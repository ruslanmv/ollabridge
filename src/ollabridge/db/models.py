from __future__ import annotations

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    SQLModel >= 0.0.48 stores ``datetime`` columns as ``UTCDateTime`` and
    rejects naive values at bind time, so every timestamp written to the
    database must carry tzinfo. ``datetime.utcnow`` is naive (and deprecated
    since Python 3.12); this is the one default factory every model uses.
    """
    return datetime.now(timezone.utc)


class RuntimeNode(SQLModel, table=True):
    """Persistent metadata about nodes (optional; live status is in-memory)."""

    id: int | None = Field(default=None, primary_key=True)
    node_id: str = Field(index=True, unique=True)
    connector: str
    endpoint: str | None = None
    tags: str | None = None  # csv
    models: str | None = None  # csv
    capacity: int = 1
    last_seen: datetime = Field(default_factory=utcnow)
    healthy: bool = True


class ModelRoute(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    model_pattern: str = Field(index=True)
    selector: str  # e.g. "tag:prod" or "node:abc"
    priority: int = 100


class RequestLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow)
    path: str
    model: str | None = None
    latency_ms: int | None = None
    ok: bool = True
    client: str | None = None
