"""
Local runtime client.

Wraps the Ollama HTTP API the catalog cares about:

- ``GET  /api/tags``   — installed model list (catalog discovery)
- ``POST /api/show``   — per-model details (template, parameters, families)
- ``POST /api/chat``   — 1-token probe used by the per-model health check
- ``POST /api/pull``   — streaming model download (admin "Pull Model")

The client is intentionally narrow: it only owns the runtime conversation,
not the orchestration logic. Caller code (parser, sync, health) consumes
the structured returns.

Future runtimes (llama.cpp, vLLM) should expose the same shape so the rest
of the addon doesn't have to grow conditional branches.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


class LocalRuntimeClient:
    """Async client for an Ollama-style local runtime."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        *,
        timeout: float = 30.0,
        pull_timeout: float = 60 * 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pull_timeout = pull_timeout

    # ── HTTP helper ─────────────────────────────────────────

    def _http(self, *, timeout: Optional[float] = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout if timeout is not None else self.timeout,
            headers={"Accept": "application/json"},
        )

    # ── Discovery ───────────────────────────────────────────

    async def list_tags(self) -> list[dict[str, Any]]:
        """Return the raw entries from ``/api/tags`` (``models`` array)."""
        try:
            async with self._http() as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("local runtime /api/tags failed: %s", exc)
            return []

        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []
        return models

    async def show(self, model: str) -> dict[str, Any]:
        """Fetch ``/api/show`` details for one model. Empty dict on failure."""
        try:
            async with self._http() as client:
                resp = await client.post("/api/show", json={"name": model})
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {}
        except httpx.HTTPError as exc:
            logger.debug("local runtime /api/show(%s) failed: %s", model, exc)
            return {}

    async def ping(self) -> bool:
        """Cheapest reachability check — used by node health card."""
        try:
            async with self._http(timeout=5.0) as client:
                resp = await client.get("/api/tags")
                return resp.status_code < 500
        except httpx.HTTPError:
            return False

    # ── Health probe (1-token chat) ─────────────────────────

    async def probe_chat(self, model: str) -> tuple[bool, Optional[str], Optional[float]]:
        """
        Tiny ``/api/chat`` call with a single-token cap.

        Returns ``(ok, error, latency_ms)``.
        """
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "options": {"num_predict": 1},
        }
        started = time.monotonic()
        try:
            async with self._http(timeout=15.0) as client:
                resp = await client.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:
            return False, exc.__class__.__name__, None
        latency_ms = (time.monotonic() - started) * 1000.0

        if resp.status_code >= 400:
            return False, f"http_{resp.status_code}", latency_ms
        return True, None, latency_ms

    # ── Pull (streaming) ────────────────────────────────────

    async def pull_stream(self, model: str) -> AsyncIterator[dict[str, Any]]:
        """
        Stream progress events from ``POST /api/pull``.

        Each yielded dict looks like::

            {"status": "downloading", "completed": 1234, "total": 5678}

        and the stream terminates with ``{"status": "success"}``. Errors
        are forwarded as ``{"status": "error", "error": "..."}``.
        """
        url = "/api/pull"
        body = {"name": model, "stream": True}
        try:
            async with self._http(timeout=self.pull_timeout) as client:
                async with client.stream("POST", url, json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
        except httpx.HTTPError as exc:
            yield {"status": "error", "error": str(exc)}

    # ── Optional: delete (admin "Remove Local Model") ───────

    async def delete(self, model: str) -> bool:
        """Run ``ollama rm <model>`` via the HTTP API. Returns success bool."""
        try:
            async with self._http(timeout=30.0) as client:
                resp = await client.request("DELETE", "/api/delete", json={"name": model})
                return resp.status_code < 400
        except httpx.HTTPError as exc:
            logger.warning("local runtime /api/delete(%s) failed: %s", model, exc)
            return False
