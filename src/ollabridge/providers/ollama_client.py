"""Thin async client for the local Ollama runtime.

Every request resolves its base URL through runtime_settings.ollama_base_url()
at call time, so the address saved on the Local Runtimes page is the one that
chat, embeddings and model listing actually talk to (the same address that
"Test Connection" probes).
"""
from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ollabridge.core import runtime_settings as rts
from ollabridge.core.reachability import OLLAMA as _reachability
from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge")


class OllamaUnreachable(RuntimeError):
    """Ollama refused or timed out every connection attempt at base_url.

    Raised in place of tenacity's RetryError so the API can tell the caller
    which address it tried instead of leaking RetryError[<Future ...>].
    """

    def __init__(self, base_url: str, cause: BaseException) -> None:
        self.base_url = base_url
        self.cause = cause
        super().__init__(
            f"Ollama not reachable at {base_url} ({type(cause).__name__}). "
            "Make sure Ollama is running and that the Ollama base URL on the "
            "Local Runtimes page points at it."
        )


def base_url() -> str:
    """Effective Ollama base URL: the saved runtime setting, else the env setting."""
    return rts.ollama_base_url()


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _client(timeout: float) -> httpx.AsyncClient:
    """The one place that builds the HTTP client (tests inject a transport here)."""
    return httpx.AsyncClient(timeout=timeout)


# Connection-level failures: nothing answered at the address. Anything else
# (an HTTP 4xx/5xx, a read timeout mid-generation) means Ollama was reached
# and is reported as-is.
_CONNECT_FAILURES = (httpx.ConnectError, httpx.ConnectTimeout)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=0.5, max=4),
    reraise=True,  # surface the real exception, not RetryError[<Future ...>]
)
async def _post_json(base: str, path: str, payload: dict, timeout: float) -> dict:
    async with _client(timeout) as client:
        r = await client.post(_join(base, path), json=payload)
        r.raise_for_status()
        return r.json()


async def _post(path: str, payload: dict, timeout: float = 120) -> dict:
    base = base_url()
    try:
        data = await _post_json(base, path, payload, timeout)
    except _CONNECT_FAILURES as exc:
        _reachability.failure(base, exc)
        raise OllamaUnreachable(base, exc) from exc
    _reachability.success(base)
    return data


async def chat_message(
    model: str,
    messages: list[dict],
    options: dict | None = None,
    tools: list[dict] | None = None,
) -> dict:
    """Return Ollama's full assistant message, including any tool_calls.

    Ollama's native /api/chat already accepts a tools array and returns
    message.tool_calls; this surfaces that instead of discarding everything
    but the text.
    """
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    data = await _post(settings.OLLAMA_CHAT_PATH, payload)
    return data.get("message", {}) or {}


async def chat(model: str, messages: list[dict], options: dict | None = None) -> str:
    """Text-only chat. Signature and return type unchanged for existing callers."""
    message = await chat_message(model=model, messages=messages, options=options)
    return message.get("content", "") or ""


async def embeddings(model: str, text: str) -> list[float]:
    data = await _post(settings.OLLAMA_EMBED_PATH, {"model": model, "prompt": text})
    # Ollama returns {embedding: [...]}
    return data.get("embedding", [])


async def list_models() -> list[str]:
    """Model names from /api/tags. Best-effort: an empty list when Ollama
    cannot be listed. The failure is reported to the shared reachability
    monitor, which logs the address once per outage (plus reminders) rather
    than on every dashboard poll."""
    base = base_url()
    async with _client(15) as client:
        try:
            r = await client.get(_join(base, "/api/tags"))
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 - listing is best-effort
            _reachability.failure(base, exc)
            return []
    _reachability.success(base)
    models: list[str] = []
    for m in data.get("models", []) or []:
        name = m.get("name")
        if name:
            models.append(name)
    return models
