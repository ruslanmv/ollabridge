"""SQLite-backed trace store (``~/.ollabridge/traces.db``).

Stores routing/transparency metadata for every request:
which model was requested vs used, which backend served it, whether the
cloud relay or a paid provider was involved, token counts, latency, and
cost estimates. **No prompt or response content is ever written.**
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ollabridge.core import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    request_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    path TEXT,
    user_id TEXT,
    project_id TEXT,
    client_type TEXT,
    requested_model TEXT,
    resolved_model TEXT,
    provider TEXT,
    device TEXT,
    route_policy TEXT,
    cloud_relay INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    prompt_logging INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms INTEGER,
    estimated_cost_usd REAL,
    ok INTEGER NOT NULL DEFAULT 1,
    error_category TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces (ts DESC);
"""


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


class TraceRecord(BaseModel):
    request_id: str = Field(default_factory=new_request_id)
    ts: str = Field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="milliseconds"
        )
    )
    path: Optional[str] = None
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    client_type: Optional[str] = None
    requested_model: Optional[str] = None
    resolved_model: Optional[str] = None
    provider: Optional[str] = None
    device: Optional[str] = None
    route_policy: Optional[str] = None
    cloud_relay: bool = False
    fallback_used: bool = False
    prompt_logging: bool = False
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    ok: bool = True
    error_category: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), indent=2)


_COLUMNS = list(TraceRecord.model_fields.keys())


class TraceStore:
    """Small, dependency-free trace store. Safe for multi-threaded use."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else paths.traces_db_file()
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)
        paths.tighten_permissions(self.path)

    def record(self, trace: TraceRecord) -> None:
        values = trace.model_dump()
        placeholders = ", ".join("?" for _ in _COLUMNS)
        cols = ", ".join(_COLUMNS)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO traces ({cols}) VALUES ({placeholders})",
                [values[c] for c in _COLUMNS],
            )

    def get(self, request_id: str) -> TraceRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM traces WHERE request_id = ?", (request_id,)
            ).fetchone()
        return TraceRecord.model_validate(dict(row)) if row else None

    def list(self, limit: int = 50) -> list[TraceRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM traces ORDER BY ts DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [TraceRecord.model_validate(dict(r)) for r in rows]

    def prune(self, keep: int = 10000) -> int:
        """Delete all but the newest *keep* traces. Returns rows removed."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM traces WHERE request_id NOT IN "
                "(SELECT request_id FROM traces ORDER BY ts DESC LIMIT ?)",
                (int(keep),),
            )
            return cur.rowcount


_store: TraceStore | None = None
_store_lock = threading.Lock()


def get_trace_store() -> TraceStore:
    """Process-wide trace store singleton."""
    global _store
    with _store_lock:
        if _store is None:
            _store = TraceStore()
        return _store
