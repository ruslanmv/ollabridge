from __future__ import annotations

from typing import Any

import httpx


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


class LocalRuntime:
    """Minimal adapter around an Ollama-like HTTP runtime."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=120)

    async def chat(self, *, model: str, messages: list[dict[str, Any]]) -> str:
        r = await self._client.post(_join(self.base_url, "/api/chat"), json={"model": model, "messages": messages, "stream": False})
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "") or ""

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
