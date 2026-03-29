"""
Generic OpenAI-compatible adapter.

Works with any provider that speaks the OpenAI /v1/chat/completions format.
This is the base for Groq, DeepSeek, OpenRouter, and similar APIs.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseProviderAdapter):
    """Adapter for any OpenAI-compatible chat completions API."""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat_url(self) -> str:
        return f"{self.base_url}/v1/chat/completions"

    def _models_url(self) -> str:
        return f"{self.base_url}/v1/models"

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

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._models_url(), headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self._models_url(), headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", [])
        except Exception as exc:
            logger.warning("Failed to list models: %s", exc)
            return []
