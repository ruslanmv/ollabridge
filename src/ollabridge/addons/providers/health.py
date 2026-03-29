"""
Provider health checking.

Runs periodic or on-demand health probes against registered providers.
"""

from __future__ import annotations

import datetime as dt
import logging

from ollabridge.addons.providers.models import HealthStatus
from ollabridge.addons.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


async def check_provider_health(registry: ProviderRegistry, provider_id: str) -> HealthStatus:
    """Run a health check on a single provider and update its state."""
    adapter = registry.get_adapter(provider_id)
    state = registry.get_state(provider_id)
    if not adapter or not state:
        return HealthStatus.UNKNOWN

    try:
        ok = await adapter.health_check()
        new_status = HealthStatus.HEALTHY if ok else HealthStatus.DOWN
    except Exception as exc:
        logger.warning("Health check failed for %s: %s", provider_id, exc)
        new_status = HealthStatus.DOWN

    state.last_check = dt.datetime.now(dt.timezone.utc)
    await registry.update_health(provider_id, new_status)
    return new_status


async def check_all_health(registry: ProviderRegistry) -> dict[str, HealthStatus]:
    """Run health checks on all enabled providers. Returns {id: status}."""
    results: dict[str, HealthStatus] = {}
    for config in registry.list_enabled():
        status = await check_provider_health(registry, config.id)
        results[config.id] = status
    return results
