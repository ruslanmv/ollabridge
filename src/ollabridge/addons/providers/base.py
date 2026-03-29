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

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

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
