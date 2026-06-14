"""
OllamaBridge local node adapter (not yet wired).

This adapter is a placeholder for direct provider-layer communication with
OllamaBridge relay nodes over WebSocket. Relay traffic is currently handled
by the gateway's RelayHub, not this addon adapter, so this adapter must
**never** answer a real request — doing so previously returned the
"[OllamaBridge stub] Relay integration pending." text to end users
(e.g. via OllaBridge Cloud → yourfriend.online).

Instead it raises, which makes ``ProviderRouter.route_chat`` fail over to
the next candidate (a real provider or the gateway's local/relay fallback).
The seeded ``ollama-node-*`` providers are also shipped ``enabled: false``
so they are not selected in the first place.
"""

from __future__ import annotations

import logging
from typing import Any

from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.errors import ProviderError

logger = logging.getLogger(__name__)


class OllamaBridgeAdapter(BaseProviderAdapter):
    """Placeholder adapter for local OllamaBridge relay nodes.

    Relay routing is the gateway's job (RelayHub); this addon adapter is not
    wired to it yet, so it fails fast to trigger router fail-over rather than
    returning a fake response.
    """

    # Local/relay nodes don't use an external API key.
    requires_credential = False

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        logger.warning(
            "OllamaBridgeAdapter is not wired to the relay; failing over. "
            "provider=%s model=%s",
            self.base_url,
            model,
        )
        raise ProviderError(
            "ollama_bridge addon adapter is not wired to the relay; "
            "request must fail over to another provider or the gateway relay"
        )

    async def health_check(self) -> bool:
        # Always unhealthy so the router/scorer never selects this provider.
        return False
