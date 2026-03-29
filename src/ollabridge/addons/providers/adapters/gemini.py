"""
Google Gemini API adapter.

Gemini uses its own REST format at generativelanguage.googleapis.com.
This adapter translates OpenAI-style messages to Gemini's format and back.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class GeminiAdapter(BaseProviderAdapter):
    """Adapter for the Google Gemini generative language API."""

    def _chat_url(self, model: str) -> str:
        return (
            f"{self.base_url}/v1beta/models/{model}:generateContent"
            f"?key={self.api_key}"
        )

    def _models_url(self) -> str:
        return f"{self.base_url}/v1beta/models?key={self.api_key}"

    @staticmethod
    def _to_gemini_messages(messages: list[dict]) -> list[dict]:
        """Convert OpenAI messages to Gemini content format."""
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            # Gemini uses "user" and "model" roles
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": msg.get("content", "")}],
            })
        return contents

    @staticmethod
    def _from_gemini_response(data: dict, model: str) -> dict:
        """Convert Gemini response to OpenAI-compatible format."""
        candidates = data.get("candidates", [])
        content = ""
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

        usage_meta = data.get("usageMetadata", {})
        return {
            "id": "chatcmpl-gemini",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                "total_tokens": usage_meta.get("totalTokenCount", 0),
            },
            "model": model,
        }

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        payload: dict[str, Any] = {
            "contents": self._to_gemini_messages(messages),
        }
        generation_config: dict[str, Any] = {}
        if kwargs.get("temperature") is not None:
            generation_config["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens") is not None:
            generation_config["maxOutputTokens"] = kwargs["max_tokens"]
        if generation_config:
            payload["generationConfig"] = generation_config

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self._chat_url(model),
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return self._from_gemini_response(resp.json(), model)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._models_url())
                return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(self._models_url())
                resp.raise_for_status()
                data = resp.json()
                return [
                    {"id": m.get("name", "").replace("models/", ""), "object": "model"}
                    for m in data.get("models", [])
                ]
        except Exception as exc:
            logger.warning("Gemini list_models failed: %s", exc)
            return []
