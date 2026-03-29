"""
Provider quota management.

Tracks monthly token and request budgets per provider.
Phase 1 uses in-memory counters; Phase 2 will persist to DB.
"""

from __future__ import annotations

import datetime as dt
import logging

from ollabridge.addons.providers.models import HealthStatus
from ollabridge.addons.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def check_quota(registry: ProviderRegistry, provider_id: str) -> bool:
    """
    Check if a provider still has budget remaining.

    Returns True if the provider can accept more requests.
    """
    state = registry.get_state(provider_id)
    if not state:
        return False
    return not state.is_quota_exhausted


def reset_monthly_quotas(registry: ProviderRegistry) -> int:
    """
    Reset all monthly counters. Call this at the start of each billing month.

    Returns the number of providers reset.
    """
    now = dt.datetime.now(dt.timezone.utc)
    count = 0
    for config in registry.list_providers():
        state = registry.get_state(config.id)
        if not state:
            continue
        state.monthly_tokens_used = 0
        state.monthly_requests_used = 0
        state.budget_reset_at = now
        # Restore health if it was quota-exhausted
        if state.health == HealthStatus.QUOTA_EXHAUSTED:
            state.health = HealthStatus.UNKNOWN
        count += 1
    logger.info("Reset monthly quotas for %d providers", count)
    return count
