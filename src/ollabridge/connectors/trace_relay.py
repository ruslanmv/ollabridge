"""
Trace Relay — forwards embodiment trace batches to HomePilot's spatial memory.

ADDITIVE ONLY: New connector file. Does not modify any existing connector.
Non-destructive: acts as a transparent pass-through relay.

The 3D-Avatar-Chatbot flushes trace events to OllaBridge (since OllaBridge
is the client's primary backend). OllaBridge relays them to HomePilot's
/api/spatial/traces endpoint for persistent storage and consolidation.

Flow:
  3D-Avatar-Chatbot  ──POST /v1/traces──>  OllaBridge  ──POST /api/spatial/traces──>  HomePilot
       (client)                              (relay)                                   (storage)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)


class TraceRelay:
    """
    Relays trace event batches from the 3D client to HomePilot's
    spatial memory service.

    Thread-safe: uses a shared httpx.AsyncClient.
    """

    def __init__(self, homepilot_base: str = "", api_key: str = ""):
        self._base = homepilot_base.rstrip("/") if homepilot_base else ""
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def configure(self, homepilot_base: str, api_key: str = "") -> None:
        """Update HomePilot base URL at runtime (e.g., after pairing)."""
        self._base = homepilot_base.rstrip("/")
        self._api_key = api_key

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
            headers["X-API-Key"] = self._api_key
        return headers

    async def relay_traces(
        self,
        trace_id: str,
        persona_id: str,
        events: List[Dict[str, Any]],
        flushed_at: str = "",
    ) -> Dict[str, Any]:
        """
        Forward a batch of trace events to HomePilot.

        Args:
            trace_id: Session trace identifier from the client.
            persona_id: Persona that generated these traces.
            events: List of TraceEvent dicts.
            flushed_at: ISO-8601 timestamp of flush.

        Returns:
            Response dict from HomePilot, or error dict.
        """
        if not self._base:
            log.debug("[TraceRelay] No HomePilot base configured, buffering skipped")
            return {"relayed": False, "reason": "no_homepilot_base"}

        url = f"{self._base}/api/spatial/traces"
        payload = {
            "trace_id": trace_id,
            "persona_id": persona_id,
            "events": events,
            "flushed_at": flushed_at,
        }

        # Retry with exponential back-off (matches project convention)
        import asyncio
        max_retries = 4
        base_delay = 2.0

        for attempt in range(max_retries):
            try:
                resp = await self._client.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code < 400:
                    result = resp.json()
                    log.info(
                        "[TraceRelay] Relayed %d events (trace=%s) → %s",
                        len(events), trace_id[:8], result,
                    )
                    return {"relayed": True, **result}
                else:
                    log.warning(
                        "[TraceRelay] HTTP %d from HomePilot: %s",
                        resp.status_code, resp.text[:200],
                    )
                    if resp.status_code < 500:
                        # Client error, don't retry
                        return {
                            "relayed": False,
                            "error": f"HTTP {resp.status_code}",
                            "detail": resp.text[:200],
                        }

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                log.warning(
                    "[TraceRelay] Network error (attempt %d/%d): %s",
                    attempt + 1, max_retries, exc,
                )

            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)

        return {"relayed": False, "error": "max_retries_exceeded"}

    async def get_episodes(
        self,
        persona_id: str,
        limit: int = 5,
        min_importance: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Fetch consolidated spatial episodes from HomePilot.

        Useful for the perceive node or for client-side display.
        """
        if not self._base:
            return []

        url = f"{self._base}/api/spatial/episodes"
        params = {
            "persona_id": persona_id,
            "limit": limit,
            "min_importance": min_importance,
        }

        try:
            resp = await self._client.get(
                url, params=params, headers=self._headers()
            )
            if resp.status_code == 200:
                return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("[TraceRelay] Failed to fetch episodes: %s", exc)

        return []

    async def get_context_block(self, persona_id: str) -> str:
        """
        Fetch the pre-formatted spatial memory context block.

        Returns empty string on failure (safe for prompt injection).
        """
        if not self._base:
            return ""

        url = f"{self._base}/api/spatial/context-block"
        try:
            resp = await self._client.get(
                url,
                params={"persona_id": persona_id},
                headers=self._headers(),
            )
            if resp.status_code == 200:
                body = resp.json()
                return body.get("context_block", "")
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.warning("[TraceRelay] Failed to fetch context block: %s", exc)

        return ""
