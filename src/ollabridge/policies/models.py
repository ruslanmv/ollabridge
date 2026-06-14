"""Pydantic models for the routing policy engine (``~/.ollabridge/policies.yaml``)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

TargetType = Literal["local_device", "external_provider", "cloud_relay"]


class PolicyMatch(BaseModel):
    """What a policy applies to. At least one selector must be set."""

    alias: Optional[str] = None
    model: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "PolicyMatch":
        if not (self.alias or self.model):
            raise ValueError("policy match requires 'alias' or 'model'")
        return self


class TargetFilter(BaseModel):
    """Allow/deny entry: by target type and/or provider name."""

    type: Optional[TargetType] = None
    provider: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "TargetFilter":
        if not (self.type or self.provider):
            raise ValueError("allow/deny entry requires 'type' or 'provider'")
        return self

    def matches(self, *, target_type: TargetType, provider: str | None) -> bool:
        if self.type and self.type != target_type:
            return False
        if self.provider and (provider or "").lower() != self.provider.lower():
            return False
        return True


class PreferenceTarget(BaseModel):
    """One entry in a policy's ordered preference list."""

    provider: str  # "local" or a provider name (anthropic, groq, openrouter, …)
    model: Optional[str] = None
    device_tag: Optional[str] = None

    @property
    def is_local(self) -> bool:
        return self.provider.lower() in ("local", "local_device", "ollama")


class CapabilitySpec(BaseModel):
    """Capabilities the selected backend must support."""

    streaming: Optional[bool] = None
    tools: Optional[bool] = None
    vision: Optional[bool] = None
    embeddings: Optional[bool] = None


class RouteSpec(BaseModel):
    allow: list[TargetFilter] = Field(default_factory=list)
    deny: list[TargetFilter] = Field(default_factory=list)
    prefer: list[PreferenceTarget] = Field(default_factory=list)
    fallback: bool = True
    max_cost_usd_per_1k_tokens: Optional[float] = None
    max_latency_ms: Optional[int] = None
    require: CapabilitySpec = Field(default_factory=CapabilitySpec)


class LoggingSpec(BaseModel):
    prompt_logging: bool = False


class ScopeSpec(BaseModel):
    """Workspace/project/user/team scoping (enterprise; advisory locally)."""

    workspace: Optional[str] = None
    project: Optional[str] = None
    users: list[str] = Field(default_factory=list)
    teams: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    name: str
    match: PolicyMatch
    route: RouteSpec = Field(default_factory=RouteSpec)
    logging: LoggingSpec = Field(default_factory=LoggingSpec)
    scope: ScopeSpec = Field(default_factory=ScopeSpec)
    data_classification: Optional[str] = None  # e.g. public|internal|confidential


class PoliciesFile(BaseModel):
    policies: list[Policy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> "PoliciesFile":
        seen: set[str] = set()
        for p in self.policies:
            if p.name in seen:
                raise ValueError(f"duplicate policy name: {p.name!r}")
            seen.add(p.name)
        return self


class RouteExplanation(BaseModel):
    """The answer to ``ollabridge route explain <alias>``."""

    requested: str
    policy_name: Optional[str] = None
    selected_backend: Optional[str] = None  # "local_device" | "provider:<name>" | None
    selected_provider: Optional[str] = None
    selected_device: Optional[str] = None
    selected_model: Optional[str] = None
    cloud_relay: bool = False
    fallbacks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    prompt_logging: bool = False
    estimated_cost_usd_per_1k_tokens: Optional[float] = None
    error: Optional[str] = None
