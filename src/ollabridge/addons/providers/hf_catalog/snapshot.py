"""YAML-backed snapshot of the Hugging Face catalog.

Persists a flat list of :class:`SnapshotEntry` rows under the gateway's
data directory so the catalog survives restarts. Reads are O(N) — the
catalog is at most a few hundred rows.

The snapshot is intentionally not the source of truth for capability
metadata: it's a *cache* of the last successful Hub sync, plus operator
overrides (``manually_added=True`` rows survive a sync that can no
longer see them upstream).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable

import yaml

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFInferenceModelRow,
    SnapshotEntry,
)

logger = logging.getLogger(__name__)


DEFAULT_SNAPSHOT_PATH = Path("~/.ollabridge/hf_catalog.yaml").expanduser()
MAX_MISSING_SYNCS_BEFORE_DROP = 5


class CatalogSnapshot:
    """In-memory + on-disk view of the HF catalog.

    Thread-safety: the snapshot is loaded once at startup and mutated only
    on sync (single writer). The router reads via ``list_entries()`` which
    returns a defensive copy, so concurrent reads are safe.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).expanduser() if path else DEFAULT_SNAPSHOT_PATH
        self._entries: dict[str, SnapshotEntry] = {}

    # ── I/O ────────────────────────────────────────────────

    def load(self) -> None:
        if not self.path.exists():
            logger.info("HF catalog snapshot not found at %s — starting empty", self.path)
            self._entries = {}
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("HF catalog snapshot at %s unreadable: %s", self.path, exc)
            self._entries = {}
            return

        raw_rows = data.get("models", [])
        entries: dict[str, SnapshotEntry] = {}
        for raw in raw_rows:
            try:
                entry = SnapshotEntry(**raw)
                entries[entry.router_model_id] = entry
            except Exception as exc:
                logger.warning("Skipping invalid snapshot row: %s", exc)
        self._entries = entries
        logger.info("Loaded %d HF catalog rows from %s", len(self._entries), self.path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Sort by score desc then router_model_id asc for stable diffs.
        rows = sorted(
            (e.model_dump(mode="json") for e in self._entries.values()),
            key=lambda r: (-(r.get("score") or 0.0), r.get("router_model_id") or ""),
        )
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "count": len(rows),
            "models": rows,
        }
        # Atomic write — never leave a half-flushed file if interrupted.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(self.path.parent),
            prefix=".hf_catalog.", suffix=".tmp", delete=False,
        )
        try:
            yaml.safe_dump(payload, tmp, sort_keys=False, allow_unicode=True)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp.name, self.path)
        logger.info("Wrote %d HF catalog rows to %s", len(rows), self.path)

    # ── Sync helpers ───────────────────────────────────────

    def upsert(
        self,
        scored: list[tuple[HFInferenceModelRow, float]],
        *,
        now: dt.datetime | None = None,
    ) -> tuple[int, int]:
        """Insert/update entries from a scored batch.

        Returns ``(upserted, marked_stale)``. Rows that were not seen in
        ``scored`` get their ``missing_sync_count`` incremented; rows that
        exceed :data:`MAX_MISSING_SYNCS_BEFORE_DROP` are removed unless
        ``manually_added`` is set."""
        now = now or dt.datetime.now(dt.timezone.utc)
        seen_keys: set[str] = set()
        upserted = 0

        for rank, (row, score) in enumerate(scored, start=1):
            key = row.router_model_id
            seen_keys.add(key)
            existing = self._entries.get(key)
            entry = SnapshotEntry(
                router_model_id=key,
                model_id=row.model_id,
                hf_provider=row.hf_provider,
                task=row.task,
                rank=rank,
                score=round(score, 4),
                input_price_per_1m=row.input_price_per_1m,
                output_price_per_1m=row.output_price_per_1m,
                context_window=row.context_window,
                latency_s=row.latency_s,
                throughput_tps=row.throughput_tps,
                supports_tools=row.supports_tools,
                supports_structured_output=row.supports_structured_output,
                trending_score=row.trending_score,
                labels=row.labels,
                manually_added=existing.manually_added if existing else False,
                last_seen_at=now,
                missing_sync_count=0,
            )
            self._entries[key] = entry
            upserted += 1

        # Age out entries we didn't see this run.
        dropped = 0
        for key in list(self._entries.keys()):
            if key in seen_keys:
                continue
            entry = self._entries[key]
            entry.missing_sync_count += 1
            if entry.missing_sync_count > MAX_MISSING_SYNCS_BEFORE_DROP and not entry.manually_added:
                del self._entries[key]
                dropped += 1

        return upserted, dropped

    # ── Read API ───────────────────────────────────────────

    def list_entries(self) -> list[SnapshotEntry]:
        return list(self._entries.values())

    def find(self, router_model_id: str) -> SnapshotEntry | None:
        return self._entries.get(router_model_id)

    def filter(
        self,
        *,
        task: str | None = None,
        supports_tools: bool | None = None,
        supports_structured_output: bool | None = None,
        free_credit_only: bool | None = None,
        max_price_per_1m: float | None = None,
    ) -> list[SnapshotEntry]:
        """Capability-based filter. Returns rows in current rank order."""
        out = sorted(self._entries.values(), key=lambda e: (e.rank or 1e9, -e.score))
        if task is not None:
            out = [e for e in out if str(e.task) == task or e.task.value == task]
        if supports_tools is not None:
            out = [e for e in out if e.supports_tools == supports_tools]
        if supports_structured_output is not None:
            out = [e for e in out if e.supports_structured_output == supports_structured_output]
        if free_credit_only:
            out = [e for e in out if e.cost_marker in ("free", "cheap", "unknown")]
        if max_price_per_1m is not None:
            out = [
                e for e in out
                if (e.input_price_per_1m or 0.0) <= max_price_per_1m
                and (e.output_price_per_1m or 0.0) <= max_price_per_1m
            ]
        return out

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    # Convenience for tests / serialisation.
    def to_dicts(self) -> Iterable[dict]:
        return (e.model_dump(mode="json") for e in self._entries.values())
