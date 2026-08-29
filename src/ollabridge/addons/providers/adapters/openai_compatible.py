"""
Generic OpenAI-compatible adapter.

Works with any provider that speaks the OpenAI /v1/chat/completions format.
This is the base for Groq, DeepSeek, OpenRouter, and similar APIs.

Base URLs arrive from three places that disagree about how much of the path
they carry: the seed catalog (``https://api.groq.com``), the BYOK catalog
(``https://api.groq.com/openai/v1``) and whatever the user types into the
Sources form. :meth:`_api_base` reconciles them, so a base URL that already
carries the API root is never given a second copy of it.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderTimeout,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseProviderAdapter):
    """Adapter for any OpenAI-compatible chat completions API."""

    #: Path segment(s) between the host and the OpenAI-style resources.
    #: Groq serves them under ``/openai/v1``; most others under ``/v1``.
    api_root: str = "v1"

    def _api_base(self) -> str:
        """``base_url`` joined with :attr:`api_root`, without duplicating it.

        ``https://api.groq.com`` → ``https://api.groq.com/openai/v1``
        ``https://api.groq.com/openai`` → ``https://api.groq.com/openai/v1``
        ``https://api.groq.com/openai/v1`` → unchanged
        """
        base = self.base_url.rstrip("/")
        segments = [s for s in self.api_root.strip("/").split("/") if s]
        if not segments:
            return base
        # Drop whatever leading part of the root the base URL already carries.
        for take in range(len(segments), 0, -1):
            if base.endswith("/" + "/".join(segments[:take])):
                segments = segments[take:]
                break
        return "/".join([base, *segments]) if segments else base

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_url(self) -> str:
        return f"{self._api_base()}/chat/completions"

    def _models_url(self) -> str:
        return f"{self._api_base()}/models"

    # ── Error mapping ────────────────────────────────────────────────

    def _redact(self, text: str) -> str:
        if self.api_key:
            return text.replace(str(self.api_key), "(redacted)")
        return text

    def _map_status(self, status: int, body: str) -> ProviderError:
        """Turn an upstream HTTP status into a routing-aware error.

        A decommissioned model is the common Groq failure and comes back as a
        400 naming the model, so it maps to :class:`ProviderBadRequest` — do
        not retry the same model, but do let the router try the next one.
        """
        detail = self._redact((body or "")[:300])
        if status in (401, 403):
            exc: ProviderError = ProviderAuthError(f"HTTP {status}: {detail}")
        elif status in (402, 429):
            exc = ProviderQuotaExceeded(f"HTTP {status}: {detail}")
        elif 400 <= status < 500:
            exc = ProviderBadRequest(f"HTTP {status}: {detail}")
        else:
            exc = ProviderUnavailable(f"HTTP {status}: {detail}")
        exc.upstream_status = status
        return exc

    # ── Calls ────────────────────────────────────────────────────────

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens") is not None:
            payload["max_tokens"] = kwargs["max_tokens"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._chat_url(), json=payload, headers=self._headers()
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self._redact(f"timeout: {exc}")) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc
        if resp.status_code != 200:
            raise self._map_status(resp.status_code, resp.text)
        return resp.json()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._models_url(), headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        """Live model listing from ``{base}/models``.

        Raises a :class:`ProviderError` so the Sources API can tell "your key
        was rejected" apart from "this provider has no models" — an empty list
        is a real answer, not an error swallowed on the way out.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self._models_url(), headers=self._headers())
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(
                self._redact(f"timeout listing models: {exc}")
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc
        if resp.status_code != 200:
            raise self._map_status(resp.status_code, resp.text)
        data = resp.json()
        models = data.get("data", []) if isinstance(data, dict) else []
        return [m for m in models if isinstance(m, dict)]
