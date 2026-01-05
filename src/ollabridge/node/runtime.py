from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


class LocalRuntime:
    """Minimal adapter around an Ollama-like HTTP runtime."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=120)

    async def chat(self, *, model: str, messages: list[dict[str, Any]]) -> str:
        r = await self._client.post(
            _join(self.base_url, "/api/chat"),
            json={"model": model, "messages": messages, "stream": False},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "") or ""

    async def chat_stream(self, *, model: str, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """
        Stream chat tokens/chunks from Ollama.

        Ollama's /api/chat streaming responds with JSON objects separated by newlines.
        Each object often contains:
          - message.content: partial content
          - done: true when complete
        """
        url = _join(self.base_url, "/api/chat")
        async with self._client.stream(
            "POST",
            url,
            json={"model": model, "messages": messages, "stream": True},
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("done") is True:
                    break
                chunk = (obj.get("message") or {}).get("content") or ""
                if chunk:
                    yield str(chunk)

    async def embeddings(self, *, model: str, text: str) -> list[float]:
        r = await self._client.post(_join(self.base_url, "/api/embeddings"), json={"model": model, "prompt": text})
        r.raise_for_status()
        data = r.json()
        return data.get("embedding", [])

    async def list_models(self) -> list[str]:
        try:
            r = await self._client.get(_join(self.base_url, "/api/tags"))
            r.raise_for_status()
            data = r.json()
            out: list[str] = []
            for m in data.get("models", []) or []:
                name = m.get("name")
                if name:
                    out.append(name)
            return out
        except Exception:
            return []
