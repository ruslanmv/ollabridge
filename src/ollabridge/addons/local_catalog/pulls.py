"""
Background ``ollama pull`` manager.

The admin "Pull Model" button starts an asyncio task here, which streams
progress from the runtime's ``POST /api/pull`` and updates an in-memory
``PullProgress`` record per (node, model). The HTTP layer reads that record
to render progress bars; nothing is persisted to YAML — once the pull
finishes the next sync will pick up the new model row.

Concurrent pulls of the same model are coalesced. A small concurrency cap
prevents accidental denial-of-service of the local runtime.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Optional

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.schemas import LocalSetupStatus, PullProgress

logger = logging.getLogger(__name__)


class LocalPullManager:
    def __init__(
        self,
        repository: LocalCatalogRepository,
        *,
        max_concurrent: int = 1,
    ) -> None:
        self.repository = repository
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._progress: dict[tuple[str, str], PullProgress] = {}
        self._tasks: dict[tuple[str, str], asyncio.Task] = {}

    # ── API used by routes ──────────────────────────────────

    async def start(
        self,
        *,
        node_id: str,
        external_model_id: str,
        client: LocalRuntimeClient,
    ) -> PullProgress:
        key = (node_id, external_model_id)
        existing = self._progress.get(key)
        if existing and existing.status in ("queued", "running"):
            return existing

        progress = PullProgress(node_id=node_id, external_model_id=external_model_id)
        self._progress[key] = progress
        task = asyncio.create_task(self._run(progress, client), name=f"pull:{node_id}:{external_model_id}")
        self._tasks[key] = task
        return progress

    def get(self, node_id: str, external_model_id: str) -> Optional[PullProgress]:
        return self._progress.get((node_id, external_model_id))

    def list_active(self) -> list[PullProgress]:
        return [p for p in self._progress.values() if p.status in ("queued", "running")]

    async def cancel(self, node_id: str, external_model_id: str) -> bool:
        key = (node_id, external_model_id)
        task = self._tasks.get(key)
        if not task or task.done():
            return False
        task.cancel()
        progress = self._progress.get(key)
        if progress:
            progress.status = "error"
            progress.error = "cancelled"
            progress.last_update = dt.datetime.now(dt.timezone.utc)
        return True

    # ── Worker ──────────────────────────────────────────────

    async def _run(self, progress: PullProgress, client: LocalRuntimeClient) -> None:
        # Reflect the pull state in the catalog row (if it exists).
        router_id = f"{progress.node_id}:{progress.external_model_id}"
        await self.repository.set_setup_status(router_id, LocalSetupStatus.PULLING)

        async with self._semaphore:
            progress.status = "running"
            progress.last_update = dt.datetime.now(dt.timezone.utc)

            try:
                async for event in client.pull_stream(progress.external_model_id):
                    status = (event.get("status") or "").lower()
                    progress.last_update = dt.datetime.now(dt.timezone.utc)

                    if status == "error":
                        progress.status = "error"
                        progress.error = str(event.get("error") or "unknown error")
                        break

                    if event.get("total"):
                        progress.total_bytes = int(event["total"])
                    if event.get("completed"):
                        progress.completed_bytes = int(event["completed"])

                    if status in ("success", "completed"):
                        progress.status = "completed"
                        break
            except asyncio.CancelledError:
                progress.status = "error"
                progress.error = "cancelled"
                raise
            except Exception as exc:
                logger.exception("local pull failed for %s", router_id)
                progress.status = "error"
                progress.error = f"{exc.__class__.__name__}: {exc}"

        # Resolve the catalog status based on the outcome.
        if progress.status == "completed":
            await self.repository.set_setup_status(router_id, LocalSetupStatus.AUTO)
        else:
            await self.repository.set_setup_status(router_id, LocalSetupStatus.NOT_INSTALLED)
        await self.repository.save()
