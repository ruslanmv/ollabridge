"""SQLite usage ledger (``~/.ollabridge/usage.db``).

Separate from ``traces.db`` on purpose: traces are a short-lived debugging
aid pruned to the newest few thousand rows, while accounting needs long
retention, idempotency keys, integer money and sync state.

**No prompt or response content is ever written.**
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ollabridge.core import paths

from .contract import MEASUREMENT_RANK, TOKEN_DIMENSIONS, UsageEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT,
    task_id TEXT,
    parent_event_id TEXT,
    occurred_at TEXT NOT NULL,
    day TEXT NOT NULL,
    source TEXT NOT NULL,
    device_id TEXT,
    application_id TEXT,
    agent_id TEXT,
    account_ref TEXT,
    provider TEXT NOT NULL,
    billing_provider TEXT NOT NULL,
    model TEXT,
    requested_model TEXT,
    execution TEXT NOT NULL,
    billing_mode TEXT NOT NULL,
    input_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    output_tokens INTEGER,
    reasoning_tokens INTEGER,
    other_units_json TEXT,
    measurement TEXT NOT NULL,
    estimated_micro INTEGER,
    reported_micro INTEGER,
    pricing_version TEXT,
    status TEXT NOT NULL,
    error_category TEXT,
    streamed INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    -- pending | synced | rejected
    sync_state TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_events (day);
CREATE INDEX IF NOT EXISTS idx_usage_sync ON usage_events (sync_state);
CREATE INDEX IF NOT EXISTS idx_usage_trace ON usage_events (trace_id);
CREATE TABLE IF NOT EXISTS usage_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_EVENT_COLUMNS = (
    "event_id", "trace_id", "task_id", "parent_event_id", "occurred_at", "day", "source",
    "device_id", "application_id", "agent_id", "account_ref", "provider", "billing_provider",
    "model", "requested_model", "execution", "billing_mode", *TOKEN_DIMENSIONS,
    "other_units_json", "measurement", "estimated_micro", "reported_micro", "pricing_version",
    "status", "error_category", "streamed", "latency_ms",
)
_FILTERABLE = ("provider", "application_id", "agent_id", "device_id", "billing_mode")


def usage_db_file() -> Path:
    return paths.data_dir() / "usage.db"


def _values(event: UsageEvent) -> Dict[str, Any]:
    usage = event.usage
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "task_id": event.task_id,
        "parent_event_id": event.parent_event_id,
        "occurred_at": event.occurred_at.isoformat(timespec="milliseconds"),
        "day": event.day,
        "source": event.source,
        "device_id": event.device_id,
        "application_id": event.application_id,
        "agent_id": event.agent_id,
        "account_ref": event.account_ref,
        "provider": event.provider,
        "billing_provider": event.effective_billing_provider,
        "model": event.model,
        "requested_model": event.requested_model,
        "execution": event.execution,
        "billing_mode": event.billing_mode,
        **{d: getattr(usage, d) for d in TOKEN_DIMENSIONS},
        "other_units_json": json.dumps(usage.other_units) if usage.other_units else None,
        "measurement": event.measurement,
        "estimated_micro": event.cost.estimated_micro,
        "reported_micro": event.cost.provider_reported_micro,
        "pricing_version": event.cost.pricing_version,
        "status": event.status,
        "error_category": event.error_category,
        "streamed": int(event.streamed),
        "latency_ms": event.latency_ms,
    }


def row_to_event(row: Dict[str, Any]) -> Dict[str, Any]:
    """A stored row as a contract-shaped dict (what the cloud ingests)."""
    return {
        "schema_version": 1,
        **{k: row[k] for k in (
            "event_id", "trace_id", "task_id", "parent_event_id", "occurred_at", "source",
            "device_id", "application_id", "agent_id", "account_ref", "provider",
            "billing_provider", "model", "requested_model", "execution", "billing_mode",
            "measurement", "status", "error_category", "latency_ms",
        )},
        "usage": {
            **{d: row[d] for d in TOKEN_DIMENSIONS},
            "other_units": json.loads(row["other_units_json"]) if row["other_units_json"] else {},
        },
        "cost": {
            "currency": "USD",
            "estimated_micro": row["estimated_micro"],
            "provider_reported_micro": row["reported_micro"],
            "pricing_version": row["pricing_version"],
        },
        "streamed": bool(row["streamed"]),
    }


class UsageStore:
    """Small, dependency-free usage ledger. Safe for multi-threaded use."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else usage_db_file()
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
        paths.tighten_permissions(self.path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── writes ──────────────────────────────────────────────────────────

    def record(self, event: UsageEvent) -> str:
        """Store one attempt idempotently.

        Returns ``accepted`` (new), ``merged`` (a better-measured sighting of a
        known attempt replaced its counts) or ``duplicate``.
        """
        values = _values(event)
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT measurement FROM usage_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if existing is None:
                columns = ", ".join(_EVENT_COLUMNS)
                marks = ", ".join("?" for _ in _EVENT_COLUMNS)
                conn.execute(
                    f"INSERT INTO usage_events ({columns}) VALUES ({marks})",
                    [values[c] for c in _EVENT_COLUMNS],
                )
                return "accepted"
            better = MEASUREMENT_RANK[event.measurement] > MEASUREMENT_RANK.get(existing["measurement"], 0)
            if not (better and event.usage.known):
                return "duplicate"
            updated = (*TOKEN_DIMENSIONS, "measurement", "estimated_micro", "pricing_version")
            assignments = ", ".join(f"{c} = ?" for c in updated)
            conn.execute(
                # Changed counts must reach the cloud again.
                f"UPDATE usage_events SET {assignments}, sync_state = 'pending' WHERE event_id = ?",
                [values[c] for c in updated] + [event.event_id],
            )
            return "merged"

    def mark_synced(self, event_ids: Iterable[str], state: str = "synced") -> None:
        ids = list(event_ids)
        if not ids:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(
                "UPDATE usage_events SET sync_state = ? WHERE event_id = ?",
                [(state, event_id) for event_id in ids],
            )

    def prune(self, keep_days: int) -> int:
        """Delete events older than ``keep_days`` days. Returns rows removed."""
        cutoff = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=keep_days)).isoformat()
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM usage_events WHERE day < ?", (cutoff,)).rowcount

    # ── reads ───────────────────────────────────────────────────────────

    def pending(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_events WHERE sync_state = 'pending' "
                "ORDER BY occurred_at LIMIT ?", (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def sync_counts(self) -> Dict[str, int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT sync_state, COUNT(*) AS n FROM usage_events GROUP BY sync_state"
            ).fetchall()
        return {r["sync_state"]: r["n"] for r in rows}

    def events(
        self, *, trace_id: Optional[str] = None, agent_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        where, params = [], []
        if trace_id:
            where.append("trace_id = ?"); params.append(trace_id)
        if agent_id:
            where.append("agent_id = ?"); params.append(agent_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM usage_events {clause} ORDER BY occurred_at DESC LIMIT ?",
                [*params, int(limit)],
            ).fetchall()
        return [dict(r) for r in rows]

    def sources(self) -> List[Dict[str, Any]]:
        """Each usage source with its event count and last-seen time."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) AS events, MAX(occurred_at) AS last_seen "
                "FROM usage_events GROUP BY source ORDER BY source"
            ).fetchall()
        return [dict(r) for r in rows]

    def rollup_rows(self, start: dt.date, end: dt.date, **filters: Optional[str]) -> List[Dict[str, Any]]:
        """Daily rollup rows (shape: ``bi_core`` module docstring)."""
        tokens = " + ".join(f"COALESCE({d}, 0)" for d in TOKEN_DIMENSIONS)
        all_unknown = " AND ".join(f"{d} IS NULL" for d in TOKEN_DIMENSIONS)
        sums = ", ".join(f"COALESCE(SUM({d}), 0) AS {d}" for d in TOKEN_DIMENSIONS)
        group = ("day, provider, billing_provider, model, application_id, agent_id, device_id, "
                 "billing_mode, measurement, status")
        where, params = ["day >= ?", "day <= ?"], [start.isoformat(), end.isoformat()]
        for column in _FILTERABLE:
            if filters.get(column):
                where.append(f"{column} = ?"); params.append(filters[column])
        sql = (
            f"SELECT {group}, COUNT(*) AS events, "
            f"SUM(CASE WHEN {all_unknown} THEN 1 ELSE 0 END) AS unknown_events, {sums}, "
            "COALESCE(SUM(COALESCE(estimated_micro, reported_micro)), 0) AS cost_micro, "
            "COALESCE(SUM(reported_micro), 0) AS reported_micro, "
            "COALESCE(SUM(CASE WHEN COALESCE(estimated_micro, reported_micro) IS NULL "
            f"THEN {tokens} ELSE 0 END), 0) AS unpriced_tokens "
            f"FROM usage_events WHERE {' AND '.join(where)} GROUP BY {group}"
        )
        with self._lock, self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ── settings (budget) ───────────────────────────────────────────────

    def get_budget_limit(self) -> Optional[int]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM usage_settings WHERE key = 'monthly_budget_micro'"
            ).fetchone()
        return int(row["value"]) if row else None

    def set_budget_limit(self, limit_micro: Optional[int]) -> None:
        with self._lock, self._connect() as conn:
            if limit_micro is None:
                conn.execute("DELETE FROM usage_settings WHERE key = 'monthly_budget_micro'")
            else:
                conn.execute(
                    "INSERT INTO usage_settings (key, value) VALUES ('monthly_budget_micro', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(int(limit_micro)),),
                )


_store: UsageStore | None = None
_store_lock = threading.Lock()


def get_usage_store() -> UsageStore:
    """Process-wide usage store singleton."""
    global _store
    with _store_lock:
        if _store is None:
            _store = UsageStore()
        return _store
