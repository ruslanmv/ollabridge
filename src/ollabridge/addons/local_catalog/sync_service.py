"""
Sync orchestrator: discover → enrich → score → upsert → top-N → aliases.

Per-node. Designed to be cheap enough to run on a timer (defaults to every
60 s while the runtime is reachable, configurable via env). Concurrent
invocations against the same node coalesce via a per-node lock so a chatty
client can't trigger overlapping syncs.

Managed aliases live in ``~/.ollabridge/local_aliases.yaml`` separately
from any operator-defined alias file. The cloud heartbeat reads from this
file to share the recommended set with cloud Admin.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.parser import normalize
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.schemas import (
    LocalModel,
    LocalScoringProfile,
    LocalSetupStatus,
    LocalSyncResult,
)
from ollabridge.addons.local_catalog.scoring import pick_top_n, score_models

logger = logging.getLogger(__name__)


def _default_alias_path() -> Path:
    override = os.environ.get("OBRIDGE_LOCAL_ALIAS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".ollabridge" / "local_aliases.yaml"


class LocalCatalogSyncService:
    """Orchestrate one runtime-list → catalog refresh cycle for a node."""

    def __init__(
        self,
        repository: LocalCatalogRepository,
        *,
        scoring_profile: LocalScoringProfile = LocalScoringProfile.DEFAULT,
        alias_path: str | Path | None = None,
        enrich_with_show: bool = True,
        max_show_calls: int = 32,
    ) -> None:
        self.repository = repository
        self.scoring_profile = scoring_profile
        self.alias_path = Path(alias_path) if alias_path else _default_alias_path()
        self.enrich_with_show = enrich_with_show
        self.max_show_calls = max_show_calls
        self._locks: dict[str, asyncio.Lock] = {}

    # ── Public API ──────────────────────────────────────────

    async def sync_node(
        self,
        *,
        node_id: str,
        client: LocalRuntimeClient,
        auto_enable_top: int = 3,
    ) -> LocalSyncResult:
        lock = self._locks.setdefault(node_id, asyncio.Lock())
        if lock.locked():
            now = dt.datetime.now(dt.timezone.utc)
            return LocalSyncResult(
                node_id=node_id, started_at=now, finished_at=now,
                error="sync_already_running",
            )

        async with lock:
            started = dt.datetime.now(dt.timezone.utc)
            result = LocalSyncResult(node_id=node_id, started_at=started, finished_at=started)

            try:
                tags = await client.list_tags()
                result.fetched = len(tags)

                show_details: dict[str, dict] = {}
                if self.enrich_with_show and tags:
                    show_details = await self._enrich(client, tags)

                rows = normalize(node_id, tags, show_details=show_details)
                models = [_row_to_persisted(r) for r in rows]

                # Initial score so newly-upserted rows have a baseline; the
                # repository preserves admin state (pinned, enabled, etc.).
                scored = score_models(models, profile=self.scoring_profile)
                for m, s in scored:
                    m.score = round(s, 6)

                new, updated = await self.repository.upsert_many(node_id, [m for m, _ in scored])
                result.upserted = new + updated

                present_ids = {m.router_model_id for m, _ in scored}
                result.marked_removed = await self.repository.mark_removed(node_id, present_ids)

                # Re-score against persisted rows (preserves pinned/health), then
                # promote the top-N for this node.
                live = self.repository.list_models(node_id=node_id)
                scored_live = score_models(live, profile=self.scoring_profile)
                top = pick_top_n(
                    scored_live,
                    n=auto_enable_top,
                    require_chat=True,
                    dedupe_family=False,
                )
                promoted, demoted = await self.repository.apply_top_recommendation(
                    node_id, [m.router_model_id for m, _ in top], auto_enable=True,
                )
                result.promoted_to_top = promoted
                result.demoted_from_top = demoted

                result.aliases_written = self._write_managed_aliases()

            except Exception as exc:
                logger.exception("local catalog sync failed for node=%s", node_id)
                result.error = f"{exc.__class__.__name__}: {exc}"

            result.finished_at = dt.datetime.now(dt.timezone.utc)
            await self.repository.set_last_sync(node_id, result)
            await self.repository.save()

            logger.info(
                "local catalog sync node=%s fetched=%d upserted=%d promoted=%d demoted=%d removed=%d (%.1fs)%s",
                node_id, result.fetched, result.upserted, result.promoted_to_top,
                result.demoted_from_top, result.marked_removed, result.duration_s,
                f" error={result.error}" if result.error else "",
            )
            return result

    # ── Manual add ──────────────────────────────────────────

    async def add_manual_model(
        self,
        *,
        node_id: str,
        external_model_id: str,
        runtime: str = "ollama",
        display_name: Optional[str] = None,
        enabled: bool = True,
        pinned: bool = False,
        supports_tools: bool = False,
        supports_vision: bool = False,
        supports_embeddings: bool = False,
    ) -> LocalModel:
        from ollabridge.addons.local_catalog.schemas import (
            LocalRuntime, ModelCapabilities,
        )
        try:
            rt = LocalRuntime(runtime)
        except ValueError:
            rt = LocalRuntime.OLLAMA

        model = LocalModel(
            node_id=node_id,
            runtime=rt,
            external_model_id=external_model_id.strip(),
            router_model_id=f"{node_id}:{external_model_id.strip()}",
            display_name=display_name,
            enabled=enabled,
            pinned=pinned,
            capabilities=ModelCapabilities(
                supports_chat=not supports_embeddings,
                supports_embeddings=supports_embeddings,
                supports_tools=supports_tools,
                supports_vision=supports_vision,
            ),
            manually_added=True,
            setup_status=LocalSetupStatus.NOT_INSTALLED,
        )
        await self.repository.upsert_manual(model)
        await self.repository.save()
        return model

    # ── Internals ───────────────────────────────────────────

    async def _enrich(
        self,
        client: LocalRuntimeClient,
        tags: list[dict],
    ) -> dict[str, dict]:
        """Call ``/api/show`` for up to ``max_show_calls`` tags in parallel."""
        names: list[str] = []
        for t in tags[: self.max_show_calls]:
            n = t.get("name") or t.get("model")
            if isinstance(n, str):
                names.append(n)

        if not names:
            return {}

        results = await asyncio.gather(
            *(client.show(n) for n in names), return_exceptions=True
        )
        out: dict[str, dict] = {}
        for name, res in zip(names, results):
            if isinstance(res, dict) and res:
                out[name] = res
        return out

    def _write_managed_aliases(self) -> int:
        """
        Produce ``local-best`` / ``local-fast`` / ``local-private`` aliases
        across all nodes.

        - ``local-best``    — top scored model per node, then globally.
        - ``local-fast``    — top latency_observed_ms ascending, top 5.
        - ``local-private`` — same as best (all local nodes are private),
                              kept as a distinct name for routing-profile UX.
        """
        all_models = self.repository.list_models()
        if not all_models:
            return 0

        scored = score_models(all_models, profile=self.scoring_profile)

        best = pick_top_n(scored, n=5, require_chat=True, dedupe_family=False)

        fast_sorted = sorted(
            ((m, s) for m, s in scored if m.latency_observed_ms is not None),
            key=lambda t: (t[0].latency_observed_ms, -t[1]),
        )
        # Fall back to score order when no probes have been run yet.
        fast = pick_top_n(fast_sorted or scored, n=5, require_chat=True)

        # Private == best, but bounded to verified models only.
        private_pool = [(m, s) for m, s in scored if m.setup_status == LocalSetupStatus.VERIFIED]
        private = pick_top_n(private_pool or scored, n=5, require_chat=True)

        def _entries(rows) -> list[dict]:
            return [
                {"provider": m.node_id, "model": m.external_model_id}
                for m, _ in rows
            ]

        payload = {
            "managed_by": "local_catalog",
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "aliases": {
                "local-best": _entries(best),
                "local-fast": _entries(fast),
                "local-private": _entries(private),
            },
        }

        self.alias_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.alias_path.with_suffix(self.alias_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
        tmp.replace(self.alias_path)

        return sum(1 for entries in payload["aliases"].values() if entries)


# ── Helpers ─────────────────────────────────────────────────


def _row_to_persisted(row) -> LocalModel:
    return LocalModel(
        node_id=row.node_id,
        runtime=row.runtime,
        external_model_id=row.external_model_id,
        router_model_id=row.router_model_id,
        display_name=row.display_name,
        family=row.family,
        parameter_size=row.parameter_size,
        parameter_count=row.parameter_count,
        quantization=row.quantization,
        context_window=row.context_window,
        disk_size_bytes=row.disk_size_bytes,
        capabilities=row.capabilities,
        modified_at=row.modified_at,
        raw_metadata=row.raw,
    )
