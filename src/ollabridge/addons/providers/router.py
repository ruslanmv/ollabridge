"""
Provider router — selects the best provider for each request.

Supports:
- Model alias resolution (free-best, free-fast, local-private, etc.)
- Concrete model routing (finds providers that serve the requested model)
- Score-based ranking with health, latency, tier, and quota awareness
- Automatic failover to next-best candidate
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderConfig,
    RouteResult,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.scoring import compute_score

logger = logging.getLogger(__name__)


class ProviderRouter:
    """Routes chat requests to the best available provider."""

    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def _is_available(self, config: ProviderConfig) -> bool:
        """Check if a provider is enabled and not in a terminal health state."""
        if not config.enabled:
            return False
        state = self.registry.get_state(config.id)
        if not state:
            return False
        if state.health in (HealthStatus.DOWN, HealthStatus.MAINTENANCE, HealthStatus.QUOTA_EXHAUSTED):
            return False
        return True

    def _rank_candidates(self, candidates: list[tuple[ProviderConfig, str]]) -> list[RouteResult]:
        """Score and rank a list of (config, model) candidates."""
        scored: list[RouteResult] = []
        for config, model in candidates:
            state = self.registry.get_state(config.id)
            if not state:
                continue
            score = compute_score(config, state)
            scored.append(RouteResult(
                provider_id=config.id,
                provider_config=config,
                model=model,
                score=score,
                reason=f"score={score:.3f} health={state.health.value} tier={config.tier.value}",
            ))
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    def resolve(self, model_or_alias: str) -> list[RouteResult]:
        """
        Resolve a model name or alias to a ranked list of routing candidates.

        If the name matches an alias, expand it to the candidate list.
        If not, look for any enabled provider that lists this model in its tags or
        fall back to providers with matching kind.

        Returns a list of RouteResult sorted by score (best first).
        """
        # 1. Check if it's an alias
        alias_candidates = self.registry.resolve_alias(model_or_alias)
        if alias_candidates:
            candidates: list[tuple[ProviderConfig, str]] = []
            for ac in alias_candidates:
                config = self.registry.get_config(ac.provider)
                if config and self._is_available(config):
                    candidates.append((config, ac.model))
            return self._rank_candidates(candidates)

        # 2. Not an alias — try all enabled providers with the concrete model
        candidates = []
        for config in self.registry.list_enabled():
            if self._is_available(config):
                candidates.append((config, model_or_alias))
        return self._rank_candidates(candidates)

    async def route_chat(
        self,
        model_or_alias: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict:
        """
        Route a chat request to the best provider with automatic failover.

        Tries candidates in score order. On failure, moves to the next.
        Returns the first successful OpenAI-compatible response dict.
        Raises RuntimeError if all candidates fail.
        """
        candidates = self.resolve(model_or_alias)
        if not candidates:
            raise RuntimeError(
                f"No available provider for model/alias '{model_or_alias}'. "
                "Check provider health and quotas."
            )

        last_error: Exception | None = None
        for route in candidates:
            adapter = self.registry.get_adapter(route.provider_id)
            if not adapter:
                continue

            start = time.monotonic()
            try:
                logger.info(
                    "Routing to %s (model=%s score=%.3f)",
                    route.provider_id, route.model, route.score,
                )
                result = await adapter.chat(route.model, messages, **kwargs)
                latency_ms = (time.monotonic() - start) * 1000

                # Extract token usage for quota tracking
                usage = result.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, tokens=total_tokens, success=True
                )

                logger.info(
                    "Provider %s responded in %.0fms (tokens=%d)",
                    route.provider_id, latency_ms, total_tokens,
                )
                return result

            except Exception as exc:
                latency_ms = (time.monotonic() - start) * 1000
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, success=False
                )
                logger.warning(
                    "Provider %s failed (%.0fms): %s — trying next candidate",
                    route.provider_id, latency_ms, exc,
                )
                last_error = exc

        raise RuntimeError(
            f"All providers failed for '{model_or_alias}'. Last error: {last_error}"
        )
