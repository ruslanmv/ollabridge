"""
YAML-backed repository for the local model fleet.

State lives under ``~/.ollabridge/local_models.yaml`` (override via the
``OBRIDGE_LOCAL_CATALOG_PATH`` env var). The on-disk schema is multi-node:

::

    nodes:
      local-node-01:
        last_sync: { ... }
        models:
          - { router_model_id: "local-node-01:qwen2.5:14b", ... }
          - ...

so one OllaBridge instance can manage several runtimes (a workstation +
a homelab box, for example) without colliding on file paths.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

import yaml

from ollabridge.addons.local_catalog.schemas import (
    LocalCatalogStats,
    LocalModel,
    LocalSetupStatus,
    LocalSyncResult,
)

logger = logging.getLogger(__name__)


def _default_path() -> Path:
    override = os.environ.get("OBRIDGE_LOCAL_CATALOG_PATH")
    if override:
        return Path(override)
    return Path.home() / ".ollabridge" / "local_models.yaml"


class LocalCatalogRepository:
    """Per-node, in-memory cache backed by a single YAML file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _default_path()
        self._lock = asyncio.Lock()
        # ``self._nodes[node_id][router_model_id] = LocalModel``
        self._nodes: dict[str, dict[str, LocalModel]] = {}
        self._last_sync: dict[str, LocalSyncResult] = {}

    # ── Load / save ─────────────────────────────────────────

    def load(self) -> None:
        if not self.path.exists():
            logger.info("local catalog file not found at %s — starting empty", self.path)
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error("failed to load local catalog from %s: %s", self.path, exc)
            return

        nodes = data.get("nodes") or {}
        for node_id, payload in nodes.items():
            models: dict[str, LocalModel] = {}
            for raw in (payload or {}).get("models", []) or []:
                try:
                    m = LocalModel.model_validate(raw)
                    models[m.router_model_id] = m
                except Exception as exc:
                    logger.warning("skipping invalid local-catalog row: %s", exc)
            self._nodes[node_id] = models

            last_sync_raw = (payload or {}).get("last_sync")
            if last_sync_raw:
                try:
                    self._last_sync[node_id] = LocalSyncResult.model_validate(last_sync_raw)
                except Exception as exc:
                    logger.warning("discarding malformed last_sync for %s: %s", node_id, exc)

        logger.info(
            "loaded local catalog from %s: %d nodes, %d models",
            self.path, len(self._nodes), sum(len(v) for v in self._nodes.values()),
        )

    def _save_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodes": {
                node_id: {
                    "last_sync": (
                        self._last_sync[node_id].model_dump(mode="json")
                        if node_id in self._last_sync else None
                    ),
                    "models": [m.model_dump(mode="json") for m in models.values()],
                }
                for node_id, models in self._nodes.items()
            }
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        tmp.replace(self.path)

    async def save(self) -> None:
        async with self._lock:
            self._save_unlocked()

    # ── Read API ────────────────────────────────────────────

    def list_nodes(self) -> list[str]:
        return list(self._nodes.keys())

    def list_models(self, node_id: Optional[str] = None) -> list[LocalModel]:
        if node_id is None:
            return [m for models in self._nodes.values() for m in models.values()]
        return list(self._nodes.get(node_id, {}).values())

    def get(self, router_model_id: str) -> Optional[LocalModel]:
        for models in self._nodes.values():
            m = models.get(router_model_id)
            if m:
                return m
        return None

    def list_enabled(self, node_id: Optional[str] = None) -> list[LocalModel]:
        return [m for m in self.list_models(node_id) if m.enabled]

    def list_top(self, node_id: Optional[str] = None) -> list[LocalModel]:
        rows = [m for m in self.list_models(node_id) if m.is_top_recommended]
        rows.sort(key=lambda m: (m.rank or 9999, -m.score))
        return rows

    def stats(self, node_id: Optional[str] = None) -> LocalCatalogStats:
        s = LocalCatalogStats(node_id=node_id)
        for m in self.list_models(node_id):
            s.total += 1
            if m.enabled:
                s.enabled += 1
            if m.is_top_recommended:
                s.top_recommended += 1
            if m.pinned:
                s.pinned += 1
            if m.manually_added:
                s.manual += 1
            if m.setup_status == LocalSetupStatus.VERIFIED:
                s.verified += 1
            elif m.setup_status == LocalSetupStatus.BROKEN:
                s.broken += 1
            elif m.setup_status == LocalSetupStatus.REMOVED:
                s.removed += 1
            if m.disk_size_bytes:
                s.total_disk_bytes += m.disk_size_bytes

        if node_id and node_id in self._last_sync:
            ls = self._last_sync[node_id]
            s.last_sync_at = ls.finished_at
            s.last_sync_ok = ls.ok
        return s

    def last_sync(self, node_id: str) -> Optional[LocalSyncResult]:
        return self._last_sync.get(node_id)

    # ── Write API ───────────────────────────────────────────

    async def upsert_many(
        self,
        node_id: str,
        models: Iterable[LocalModel],
        *,
        now: Optional[dt.datetime] = None,
    ) -> tuple[int, int]:
        """
        Insert new rows, refresh existing ones (preserving admin state).
        Returns ``(new_count, updated_count)``.
        """
        now = now or dt.datetime.now(dt.timezone.utc)
        new = 0
        updated = 0
        async with self._lock:
            bucket = self._nodes.setdefault(node_id, {})
            for incoming in models:
                existing = bucket.get(incoming.router_model_id)
                if existing is None:
                    incoming.last_seen_at = now
                    incoming.missing_sync_count = 0
                    bucket[incoming.router_model_id] = incoming
                    new += 1
                    continue

                # Refresh discovery fields, preserve admin state.
                existing.runtime = incoming.runtime
                existing.display_name = incoming.display_name or existing.display_name
                existing.family = incoming.family or existing.family
                existing.parameter_size = incoming.parameter_size or existing.parameter_size
                existing.parameter_count = incoming.parameter_count or existing.parameter_count
                existing.quantization = incoming.quantization or existing.quantization
                existing.context_window = incoming.context_window or existing.context_window
                existing.disk_size_bytes = incoming.disk_size_bytes or existing.disk_size_bytes
                existing.capabilities = incoming.capabilities
                existing.modified_at = incoming.modified_at or existing.modified_at
                existing.score = incoming.score
                existing.rank = incoming.rank
                existing.is_top_recommended = incoming.is_top_recommended
                existing.last_seen_at = now
                existing.missing_sync_count = 0
                existing.raw_metadata = incoming.raw_metadata or existing.raw_metadata
                if existing.setup_status == LocalSetupStatus.REMOVED:
                    # Re-installed externally — restore to AUTO so the next probe
                    # can promote it back to VERIFIED.
                    existing.setup_status = LocalSetupStatus.AUTO
                updated += 1
        return new, updated

    async def mark_removed(
        self,
        node_id: str,
        present_router_ids: set[str],
        *,
        threshold: int = 2,
    ) -> int:
        """
        Bump ``missing_sync_count`` on rows absent from the latest listing
        and flag them ``REMOVED`` once the threshold is crossed.

        Manually-added rows are skipped (they may represent models the user
        intends to pull later).
        """
        transitioned = 0
        async with self._lock:
            bucket = self._nodes.get(node_id) or {}
            for m in bucket.values():
                if m.manually_added:
                    continue
                if m.router_model_id in present_router_ids:
                    continue
                m.missing_sync_count += 1
                if (
                    m.missing_sync_count >= threshold
                    and m.setup_status != LocalSetupStatus.REMOVED
                ):
                    m.setup_status = LocalSetupStatus.REMOVED
                    m.is_top_recommended = False
                    transitioned += 1
        return transitioned

    async def apply_top_recommendation(
        self,
        node_id: str,
        top_router_ids: list[str],
        *,
        auto_enable: bool = True,
    ) -> tuple[int, int]:
        """Mark ``top_router_ids`` top-recommended; optionally auto-enable."""
        target = set(top_router_ids)
        rank_map = {rid: idx + 1 for idx, rid in enumerate(top_router_ids)}
        promoted = 0
        demoted = 0
        async with self._lock:
            bucket = self._nodes.get(node_id) or {}
            for m in bucket.values():
                was_top = m.is_top_recommended
                should_top = m.router_model_id in target
                if should_top and not was_top:
                    promoted += 1
                elif was_top and not should_top:
                    demoted += 1
                m.is_top_recommended = should_top
                m.rank = rank_map.get(m.router_model_id, 0)
                if should_top and auto_enable and not m.enabled:
                    m.enabled = True
        return promoted, demoted

    async def set_enabled(self, router_model_id: str, enabled: bool) -> bool:
        async with self._lock:
            for bucket in self._nodes.values():
                m = bucket.get(router_model_id)
                if not m:
                    continue
                m.enabled = enabled
                if not enabled and m.setup_status == LocalSetupStatus.AUTO:
                    m.setup_status = LocalSetupStatus.DISABLED
                elif enabled and m.setup_status == LocalSetupStatus.DISABLED:
                    m.setup_status = LocalSetupStatus.AUTO
                return True
        return False

    async def set_pinned(self, router_model_id: str, pinned: bool) -> bool:
        async with self._lock:
            for bucket in self._nodes.values():
                m = bucket.get(router_model_id)
                if not m:
                    continue
                m.pinned = pinned
                return True
        return False

    async def upsert_manual(self, model: LocalModel) -> LocalModel:
        model.manually_added = True
        if model.setup_status == LocalSetupStatus.AUTO and not model.last_seen_at:
            model.setup_status = LocalSetupStatus.NOT_INSTALLED
        async with self._lock:
            self._nodes.setdefault(model.node_id, {})[model.router_model_id] = model
        return model

    async def delete(self, router_model_id: str) -> bool:
        async with self._lock:
            for bucket in self._nodes.values():
                if router_model_id in bucket:
                    del bucket[router_model_id]
                    return True
        return False

    async def record_check(
        self,
        router_model_id: str,
        *,
        ok: bool,
        error: Optional[str],
        latency_ms: Optional[float],
    ) -> None:
        async with self._lock:
            for bucket in self._nodes.values():
                m = bucket.get(router_model_id)
                if not m:
                    continue
                m.last_checked_at = dt.datetime.now(dt.timezone.utc)
                m.last_error = None if ok else error
                m.latency_observed_ms = latency_ms
                if latency_ms is not None:
                    # EWMA against any existing avg.
                    if m.avg_latency_ms is None:
                        m.avg_latency_ms = latency_ms
                    else:
                        m.avg_latency_ms = m.avg_latency_ms * 0.8 + latency_ms * 0.2
                if ok:
                    m.consecutive_check_failures = 0
                    if m.setup_status in (LocalSetupStatus.AUTO, LocalSetupStatus.BROKEN):
                        m.setup_status = LocalSetupStatus.VERIFIED
                else:
                    m.consecutive_check_failures += 1
                    if m.setup_status not in (LocalSetupStatus.REMOVED, LocalSetupStatus.NOT_INSTALLED):
                        m.setup_status = LocalSetupStatus.BROKEN
                return

    async def set_last_sync(self, node_id: str, result: LocalSyncResult) -> None:
        async with self._lock:
            self._last_sync[node_id] = result

    async def set_setup_status(self, router_model_id: str, status: LocalSetupStatus) -> bool:
        async with self._lock:
            for bucket in self._nodes.values():
                m = bucket.get(router_model_id)
                if not m:
                    continue
                m.setup_status = status
                return True
        return False
