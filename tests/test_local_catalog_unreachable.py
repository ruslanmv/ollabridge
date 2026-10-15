"""An unreachable runtime must not look like an empty one.

``list_tags`` used to swallow connection errors and return ``[]``. The sync
then "learned" that the runtime had zero models: every row's missing count
went up, and after the second tick (two minutes of downtime) the repository
marked every catalog model REMOVED. The scheduler also kept probing at the
full rate. Pinned here: downtime leaves the catalog untouched, is reported as
``runtime_unreachable``, and the scheduler backs off until the runtime answers.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from ollabridge.addons.local_catalog.client import LocalRuntimeUnreachable
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.scheduler import LocalCatalogScheduler
from ollabridge.addons.local_catalog.schemas import LocalSetupStatus, LocalSyncResult
from ollabridge.addons.local_catalog.sync_service import (
    UNREACHABLE_ERROR_PREFIX,
    LocalCatalogSyncService,
    is_unreachable_error,
)

import datetime as dt


def _tag(name: str, size: int = 4_000_000_000) -> dict:
    return {
        "name": name,
        "model": name,
        "size": size,
        "digest": "abc",
        "modified_at": "2026-01-01T00:00:00Z",
        "details": {"family": name.split(":")[0], "parameter_size": "7B"},
    }


class _UpClient:
    def __init__(self, tags):
        self.tags = tags

    async def list_tags(self):
        return list(self.tags)

    async def show(self, name):
        return {}


class _DownClient:
    base_url = "http://localhost:11434"

    async def list_tags(self):
        raise LocalRuntimeUnreachable(self.base_url, ConnectionRefusedError("refused"))

    async def show(self, name):
        return {}


def _service(tmp_path: Path) -> tuple[LocalCatalogRepository, LocalCatalogSyncService]:
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    svc = LocalCatalogSyncService(
        repository=repo, alias_path=tmp_path / "aliases.yaml", enrich_with_show=False,
    )
    return repo, svc


def test_downtime_leaves_the_catalog_exactly_as_it_was(tmp_path: Path, caplog):
    repo, svc = _service(tmp_path)
    up = _UpClient([_tag("qwen2.5:14b"), _tag("llama3.1:8b")])
    asyncio.run(svc.sync_node(node_id="n", client=up, auto_enable_top=2))
    before = {m.router_model_id: m.model_copy(deep=True) for m in repo.list_models("n")}
    assert before and all(m.setup_status != LocalSetupStatus.REMOVED for m in before.values())

    # Three ticks of downtime: previously enough to mark everything REMOVED.
    with caplog.at_level(logging.INFO, logger="ollabridge.addons.local_catalog"):
        for _ in range(3):
            result = asyncio.run(svc.sync_node(node_id="n", client=_DownClient(), auto_enable_top=2))

    assert result.ok is False
    assert is_unreachable_error(result.error)
    assert result.error.startswith(f"{UNREACHABLE_ERROR_PREFIX}: http://localhost:11434")
    assert result.fetched == 0 and result.upserted == 0 and result.marked_removed == 0
    after = {m.router_model_id: m for m in repo.list_models("n")}
    assert set(after) == set(before)
    for rid, m in after.items():
        assert m.setup_status == before[rid].setup_status
        assert m.missing_sync_count == before[rid].missing_sync_count
        assert m.is_top_recommended == before[rid].is_top_recommended
    # The last attempt is recorded (the UI shows it) but not shouted about.
    assert repo.last_sync("n").error == result.error
    assert "Traceback" not in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not [r for r in caplog.records if r.levelno == logging.INFO and "runtime_unreachable" in r.getMessage()]


def test_a_real_sync_failure_is_still_reported_loudly(tmp_path: Path, caplog):
    repo, svc = _service(tmp_path)

    class _Broken:
        async def list_tags(self):
            raise ValueError("garbage from upstream")

    with caplog.at_level(logging.ERROR, logger="ollabridge.addons.local_catalog"):
        result = asyncio.run(svc.sync_node(node_id="n", client=_Broken(), auto_enable_top=2))
    assert result.error == "ValueError: garbage from upstream"
    assert not is_unreachable_error(result.error)
    assert "local catalog sync failed" in caplog.text


# --- scheduler backoff ---------------------------------------------------------------


def _result(error: str | None) -> LocalSyncResult:
    now = dt.datetime.now(dt.timezone.utc)
    return LocalSyncResult(node_id="n", started_at=now, finished_at=now, error=error)


def test_scheduler_backs_off_while_down_and_snaps_back_when_up():
    sched = LocalCatalogScheduler(
        service=None, node_provider=lambda: [], interval_s=60, max_backoff_s=600, enabled=False,
    )
    assert sched.next_delay_s == 60
    down = _result(f"{UNREACHABLE_ERROR_PREFIX}: http://localhost:11434: refused")
    assert [sched._after_tick([down]) for _ in range(6)] == [120, 240, 480, 600, 600, 600]
    assert sched._after_tick([_result(None)]) == 60
    assert sched._after_tick([down]) == 120  # a new outage starts the ladder again


def test_scheduler_does_not_back_off_for_other_errors_or_mixed_nodes():
    sched = LocalCatalogScheduler(
        service=None, node_provider=lambda: [], interval_s=60, max_backoff_s=600, enabled=False,
    )
    assert sched._after_tick([_result("ValueError: boom")]) == 60
    down = _result(f"{UNREACHABLE_ERROR_PREFIX}: x")
    assert sched._after_tick([down, _result(None)]) == 60  # one node answered
    assert sched._after_tick([]) == 60  # nothing to sync (local runtime disabled)


def test_scheduler_reads_backoff_cap_from_env(monkeypatch):
    monkeypatch.setenv("OBRIDGE_LOCAL_SYNC_MAX_BACKOFF_S", "180")
    sched = LocalCatalogScheduler(service=None, node_provider=lambda: [], interval_s=60, enabled=False)
    down = _result(f"{UNREACHABLE_ERROR_PREFIX}: x")
    assert [sched._after_tick([down]) for _ in range(3)] == [120, 180, 180]


@pytest.mark.asyncio
async def test_scheduler_loop_uses_the_backed_off_delay(monkeypatch):
    """One real tick: the loop waits ``_after_tick``'s answer, not interval_s."""
    waits: list[float] = []

    class _Svc:
        async def sync_node(self, *, node_id, client, auto_enable_top):
            return _result(f"{UNREACHABLE_ERROR_PREFIX}: x")

    sched = LocalCatalogScheduler(
        service=_Svc(), node_provider=lambda: [("n", object())],
        interval_s=60, initial_delay_s=0, max_backoff_s=600, enabled=True,
    )
    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout):
        waits.append(timeout)
        if len(waits) >= 2:  # initial delay, then one tick's wait: stop here
            sched._stop.set()
        return await real_wait_for(awaitable, timeout=0)

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    await sched.start()
    await real_wait_for(sched._task, timeout=5)
    assert waits == [0, 120]  # initial delay, then the backed-off wait
