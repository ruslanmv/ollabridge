from __future__ import annotations

from datetime import datetime
from sqlmodel import SQLModel, Field


class RuntimeNode(SQLModel, table=True):
    """Persistent metadata about nodes (optional; live status is in-memory)."""

    id: int | None = Field(default=None, primary_key=True)
    node_id: str = Field(index=True, unique=True)
    connector: str
    endpoint: str | None = None
    tags: str | None = None  # csv
    models: str | None = None  # csv
    capacity: int = 1
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    healthy: bool = True


class ModelRoute(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    model_pattern: str = Field(index=True)
    selector: str  # e.g. "tag:prod" or "node:abc"
    priority: int = 100


class RequestLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    path: str
    model: str | None = None
    latency_ms: int | None = None
    ok: bool = True
    client: str | None = None
