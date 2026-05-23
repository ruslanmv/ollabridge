"""
Background scheduler for periodic local-runtime syncs.

Runs every ``interval_s`` seconds against every configured node. Errors are
logged and swallowed — the next tick retries. First run is delayed slightly
so app startup isn't blocked.

Environment:

- ``OBRIDGE_LOCAL_SYNC_ENABLED``    (default ``true``)
- ``OBRIDGE_LOCAL_SYNC_INTERVAL_S`` (default ``60``)
- ``OBRIDGE_LOCAL_SYNC_INITIAL_S``  (default ``5``)
- ``OBRIDGE_LOCAL_AUTO_ENABLE``     (default ``3``)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Iterable

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService

logger = logging.getLogger(__name__)


def _envint(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _envbool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


NodeProvider = Callable[[], Iterable[tuple[str, LocalRuntimeClient]]]
"""Callable that returns the set of (node_id, client) pairs to sync each tick."""


class LocalCatalogScheduler:
    def __init__(
        self,
        service: LocalCatalogSyncService,
        node_provider: NodeProvider,
        *,
        interval_s: int | None = None,
        initial_delay_s: int | None = None,
        auto_enable: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.service = service
        self.node_provider = node_provider
        self.interval_s = interval_s if interval_s is not None else _envint("OBRIDGE_LOCAL_SYNC_INTERVAL_S", 60)
        self.initial_delay_s = initial_delay_s if initial_delay_s is not None else _envint("OBRIDGE_LOCAL_SYNC_INITIAL_S", 5)
        self.auto_enable = auto_enable if auto_enable is not None else _envint("OBRIDGE_LOCAL_AUTO_ENABLE", 3)
        self.enabled = enabled if enabled is not None else _envbool("OBRIDGE_LOCAL_SYNC_ENABLED", True)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not self.enabled:
            logger.info("local catalog scheduler disabled")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="local-catalog-sync")
        logger.info(
            "local catalog scheduler started (interval=%ds, initial=%ds, top=%d)",
            self.interval_s, self.initial_delay_s, self.auto_enable,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self.initial_delay_s)
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            try:
                pairs = list(self.node_provider() or [])
            except Exception:
                logger.exception("local node provider raised")
                pairs = []

            for node_id, client in pairs:
                try:
                    await self.service.sync_node(
                        node_id=node_id,
                        client=client,
                        auto_enable_top=self.auto_enable,
                    )
                except Exception:
                    logger.exception("scheduled local sync raised for node=%s", node_id)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                return
            except asyncio.TimeoutError:
                continue
