"""Hugging Face Inference Providers adapter (v2 — OpenAI-compatible router).

Uses Hugging Face's current OpenAI-compatible endpoint:

    GET  https://router.huggingface.co/v1/models
    POST https://router.huggingface.co/v1/chat/completions

The old ``/hf/{model}/v1/chat/completions`` shape is deprecated and removed.

Concrete model ids can pin a specific upstream inference provider using
the ``model_id:provider`` notation that HF's router understands natively,
for example::

    deepseek-ai/DeepSeek-V3:together
    meta-llama/Llama-3.3-70B-Instruct:groq
    Qwen/Qwen2.5-VL-72B-Instruct:novita

When no ``:provider`` suffix is present, Hugging Face picks the upstream
provider itself based on availability and the user's account settings.

Free-credit safety:
    * 402 → ``ProviderQuotaExceeded`` (HF monthly credits exhausted)
    * 429 → ``ProviderQuotaExceeded`` (rate-limited)
    * 401/403 → ``ProviderAuthError``
    * 5xx / network → ``ProviderUnavailable``
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
    ProviderTimeout,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)


HF_ROUTER_BASE = "https://router.huggingface.co"

# Parameters we forward to /v1/chat/completions when present.
_PASSTHROUGH_PARAMS = (
    "temperature",
    "max_tokens",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "seed",
    "tools",
    "tool_choice",
    "response_format",
    "reasoning_effort",
    "logprobs",
    "top_logprobs",
    "n",
    "user",
)


class HuggingFaceAdapter(BaseProviderAdapter):
    """Adapter for Hugging Face Inference Providers via the OpenAI-compatible
    router endpoint.

    Args:
        base_url: HF router base. Defaults to ``https://router.huggingface.co``.
            ``/v1`` is appended automatically.
        api_key: A user HF token (``hf_...``). Optional but strongly
            recommended — without it requests share an anonymous quota.
        timeout: Per-request timeout in seconds.
        bill_to: Optional HF organization slug to bill against, sent as
            the ``X-HF-Bill-To`` header. Use when an org member wants
            requests counted against the org's credits.
    """

    def __init__(
        self,
        base_url: str = HF_ROUTER_BASE,
        api_key: str | None = None,
        timeout: float = 120.0,
        bill_to: str | None = None,
    ) -> None:
        super().__init__(base_url=base_url or HF_ROUTER_BASE, api_key=api_key, timeout=timeout)
        self.bill_to = bill_to

    # ── HTTP plumbing ───────────────────────────────────────

    def _api_base(self) -> str:
        # Accept either "https://router.huggingface.co" or
        # "https://router.huggingface.co/v1" in config.
        if self.base_url.endswith("/v1"):
            return self.base_url
        return f"{self.base_url}/v1"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.bill_to:
            headers["X-HF-Bill-To"] = self.bill_to
        return headers

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return

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

    # ── Public surface ──────────────────────────────────────

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        """Send an OpenAI-compatible chat completion through HF's router.

        ``model`` accepts either a bare model id (``deepseek-ai/DeepSeek-V3``)
        or a pinned model:provider pair (``deepseek-ai/DeepSeek-V3:together``).
        Multimodal messages with ``image_url`` content parts are forwarded
        unchanged — HF's router supports them on VLM models.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        for key in _PASSTHROUGH_PARAMS:
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]

        url = f"{self._api_base()}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Hugging Face request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Hugging Face network error: {exc}") from exc

        self._raise_for_status(response)
        return response.json()

    async def list_models(self) -> list[dict]:
        """List models currently served by HF Inference Providers.

        Returns the raw ``data`` array from ``GET /v1/models``: each entry
        carries provider, status, context length, pricing, tool support,
        structured-output support, first-token latency and throughput.
        """
        url = f"{self._api_base()}/models"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Hugging Face network error: {exc}") from exc

        self._raise_for_status(response)
        body = response.json()
        return body.get("data", []) if isinstance(body, dict) else []

    async def health_check(self) -> bool:
        """Cheap reachability probe against ``/v1/models``."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self._api_base()}/models", headers=self._headers()
                )
                # 401/403 still means HF is reachable — we just don't have a token.
                return response.status_code < 500
        except Exception:
            return False
