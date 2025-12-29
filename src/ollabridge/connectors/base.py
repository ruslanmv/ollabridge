from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional


class Connector(ABC):
    """A connector knows how to execute a request against a runtime node."""

    @abstractmethod
    async def chat(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a chat request and return the upstream JSON."""

    @abstractmethod
    async def embeddings(self, *, base: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute an embeddings request and return the upstream JSON."""

    async def models(self, *, base: str) -> dict[str, Any]:
        """Best-effort list models."""
        return {"data": []}
