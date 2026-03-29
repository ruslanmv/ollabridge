"""
OllamaBridge local node adapter (stub).

This adapter will eventually communicate with OllamaBridge relay nodes
via WebSocket. For now it provides the interface shape so the router
can treat local nodes uniformly with cloud providers.

Phase 2 will wire this to the existing RelayHub in
ollabridge.services.relay_hub.
"""

from __future__ import annotations

import logging
from typing import Any

from ollabridge.addons.providers.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class OllamaBridgeAdapter(BaseProviderAdapter):
    """Stub adapter for local OllamaBridge relay nodes."""

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        # TODO: Wire to RelayHub.request() for real relay communication
        logger.warning(
            "OllamaBridgeAdapter.chat() called but relay integration is not yet wired. "
            "provider=%s model=%s",
            self.base_url,
            model,
        )
        return {
            "id": "chatcmpl-ollama-bridge-stub",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "[OllamaBridge stub] Relay integration pending.",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "model": model,
        }

    async def health_check(self) -> bool:
        # TODO: Ping relay node via WebSocket
        return False
