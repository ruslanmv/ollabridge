"""Sync orchestrator for the gateway's Hugging Face catalog.

One public entry point — :meth:`HFCatalogSyncService.run` — does:

    1. Fetch top inference-capable models from the Hub.
    2. Normalize the response into per-(model, provider) rows.
    3. Score the rows with the active profile.
    4. Upsert into the on-disk snapshot.
    5. Rewrite the managed alias block in ``model_aliases.yaml``.
    6. Trigger the in-process :class:`ProviderRegistry` to reload aliases
       (so new routes are visible without an app restart).

The service is safe to call concurrently — it serialises through an
``asyncio.Lock`` so a chatty user clicking "Refresh" five times only
triggers one upstream fetch.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path
from typing import Optional

from ollabridge.addons.providers.hf_catalog.alias_writer import (
    build_managed_aliases,
    write_managed_aliases,
)
from ollabridge.addons.providers.hf_catalog.client import (
    CHAT_PIPELINES,
    HuggingFaceCatalogClient,
)
from ollabridge.addons.providers.hf_catalog.parser import normalize
from ollabridge.addons.providers.hf_catalog.schemas import (
    ScoringProfile,
    SyncResult,
)
from ollabridge.addons.providers.hf_catalog.scoring import score_rows
from ollabridge.addons.providers.hf_catalog.snapshot import CatalogSnapshot

logger = logging.getLogger(__name__)


class HFCatalogSyncService:
    """Coordinates catalog refreshes for the gateway."""

    def __init__(
        self,
        snapshot: CatalogSnapshot,
        client: HuggingFaceCatalogClient,
        aliases_path: Path,
        registry_reload_hook: Optional[callable] = None,
    ) -> None:
        self.snapshot = snapshot
        self.client = client
        self.aliases_path = aliases_path
        self._registry_reload_hook = registry_reload_hook
        self._lock = asyncio.Lock()
        self._last_result: SyncResult | None = None

    @property
    def last_result(self) -> SyncResult | None:
        return self._last_result

    async def run(
        self,
        *,
        limit: int = 100,
        profile: ScoringProfile = ScoringProfile.FREE_LAB,
        pipelines: tuple[str, ...] = CHAT_PIPELINES,
    ) -> SyncResult:
        """Run a full sync. Serialised — concurrent calls share the result."""
        async with self._lock:
            started = dt.datetime.now(dt.timezone.utc)
            try:
                raw = await self.client.fetch_inference_models(
                    limit=limit, pipelines=pipelines,
                )
                rows = normalize(raw)
                scored = score_rows(rows, profile=profile)
                upserted, marked_stale = self.snapshot.upsert(scored)
                self.snapshot.save()

                managed = build_managed_aliases(self.snapshot.list_entries())
                aliases_written = write_managed_aliases(self.aliases_path, managed)

                if self._registry_reload_hook is not None:
                    try:
                        result = self._registry_reload_hook()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("alias reload hook failed: %s", exc)

                finished = dt.datetime.now(dt.timezone.utc)
                self._last_result = SyncResult(
                    started_at=started,
                    finished_at=finished,
                    fetched=len(raw),
                    upserted=upserted,
                    marked_stale=marked_stale,
                    aliases_written=aliases_written,
                    profile=profile,
                )
                logger.info(
                    "HF catalog sync OK: fetched=%d upserted=%d stale=%d aliases=%d in %.2fs",
                    len(raw), upserted, marked_stale, aliases_written,
                    (finished - started).total_seconds(),
                )
                return self._last_result

            except Exception as exc:  # noqa: BLE001
                finished = dt.datetime.now(dt.timezone.utc)
                self._last_result = SyncResult(
                    started_at=started,
                    finished_at=finished,
                    error=str(exc),
                    profile=profile,
                )
                logger.exception("HF catalog sync failed: %s", exc)
                return self._last_result
