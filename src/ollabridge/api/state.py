from __future__ import annotations

from dataclasses import dataclass

from ollabridge.connectors.direct_endpoint import DirectEndpointConnector
from ollabridge.core.consumer_registry import ConsumerRegistry
from ollabridge.core.registry import RuntimeRegistry
from ollabridge.core.router import Router
from ollabridge.core.session_bridge import SessionBridge


@dataclass
class AppState:
    registry: RuntimeRegistry
    router: Router
    direct: DirectEndpointConnector
    consumers: ConsumerRegistry
    sessions: SessionBridge


def build_state() -> AppState:
    registry = RuntimeRegistry()
    router = Router(registry)
    return AppState(
        registry=registry,
        router=router,
        direct=DirectEndpointConnector(),
        consumers=ConsumerRegistry(),
        sessions=SessionBridge(),
    )
