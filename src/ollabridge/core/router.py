from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional

from ollabridge.core.registry import RuntimeRegistry, RuntimeNodeState


@dataclass(frozen=True)
class RouteDecision:
    node: RuntimeNodeState


class Router:
    """Selects a node for a request.

    This is intentionally simple for v1. You can extend it with:
    - tag-based routing
    - per-model pinned routes
    - weighted load balancing
    - latency-aware selection
    """

    def __init__(self, registry: RuntimeRegistry) -> None:
        self.registry = registry
        self._rr_counter = 0

    async def choose_node(self, *, model: str | None = None, require_model: bool = False) -> RouteDecision:
        nodes = [n for n in await self.registry.list() if n.healthy]
        if require_model and model:
            nodes = [n for n in nodes if model in (n.models or [])]
        if not nodes:
            raise RuntimeError("no healthy runtimes available")

        # round-robin over available nodes
        # Create a stable order by node_id
        nodes = sorted(nodes, key=lambda n: n.node_id)
        idx = self._rr_counter % len(nodes)
        self._rr_counter += 1
        return RouteDecision(node=nodes[idx])
