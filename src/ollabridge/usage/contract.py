"""Shared usage-event contract (``ollabridge-usage/1``).

VENDORED FILE — an identical copy lives in both OllaBridge repositories
(``ollabridge/usage/contract.py`` and ``ollabridge_cloud/usage/contract.py``).
``tests/conformance/test_usage_contract.py`` pins its hash; change both copies
together.

One :class:`UsageEvent` describes one real inference attempt. The schema is
metadata only: it has no field that can carry prompt or response text, and it
rejects unknown fields.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1

Source = Literal[
    "cloud_gateway",
    "cloud_relay",
    "local_gateway",
    "claude_code_otel",
    "node_job",
    "provider_import",
]
Execution = Literal["local_device", "org_device", "provider_api", "managed"]
BillingMode = Literal["api", "subscription", "local", "free_tier"]
Measurement = Literal[
    "provider_billed",
    "provider_reported",
    "locally_observed",
    "estimated",
    "unavailable",
]
Status = Literal["completed", "failed", "interrupted"]

#: Higher wins when the same event arrives twice.
MEASUREMENT_RANK: Dict[str, int] = {
    "unavailable": 0,
    "estimated": 1,
    "locally_observed": 2,
    "provider_reported": 3,
    "provider_billed": 4,
}

#: Dashboard badge for each measurement class.
MEASUREMENT_BADGE: Dict[str, str] = {
    "provider_billed": "verified",
    "provider_reported": "verified",
    "locally_observed": "observed",
    "estimated": "estimated",
    "unavailable": "unavailable",
}

TOKEN_DIMENSIONS = (
    "input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_LABEL_RE = re.compile(r"[^A-Za-z0-9 ._:/@+\-]")
_MAX_INT = 2**53


def new_event_id() -> str:
    """A fresh attempt id (also the idempotency key)."""
    return f"att_{uuid.uuid4().hex}"


def clean_label(value: Optional[str], max_len: int = 128) -> Optional[str]:
    """Reduce a caller-supplied label to a safe, bounded token.

    Labels arrive from headers and telemetry, so they are treated as hostile:
    anything outside a small character set is dropped and the result is capped.
    """
    if value is None:
        return None
    cleaned = _LABEL_RE.sub("", str(value)).strip()[:max_len]
    return cleaned or None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Usage(_Strict):
    """Disjoint token dimensions. ``None`` means unknown, never zero."""

    input_tokens: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    cache_read_tokens: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    cache_write_tokens: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    output_tokens: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    #: Non-token billable units, e.g. ``{"gpu_seconds": 12.5, "images": 1}``.
    other_units: Dict[str, float] = Field(default_factory=dict)

    @field_validator("other_units")
    @classmethod
    def _bounded_units(cls, value: Dict[str, float]) -> Dict[str, float]:
        if len(value) > 8:
            raise ValueError("other_units accepts at most 8 entries")
        out: Dict[str, float] = {}
        for key, amount in value.items():
            label = clean_label(key, 32)
            if not label or amount < 0:
                raise ValueError("invalid other_units entry")
            out[label] = float(amount)
        return out

    @property
    def known(self) -> bool:
        return any(getattr(self, d) is not None for d in TOKEN_DIMENSIONS)

    @property
    def total_tokens(self) -> Optional[int]:
        """Sum of the dimensions that are known; ``None`` if none are."""
        if not self.known:
            return None
        return sum(getattr(self, d) or 0 for d in TOKEN_DIMENSIONS)


class Cost(_Strict):
    """Money in integer micro-units of ``currency`` (1 USD = 1_000_000)."""

    currency: Literal["USD"] = "USD"
    #: Catalog price × tokens, or a client tool's own estimate.
    estimated_micro: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    #: Charge stated by the party that bills the call (e.g. OpenRouter).
    provider_reported_micro: Optional[int] = Field(default=None, ge=0, le=_MAX_INT)
    pricing_version: Optional[str] = Field(default=None, max_length=64)


class UsageEvent(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: str = Field(default_factory=new_event_id)
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    occurred_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    source: Source
    device_id: Optional[str] = None
    application_id: Optional[str] = None
    agent_id: Optional[str] = None
    account_ref: Optional[str] = None

    provider: str
    #: Who charges for the call. Defaults to ``provider``.
    billing_provider: Optional[str] = None
    model: Optional[str] = None
    requested_model: Optional[str] = None
    execution: Execution = "provider_api"
    billing_mode: BillingMode = "api"

    usage: Usage = Field(default_factory=Usage)
    measurement: Measurement = "unavailable"
    cost: Cost = Field(default_factory=Cost)

    status: Status = "completed"
    error_category: Optional[str] = None
    streamed: bool = False
    latency_ms: Optional[int] = Field(default=None, ge=0, le=86_400_000)

    @field_validator("event_id", "trace_id", "task_id", "parent_event_id", "device_id")
    @classmethod
    def _valid_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _ID_RE.match(value):
            raise ValueError("identifier must be 1-128 chars of [A-Za-z0-9._:-]")
        return value

    @field_validator(
        "application_id", "agent_id", "account_ref", "billing_provider",
        "model", "requested_model", "error_category",
    )
    @classmethod
    def _clean_optional(cls, value: Optional[str]) -> Optional[str]:
        return clean_label(value)

    @field_validator("provider")
    @classmethod
    def _clean_provider(cls, value: str) -> str:
        cleaned = clean_label(value, 64)
        if not cleaned:
            raise ValueError("provider is required")
        return cleaned.lower()

    @field_validator("occurred_at")
    @classmethod
    def _aware_utc(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    @property
    def effective_billing_provider(self) -> str:
        return (self.billing_provider or self.provider).lower()

    @property
    def day(self) -> str:
        """UTC calendar day, the rollup bucket."""
        return self.occurred_at.strftime("%Y-%m-%d")
