from __future__ import annotations

from typing import Any

import httpx

from ollabridge.connectors.base import Connector


class DirectEndpointConnector(Connector):
    """Calls the Node Agent over HTTP directly.

    This is the highest performance path when a node has a stable, reachable endpoint.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=120)

    async def chat(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post(f"{base.rstrip('/')}/node/v1/chat", json=payload)
        r.raise_for_status()
        return r.json()

    async def embeddings(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._client.post(f"{base.rstrip('/')}/node/v1/embeddings", json=payload)
        r.raise_for_status()
        return r.json()

    async def models(self, *, base: str) -> dict[str, Any]:
        r = await self._client.get(f"{base.rstrip('/')}/node/v1/models")
        r.raise_for_status()
        return r.json()
