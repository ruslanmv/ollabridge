"""
Provider scoring — ranks candidates for routing decisions.

Formula:
    score =
        40% health
        20% latency
        15% tier
        10% token budget remaining
        10% request budget remaining
         5% provider priority
"""

from __future__ import annotations

from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderConfig,
    ProviderState,
    ProviderTier,
)


def _health_score(state: ProviderState) -> float:
    """0.0 – 1.0 based on health status."""
    return {
        HealthStatus.HEALTHY: 1.0,
        HealthStatus.DEGRADED: 0.4,
        HealthStatus.DOWN: 0.0,
        HealthStatus.MAINTENANCE: 0.0,
        HealthStatus.QUOTA_EXHAUSTED: 0.0,
        HealthStatus.UNKNOWN: 0.5,
    }.get(state.health, 0.0)


def _latency_score(state: ProviderState) -> float:
    """0.0 – 1.0: lower latency = higher score."""
    if state.avg_latency_ms <= 0:
        return 0.5  # unknown
    if state.avg_latency_ms < 500:
        return 1.0
    if state.avg_latency_ms < 1000:
        return 0.8
    if state.avg_latency_ms < 2000:
        return 0.6
    if state.avg_latency_ms < 5000:
        return 0.3
    return 0.1


def _tier_score(config: ProviderConfig) -> float:
    """main = 1.0, secondary = 0.5."""
    return 1.0 if config.tier == ProviderTier.MAIN else 0.5


def _token_budget_score(state: ProviderState) -> float:
    """1.0 if plenty of budget, drops as usage approaches limit."""
    ratio = state.token_usage_ratio
    if ratio <= 0:
        return 1.0  # unlimited or no usage
    if ratio < 0.5:
        return 1.0
    if ratio < 0.85:
        return 0.6
    if ratio < 1.0:
        return 0.2
    return 0.0  # exhausted


def _request_budget_score(state: ProviderState) -> float:
    """Same shape as token budget score."""
    ratio = state.request_usage_ratio
    if ratio <= 0:
        return 1.0
    if ratio < 0.5:
        return 1.0
    if ratio < 0.85:
        return 0.6
    if ratio < 1.0:
        return 0.2
    return 0.0


def _priority_score(config: ProviderConfig) -> float:
    """Normalize priority (0–200 range) to 0.0–1.0."""
    return min(max(config.priority / 200.0, 0.0), 1.0)


def compute_score(config: ProviderConfig, state: ProviderState) -> float:
    """
    Compute a weighted composite score for a provider candidate.

    Returns a value between 0.0 and 1.0.
    """
    return (
        0.40 * _health_score(state)
        + 0.20 * _latency_score(state)
        + 0.15 * _tier_score(config)
        + 0.10 * _token_budget_score(state)
        + 0.10 * _request_budget_score(state)
        + 0.05 * _priority_score(config)
    )
