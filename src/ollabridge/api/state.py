from __future__ import annotations

from dataclasses import dataclass

from ollabridge.connectors.direct_endpoint import DirectEndpointConnector
from ollabridge.core.registry import RuntimeRegistry
from ollabridge.core.router import Router


@dataclass
class AppState:
    registry: RuntimeRegistry
    router: Router
    direct: DirectEndpointConnector


def build_state() -> AppState:
    registry = RuntimeRegistry()
    router = Router(registry)
    return AppState(registry=registry, router=router, direct=DirectEndpointConnector())
