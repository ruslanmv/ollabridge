"""
Data models for the provider orchestration layer.

These are in-memory Pydantic models (not DB models).
Phase 1 is YAML-only; Phase 2 will sync to database tables.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProviderTier(str, Enum):
    MAIN = "main"
    SECONDARY = "secondary"


class ProviderCategory(str, Enum):
    FREE = "free"
    FREE_FLEX = "free-flex"
    FREE_LAB = "free-lab"
    CHEAP = "cheap"
    PAID = "paid"
    LOCAL = "local"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    MAINTENANCE = "maintenance"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNKNOWN = "unknown"


class ProviderConfig(BaseModel):
    """Static configuration for a provider, loaded from seed YAML."""

    id: str
    name: str
    kind: str  # gemini, groq, deepseek, openrouter, huggingface, ollama_bridge, openai_compatible
    enabled: bool = True
    tier: ProviderTier = ProviderTier.MAIN
    category: ProviderCategory = ProviderCategory.FREE
    priority: int = 50
    weight: int = 10
    base_url: str = ""
    credential_env: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class ProviderState(BaseModel):
    """Runtime state for a provider, tracked in memory."""

    provider_id: str
    health: HealthStatus = HealthStatus.UNKNOWN
    last_check: Optional[dt.datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    request_count: int = 0
    token_count: int = 0

    # Quota tracking (monthly)
    monthly_token_budget: int = 0       # 0 = unlimited
    monthly_request_budget: int = 0     # 0 = unlimited
    monthly_tokens_used: int = 0
    monthly_requests_used: int = 0
    budget_reset_at: Optional[dt.datetime] = None

    @property
    def token_usage_ratio(self) -> float:
        if self.monthly_token_budget <= 0:
            return 0.0
        return self.monthly_tokens_used / self.monthly_token_budget

    @property
    def request_usage_ratio(self) -> float:
        if self.monthly_request_budget <= 0:
            return 0.0
        return self.monthly_requests_used / self.monthly_request_budget

    @property
    def is_quota_exhausted(self) -> bool:
        if self.monthly_token_budget > 0 and self.monthly_tokens_used >= self.monthly_token_budget:
            return True
        if self.monthly_request_budget > 0 and self.monthly_requests_used >= self.monthly_request_budget:
            return True
        return False


class AliasCandidate(BaseModel):
    """One candidate in a model alias resolution list."""

    provider: str
    model: str


class RouteResult(BaseModel):
    """Result of a routing decision."""

    provider_id: str
    provider_config: ProviderConfig
    model: str
    score: float = 0.0
    reason: str = ""
