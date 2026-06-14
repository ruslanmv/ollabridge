"""
Base adapter interface for LLM providers.

All provider adapters implement this interface so the router
can talk to any backend uniformly.
"""

from __future__ import annotations

import abc
from typing import Any


class BaseProviderAdapter(abc.ABC):
    """Abstract base for all provider adapters."""

    # Most providers are external HTTP APIs that require an API key. Adapters
    # that work without one (e.g. a local relay) override this to False. The
    # router uses ``has_credential`` to skip providers that cannot possibly
    # authenticate, instead of attempting them and logging 401/403 noise.
    requires_credential: bool = True

    def __init__(
        self, base_url: str, api_key: str | None = None, timeout: float = 120.0
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @property
    def has_credential(self) -> bool:
        """True when this adapter can authenticate (or needs no credential)."""
        if not self.requires_credential:
            return True
        return bool(self.api_key and str(self.api_key).strip())

    @abc.abstractmethod
    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        """
        Send a chat completion request.

        Returns an OpenAI-compatible response dict:
            {
                "id": "...",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        """

    async def health_check(self) -> bool:
        """
        Quick connectivity check.

        Returns True if the provider is reachable and responding.
        Default implementation returns True (override for real probes).
        """
        return True

    async def list_models(self) -> list[dict]:
        """
        List models available from this provider.

        Returns a list of dicts with at least {"id": "model-name"}.
        Default returns empty list.
        """
        return []
