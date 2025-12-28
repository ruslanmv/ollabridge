from __future__ import annotations

from datetime import datetime
from sqlmodel import SQLModel, Field


class RequestLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    path: str
    model: str | None = None
    latency_ms: int | None = None
    ok: bool = True
    client: str | None = None
