"""Media generation service — text-to-image and text-to-video via Hugging Face
Inference Providers.

This is intentionally not a chat adapter — the data shapes (raw bytes,
base64, long-running jobs) don't fit the OpenAI ``chat.completion`` flow
the existing provider adapters return.

Two modern HF endpoints are used:

- ``POST https://router.huggingface.co/v1/images/generations`` — OpenAI-
  compatible image gen. Body matches ``openai.images.generate(...)``:
  ``{"model": str, "prompt": str, "n": int, "size": str, "response_format":
  "b64_json"|"url"}``.

- ``POST https://router.huggingface.co/{provider}/v1/text-to-video/{model}``
  for video, returning raw video bytes. Video generation is heavy and
  slow, so the route runs it synchronously today; if average wall time
  becomes a problem, swap the in-process call for an async job queue
  without changing the public surface.

All requests honor the same free-credit safety as the chat adapter:
HTTP 402/429 raise :class:`ProviderQuotaExceeded` and the caller can
fall over to a different alias.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Optional

import httpx

from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
    ProviderTimeout,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)


HF_ROUTER_BASE = "https://router.huggingface.co"
DEFAULT_IMAGE_TIMEOUT = 180.0
DEFAULT_VIDEO_TIMEOUT = 600.0


def _split_router_id(router_model_id: str) -> tuple[str, Optional[str]]:
    """``org/model:provider`` → (``org/model``, ``provider``)."""
    if ":" in router_model_id:
        model, provider = router_model_id.rsplit(":", 1)
        return model, provider
    return router_model_id, None


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    body_snippet = ""
    if response.headers.get("content-type", "").startswith("application/json"):
        try:
            body_snippet = str(response.json())[:500]
        except ValueError:
            body_snippet = response.text[:500]
    else:
        body_snippet = response.text[:500] if response.text else ""

    if response.status_code in (401, 403):
        raise ProviderAuthError(
            f"Hugging Face rejected the token ({response.status_code}): {body_snippet}"
        )
    if response.status_code in (402, 429):
        err = ProviderQuotaExceeded(
            f"Hugging Face credits or rate limit exhausted "
            f"({response.status_code}): {body_snippet}"
        )
        err.upstream_status = response.status_code
        raise err
    if response.status_code >= 500:
        err = ProviderUnavailable(
            f"Hugging Face upstream error {response.status_code}: {body_snippet}"
        )
        err.upstream_status = response.status_code
        raise err
    err = ProviderBadRequest(
        f"Hugging Face rejected the request ({response.status_code}): {body_snippet}"
    )
    err.upstream_status = response.status_code
    raise err


def _auth_headers(api_key: Optional[str], bill_to: Optional[str]) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if bill_to:
        headers["X-HF-Bill-To"] = bill_to
    return headers


class HFMediaService:
    """Synchronous image/video generation through HF Inference Providers."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        bill_to: Optional[str] = None,
        base_url: str = HF_ROUTER_BASE,
    ) -> None:
        self.api_key = api_key
        self.bill_to = bill_to
        self.base_url = base_url.rstrip("/")

    # ── Public API ──────────────────────────────────────────

    async def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        n: int = 1,
        size: str = "1024x1024",
        response_format: str = "b64_json",
        timeout: float = DEFAULT_IMAGE_TIMEOUT,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate ``n`` images via the OpenAI-compatible router endpoint.

        Returns the upstream JSON unchanged when it already matches the
        OpenAI ``images.generate`` response. When HF returns raw image
        bytes (the older per-model inference endpoint), we wrap them into
        ``{"data": [{"b64_json": "..."}]}`` so the response surface is
        identical regardless of which upstream served the request.
        """
        url = f"{self.base_url}/v1/images/generations"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "size": size,
            "response_format": response_format,
        }
        if extra:
            payload.update({k: v for k, v in extra.items() if v is not None})

        headers = {"Content-Type": "application/json", **_auth_headers(self.api_key, self.bill_to)}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"HF image gen timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"HF image gen transport error: {exc}") from exc

        _raise_for_status(response)

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            return response.json()

        # Raw bytes fallback — wrap into OpenAI shape.
        b64 = base64.b64encode(response.content).decode("ascii")
        return {
            "created": int(time.time()),
            "data": [{"b64_json": b64}],
            "model": model,
            "_content_type": content_type or "image/png",
        }

    async def generate_video(
        self,
        *,
        model: str,
        prompt: str,
        num_frames: int = 32,
        timeout: float = DEFAULT_VIDEO_TIMEOUT,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a single video via the per-model inference endpoint.

        Returns ``{"data": [{"b64_video": "...", "content_type": "video/mp4"}], ...}``.
        Video gen is heavy: the caller should treat the request as long-
        running and avoid blocking UI threads.
        """
        bare_model, upstream = _split_router_id(model)
        if upstream:
            url = f"{self.base_url}/{upstream}/v1/video/generations"
        else:
            url = f"{self.base_url}/v1/video/generations"

        payload: dict[str, Any] = {
            "model": bare_model,
            "prompt": prompt,
            "num_frames": num_frames,
        }
        if extra:
            payload.update({k: v for k, v in extra.items() if v is not None})

        headers = {"Content-Type": "application/json", **_auth_headers(self.api_key, self.bill_to)}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"HF video gen timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"HF video gen transport error: {exc}") from exc

        _raise_for_status(response)

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            body = response.json()
            return body

        # Raw bytes fallback.
        b64 = base64.b64encode(response.content).decode("ascii")
        return {
            "created": int(time.time()),
            "data": [{
                "b64_video": b64,
                "content_type": content_type or "video/mp4",
            }],
            "model": model,
        }
