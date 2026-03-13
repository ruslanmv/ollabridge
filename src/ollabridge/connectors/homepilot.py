"""HomePilot Connector — routes chat requests to a HomePilot persona backend.

HomePilot exposes personas as OpenAI-compatible /v1/chat/completions endpoints.
Model naming convention:
  - "persona:<project_id>"  → specific persona project
  - "personality:<id>"      → built-in personality agent

This connector translates OllaBridge chat requests into HomePilot's
OpenAI-compatible format, enabling any OllaBridge client (including
3D-Avatar-Chatbot) to chat with HomePilot personas seamlessly.
"""
from __future__ import annotations

from typing import Any

import httpx

from ollabridge.connectors.base import Connector


class HomePilotConnector(Connector):
    """Connects to a HomePilot instance via its OpenAI-compatible API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self, api_key: str = "") -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key
        return headers

    async def chat(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{base.rstrip('/')}/v1/chat/completions"

        request_body: dict[str, Any] = {
            "model": payload.get("model", "default"),
            "messages": payload.get("messages", []),
            "stream": False,
        }

        passthrough_fields = (
            "temperature",
            "max_tokens",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "stop",
            "seed",
            "user",
        )
        for field in passthrough_fields:
            if field in payload and payload[field] is not None:
                request_body[field] = payload[field]

        api_key = str(payload.get("api_key") or "")
        headers = self._headers(api_key)

        response = await self._client.post(url, json=request_body, headers=headers)
        response.raise_for_status()
        data = response.json()

        content = ""
        choices = data.get("choices", [])
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                content = str(message.get("content", "") or "")

        result: dict[str, Any] = {
            "content": content,
            "raw": data,
        }

        usage = data.get("usage")
        if isinstance(usage, dict):
            result["usage"] = usage

        model_name = data.get("model")
        if model_name:
            result["model"] = model_name

        return result

    async def embeddings(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"embedding": []}

    async def models(self, *, base: str, api_key: str = "") -> dict[str, Any]:
        url = f"{base.rstrip('/')}/v1/models"
        headers = self._headers(api_key)
        try:
            response = await self._client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data
            return {"data": []}
        except Exception:
            return {"data": []}

    async def list_persona_models(self, *, base: str, api_key: str = "") -> list[str]:
        data = await self.models(base=base, api_key=api_key)
        result: list[str] = []

        for item in data.get("data", []):
            if isinstance(item, dict):
                model_id = item.get("id")
                if model_id:
                    result.append(str(model_id))

        return result