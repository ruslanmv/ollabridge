"""
Provider registry — holds all provider configs and runtime state.

Thread-safe (uses asyncio lock) for concurrent request handling.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ollabridge.addons.providers.models import (
    AliasCandidate,
    HealthStatus,
    ProviderConfig,
    ProviderState,
)
from ollabridge.addons.providers.base import BaseProviderAdapter

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """In-memory registry of providers, their state, and adapters."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._configs: dict[str, ProviderConfig] = {}
        self._states: dict[str, ProviderState] = {}
        self._adapters: dict[str, BaseProviderAdapter] = {}
        self._aliases: dict[str, list[AliasCandidate]] = {}

    # ── Registration ────────────────────────────────────────

    async def register(self, config: ProviderConfig, adapter: BaseProviderAdapter) -> None:
        async with self._lock:
            self._configs[config.id] = config
            self._adapters[config.id] = adapter
            if config.id not in self._states:
                self._states[config.id] = ProviderState(provider_id=config.id)
            logger.info("Registered provider: %s (%s)", config.id, config.kind)

    async def unregister(self, provider_id: str) -> None:
        async with self._lock:
            self._configs.pop(provider_id, None)
            self._states.pop(provider_id, None)
            self._adapters.pop(provider_id, None)

    # ── Aliases ─────────────────────────────────────────────

    def set_aliases(self, aliases: dict[str, list[AliasCandidate]]) -> None:
        self._aliases = aliases

    def resolve_alias(self, alias: str) -> list[AliasCandidate] | None:
        return self._aliases.get(alias)

    def is_alias(self, name: str) -> bool:
        return name in self._aliases

    @property
    def aliases(self) -> dict[str, list[AliasCandidate]]:
        return dict(self._aliases)

    # ── Lookups ─────────────────────────────────────────────

    def get_config(self, provider_id: str) -> Optional[ProviderConfig]:
        return self._configs.get(provider_id)

    def get_state(self, provider_id: str) -> Optional[ProviderState]:
        return self._states.get(provider_id)

    def get_adapter(self, provider_id: str) -> Optional[BaseProviderAdapter]:
        return self._adapters.get(provider_id)

    def list_providers(self) -> list[ProviderConfig]:
        return list(self._configs.values())

    def list_enabled(self) -> list[ProviderConfig]:
        return [c for c in self._configs.values() if c.enabled]

    # ── State updates ───────────────────────────────────────

    async def update_health(self, provider_id: str, health: HealthStatus, error: str | None = None) -> None:
        async with self._lock:
            state = self._states.get(provider_id)
            if not state:
                return
            state.health = health
            state.last_error = error
            if health == HealthStatus.HEALTHY:
                state.consecutive_failures = 0
            else:
                state.consecutive_failures += 1

    async def record_request(
        self, provider_id: str, latency_ms: float, tokens: int = 0, success: bool = True
    ) -> None:
        async with self._lock:
            state = self._states.get(provider_id)
            if not state:
                return
            state.request_count += 1
            state.monthly_requests_used += 1
            state.monthly_tokens_used += tokens

            # Exponential moving average for latency
            if state.avg_latency_ms == 0:
                state.avg_latency_ms = latency_ms
            else:
                state.avg_latency_ms = state.avg_latency_ms * 0.8 + latency_ms * 0.2

            if not success:
                state.consecutive_failures += 1
                if state.consecutive_failures >= 3:
                    state.health = HealthStatus.DEGRADED
            else:
                state.consecutive_failures = 0
                state.health = HealthStatus.HEALTHY

            # Auto-exhaust when over budget
            if state.is_quota_exhausted:
                state.health = HealthStatus.QUOTA_EXHAUSTED

    @property
    def provider_count(self) -> int:
        return len(self._configs)

    @property
    def enabled_count(self) -> int:
        return len([c for c in self._configs.values() if c.enabled])
