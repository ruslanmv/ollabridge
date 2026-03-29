"""
Hugging Face Inference API adapter.

HF serverless inference uses the router endpoint:
    https://router.huggingface.co/hf/{model}/v1/chat/completions

The base_url should be https://router.huggingface.co
(api-inference.huggingface.co is deprecated and returns 410).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class HuggingFaceAdapter(BaseProviderAdapter):
    """Adapter for Hugging Face serverless Inference API (router endpoint)."""

    def _chat_url(self, model: str) -> str:
        # router.huggingface.co/hf/{model}/v1/chat/completions
        return f"{self.base_url}/hf/{model}/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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
            resp = await client.post(
                self._chat_url(model), json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()

        # HF router returns OpenAI-compatible format
        if "choices" in data:
            return data

        # Fallback: wrap raw text response (legacy format)
        text = ""
        if isinstance(data, list) and data:
            text = data[0].get("generated_text", "")
        elif isinstance(data, dict):
            text = data.get("generated_text", "")

        return {
            "id": "chatcmpl-hf",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": model,
        }

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Simple GET to the router base — returns 200 if reachable
                resp = await client.get(self.base_url, headers=self._headers())
                return resp.status_code < 500
        except Exception:
            return False
