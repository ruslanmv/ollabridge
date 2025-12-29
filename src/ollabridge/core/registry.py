from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class RuntimeNodeState:
    """In-memory, real-time view of a connected node."""

    node_id: str
    connector: str  # "relay_link" | "direct_endpoint"
    endpoint: Optional[str] = None  # e.g. http://127.0.0.1:... for direct
    tags: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    capacity: int = 1
    meta: dict[str, Any] = field(default_factory=dict)
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    healthy: bool = True


class RuntimeRegistry:
    """In-memory registry for live node connections.

    Persistent data (routes, audit logs, etc.) should live in the DB.
    This registry is strictly for real-time routing.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._nodes: dict[str, RuntimeNodeState] = {}

    async def upsert(self, node: RuntimeNodeState) -> None:
        async with self._lock:
            node.last_seen = datetime.now(timezone.utc)
            self._nodes[node.node_id] = node

    async def touch(self, node_id: str, *, healthy: Optional[bool] = None) -> None:
        async with self._lock:
            n = self._nodes.get(node_id)
            if not n:
                return
            n.last_seen = datetime.now(timezone.utc)
            if healthy is not None:
                n.healthy = healthy

    async def remove(self, node_id: str) -> None:
        async with self._lock:
            self._nodes.pop(node_id, None)

    async def get(self, node_id: str) -> Optional[RuntimeNodeState]:
        async with self._lock:
            return self._nodes.get(node_id)

    async def list(self) -> list[RuntimeNodeState]:
        async with self._lock:
            return list(self._nodes.values())
