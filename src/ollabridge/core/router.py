from __future__ import annotations

from dataclasses import dataclass

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

    async def choose_node(
        self,
        *,
        model: str | None = None,
        require_model: bool = False,
        require_tools: bool = False,
    ) -> RouteDecision:
        nodes = [n for n in await self.registry.list() if n.healthy]

        if require_tools:
            # Local Ollama carries tools natively. Relay nodes are eligible only
            # when their handshake advertises the capability; other connectors
            # currently drop or reject tools and must not enter round-robin.
            nodes = [
                node
                for node in nodes
                if node.connector == "local_ollama"
                or (
                    node.connector == "relay_link"
                    and "tools" in ((node.meta or {}).get("capabilities") or [])
                )
            ]

        # Smart routing: persona:* and personality:* models go to HomePilot nodes
        if model and (model.startswith("persona:") or model.startswith("personality:")):
            hp_nodes = [n for n in nodes if n.connector == "homepilot"]
            if hp_nodes:
                # Prefer HomePilot nodes for persona models
                nodes = hp_nodes

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
