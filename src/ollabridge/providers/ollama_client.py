from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ollabridge.core.settings import settings


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4))
async def chat(model: str, messages: list[dict], options: dict | None = None) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(_join(settings.OLLAMA_BASE_URL, settings.OLLAMA_CHAT_PATH), json=payload)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", "") or ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4))
async def embeddings(model: str, text: str) -> list[float]:
    payload = {"model": model, "prompt": text}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(_join(settings.OLLAMA_BASE_URL, settings.OLLAMA_EMBED_PATH), json=payload)
        r.raise_for_status()
        data = r.json()
        # Ollama returns {embedding: [...]}
        return data.get("embedding", [])


async def list_models() -> list[str]:
    # Not all versions expose a stable list endpoint; best-effort.
    # If unavailable, return empty list.
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(_join(settings.OLLAMA_BASE_URL, "/api/tags"))
            r.raise_for_status()
            data = r.json()
            models = []
            for m in data.get("models", []) or []:
                name = m.get("name")
                if name:
                    models.append(name)
            return models
        except Exception:
            return []
