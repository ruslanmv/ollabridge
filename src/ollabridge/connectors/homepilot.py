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
    """Connects to a HomePilot instance via its OpenAI-compatible API.

    Configuration:
        base: The HomePilot backend URL (e.g. http://localhost:8000)
        api_key: HomePilot API key (from API_KEY env var on HomePilot side)
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=120)

    async def chat(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a chat request to HomePilot's OpenAI-compatible endpoint.

        Args:
            base: HomePilot base URL (e.g. http://localhost:8000)
            payload: Dict with 'model', 'messages', optional 'temperature', 'max_tokens'

        Returns:
            Dict with 'content' key containing the assistant response.
        """
        url = f"{base.rstrip('/')}/v1/chat/completions"

        # Build request in OpenAI format
        request_body = {
            "model": payload.get("model", "default"),
            "messages": payload.get("messages", []),
        }
        if "temperature" in payload:
            request_body["temperature"] = payload["temperature"]
        if "max_tokens" in payload:
            request_body["max_tokens"] = payload["max_tokens"]

        # HomePilot uses API_KEY header authentication
        headers = {}
        api_key = payload.get("api_key") or ""
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        r = await self._client.post(url, json=request_body, headers=headers)
        r.raise_for_status()
        data = r.json()

        # Extract content from OpenAI-format response
        content = ""
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        return {"content": content}

    async def embeddings(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        """HomePilot does not support embeddings — returns empty."""
        return {"embedding": []}

    async def models(self, *, base: str) -> dict[str, Any]:
        """List available HomePilot models (personas + personalities).

        Args:
            base: HomePilot base URL

        Returns:
            Dict with 'data' key containing model list.
        """
        url = f"{base.rstrip('/')}/v1/models"
        try:
            r = await self._client.get(url)
            r.raise_for_status()
            data = r.json()
            return data
        except Exception:
            return {"data": []}

    async def list_persona_models(self, *, base: str, api_key: str = "") -> list[str]:
        """Convenience: return just the model ID strings.

        Useful for node registration — the node reports which models it serves.
        """
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            r = await self._client.get(f"{base.rstrip('/')}/v1/models", headers=headers)
            r.raise_for_status()
            data = r.json()
            return [m["id"] for m in data.get("data", []) if m.get("id")]
        except Exception:
            return []
