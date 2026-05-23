"""
Per-model health checker.

A 1-token chat probe against the local runtime. Bounded concurrency keeps a
"Test all" button from saturating the GPU; per-model cooldown stops
admin button-mashing from running back-to-back probes.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Optional

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.schemas import LocalModel

logger = logging.getLogger(__name__)


class LocalModelHealthChecker:
    def __init__(
        self,
        repository: LocalCatalogRepository,
        *,
        min_interval_s: float = 30.0,
        concurrency: int = 2,
    ) -> None:
        self.repository = repository
        self.min_interval_s = min_interval_s
        self._semaphore = asyncio.Semaphore(concurrency)

    async def check_one(
        self,
        router_model_id: str,
        client: LocalRuntimeClient,
        *,
        force: bool = False,
    ) -> bool:
        model = self.repository.get(router_model_id)
        if not model:
            return False
        if not force and not _should_check(model, self.min_interval_s):
            logger.debug("skipping local probe (cooldown): %s", router_model_id)
            return model.last_error is None and model.last_checked_at is not None

        async with self._semaphore:
            ok, error, latency = await client.probe_chat(model.external_model_id)

        await self.repository.record_check(
            router_model_id, ok=ok, error=error, latency_ms=latency,
        )
        await self.repository.save()
        return ok

    async def check_enabled(
        self,
        node_id: str,
        client: LocalRuntimeClient,
    ) -> dict[str, bool]:
        enabled = [m for m in self.repository.list_enabled(node_id) if m.is_chat_capable]
        if not enabled:
            return {}

        async def _one(m: LocalModel) -> tuple[str, bool]:
            ok = await self.check_one(m.router_model_id, client, force=True)
            return m.router_model_id, ok

        pairs = await asyncio.gather(*[_one(m) for m in enabled])
        return dict(pairs)


def _should_check(model: LocalModel, min_interval_s: float) -> bool:
    last = model.last_checked_at
    if last is None:
        return True
    age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds()
    return age >= min_interval_s
