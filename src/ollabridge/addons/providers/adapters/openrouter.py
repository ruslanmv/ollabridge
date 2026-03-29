"""
OpenRouter API adapter.

OpenRouter is an aggregator that speaks OpenAI-compatible format.
Free models are suffixed with `:free` in their model IDs.
"""

from __future__ import annotations

from typing import Any

import httpx

from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """Adapter for the OpenRouter aggregator API."""

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # OpenRouter recommends setting HTTP-Referer and X-Title
        headers["HTTP-Referer"] = "https://ollabridge.app"
        headers["X-Title"] = "OllaBridge Cloud"
        return headers

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

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self._chat_url(), json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
