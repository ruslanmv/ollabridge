"""Unit tests for the local model catalog addon.

No network, no Ollama runtime needed — the client is only exercised via
unit-level helpers that don't touch HTTP. The parser, scoring, repository
and sync_service surface paths are covered with synthetic inputs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from ollabridge.addons.local_catalog.parser import normalize
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.schemas import (
    LocalModel,
    LocalRuntime,
    LocalScoringProfile,
    LocalSetupStatus,
    LocalSyncResult,
    ModelCapabilities,
)
from ollabridge.addons.local_catalog.scoring import pick_top_n, score_models
from ollabridge.addons.local_catalog.sync_service import (
    LocalCatalogSyncService,
    _row_to_persisted,
)


# ── Parser ──────────────────────────────────────────────────


def _tag(name: str, **extras) -> dict:
    base = {
        "name": name,
        "model": name,
        "size": 4_700_000_000,
        "modified_at": "2026-05-01T12:00:00.123456789Z",
        "details": {},
    }
    base.update(extras)
    return base


def test_parser_extracts_family_and_param_size_from_tag():
    rows = normalize("node-01", [_tag("qwen2.5:14b"), _tag("llama3.1:8b")])
    by_name = {r.external_model_id: r for r in rows}
    assert by_name["qwen2.5:14b"].family == "qwen2.5"
    assert by_name["qwen2.5:14b"].parameter_size == "14b"
    assert by_name["qwen2.5:14b"].parameter_count == 14_000
    assert by_name["llama3.1:8b"].parameter_count == 8_000
    assert by_name["llama3.1:8b"].router_model_id == "node-01:llama3.1:8b"


def test_parser_prefers_show_details_over_tag_inference():
    rows = normalize(
        "node-01",
        [_tag("custom-model:latest", details={})],
        show_details={
            "custom-model:latest": {
                "details": {
                    "family": "qwen",
                    "parameter_size": "7B",
                    "quantization_level": "Q4_K_M",
                }
            }
        },
    )
    assert rows[0].family == "qwen"
    assert rows[0].parameter_count == 7_000
    assert (rows[0].quantization or "").lower() == "q4_k_m"


def test_parser_marks_embedding_family_correctly():
    rows = normalize("node-01", [_tag("nomic-embed-text:latest")])
    cap = rows[0].capabilities
    assert cap.supports_embeddings is True
    assert cap.supports_chat is False


def test_parser_marks_vision_family_correctly():
    rows = normalize("node-01", [_tag("llava:13b")])
    assert rows[0].capabilities.supports_vision is True


def test_parser_skips_entries_with_no_name():
    rows = normalize("node-01", [{}, {"size": 100}])
    assert rows == []


def test_parser_handles_iso_modified_at_with_nanoseconds():
    rows = normalize("node-01", [_tag("qwen2.5:7b")])
    assert rows[0].modified_at is not None
    assert rows[0].modified_at.tzinfo is not None


# ── Scoring ─────────────────────────────────────────────────


def _persisted(router_id: str, **overrides) -> LocalModel:
    parts = router_id.split(":", 1)
    node_id, ext = parts[0], parts[1]
    defaults = dict(
        node_id=node_id,
        runtime=LocalRuntime.OLLAMA,
        external_model_id=ext,
        router_model_id=router_id,
        family="qwen",
        parameter_size="7b",
        parameter_count=7_000,
        capabilities=ModelCapabilities(supports_chat=True, supports_tools=True),
        setup_status=LocalSetupStatus.VERIFIED,
        latency_observed_ms=200.0,
        modified_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10),
    )
    defaults.update(overrides)
    return LocalModel(**defaults)


def test_scoring_prefers_verified_over_broken():
    good = _persisted("n:a", setup_status=LocalSetupStatus.VERIFIED)
    bad = _persisted("n:b", setup_status=LocalSetupStatus.BROKEN)
    scored = score_models([good, bad])
    assert scored[0][0].router_model_id == "n:a"
    assert scored[0][1] > scored[1][1]


def test_scoring_prefers_sweet_spot_size():
    tiny = _persisted("n:a", parameter_count=500, parameter_size="500m")
    sweet = _persisted("n:b", parameter_count=8_000, parameter_size="8b")
    huge = _persisted("n:c", parameter_count=120_000, parameter_size="120b")
    scored = {r.router_model_id: s for r, s in score_models([tiny, sweet, huge])}
    assert scored["n:b"] > scored["n:a"]
    assert scored["n:b"] > scored["n:c"]


def test_scoring_pin_promotes_low_quality_model():
    pinned = _persisted("n:a", setup_status=LocalSetupStatus.AUTO, pinned=True)
    auto = _persisted("n:b", setup_status=LocalSetupStatus.AUTO, pinned=False)
    scored = {r.router_model_id: s for r, s in score_models([pinned, auto])}
    assert scored["n:a"] > scored["n:b"]


def test_scoring_is_deterministic():
    rows = [_persisted(f"n:m{i}") for i in range(5)]
    a = score_models(rows)
    b = score_models(rows)
    assert [r.router_model_id for r, _ in a] == [r.router_model_id for r, _ in b]
    assert [s for _, s in a] == [s for _, s in b]


def test_pick_top_n_excludes_embedding_only_when_requiring_chat():
    chat = _persisted("n:a", capabilities=ModelCapabilities(supports_chat=True))
    embed = _persisted("n:b", capabilities=ModelCapabilities(
        supports_chat=False, supports_embeddings=True,
    ))
    scored = score_models([chat, embed])
    top = pick_top_n(scored, n=2, require_chat=True)
    assert {m.router_model_id for m, _ in top} == {"n:a"}


def test_pick_top_n_dedupes_family():
    a = _persisted("n:a", family="qwen", latency_observed_ms=100.0)
    b = _persisted("n:b", family="qwen", latency_observed_ms=500.0)
    c = _persisted("n:c", family="llama", latency_observed_ms=400.0)
    scored = score_models([a, b, c])
    top = pick_top_n(scored, n=2, dedupe_family=True)
    families = {m.family for m, _ in top}
    assert families == {"qwen", "llama"}


def test_privacy_profile_prefers_smaller_models():
    big = _persisted("n:a", parameter_count=70_000, parameter_size="70b",
                       latency_observed_ms=200.0)
    small = _persisted("n:b", parameter_count=3_000, parameter_size="3b",
                          latency_observed_ms=200.0)
    default = {r.router_model_id: s for r, s in score_models([big, small])}
    privacy = {r.router_model_id: s
                for r, s in score_models([big, small], profile=LocalScoringProfile.PRIVACY)}
    # Default profile keeps small ahead of big, privacy should widen the gap.
    assert (privacy["n:b"] - privacy["n:a"]) > (default["n:b"] - default["n:a"])


# ── Repository ──────────────────────────────────────────────


def test_repository_upsert_new_then_update(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    m = _persisted("n:a")
    new, updated = asyncio.run(repo.upsert_many("n", [m]))
    assert (new, updated) == (1, 0)
    new, updated = asyncio.run(repo.upsert_many("n", [_persisted("n:a", score=0.99)]))
    assert (new, updated) == (0, 1)
    assert repo.get("n:a").score == 0.99


def test_repository_preserves_admin_state_on_upsert(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    asyncio.run(repo.upsert_many("n", [_persisted("n:a")]))
    asyncio.run(repo.set_enabled("n:a", True))
    asyncio.run(repo.set_pinned("n:a", True))
    asyncio.run(repo.upsert_many("n", [_persisted("n:a", score=0.01)]))
    m = repo.get("n:a")
    assert m.enabled is True and m.pinned is True


def test_repository_mark_removed_after_threshold(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    asyncio.run(repo.upsert_many("n", [_persisted("n:a"), _persisted("n:b")]))
    transitioned = 0
    for _ in range(2):
        transitioned += asyncio.run(repo.mark_removed("n", {"n:a"}))
    assert repo.get("n:b").setup_status == LocalSetupStatus.REMOVED
    assert repo.get("n:a").setup_status != LocalSetupStatus.REMOVED
    assert transitioned == 1


def test_repository_apply_top_recommendation(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    asyncio.run(repo.upsert_many("n", [_persisted("n:a"), _persisted("n:b"), _persisted("n:c")]))
    promoted, demoted = asyncio.run(repo.apply_top_recommendation("n", ["n:a", "n:b"]))
    assert promoted == 2 and demoted == 0
    assert repo.get("n:a").enabled is True
    promoted, demoted = asyncio.run(repo.apply_top_recommendation("n", ["n:a", "n:c"]))
    assert promoted == 1 and demoted == 1
    # Demoted row keeps enabled (admin-friendly).
    assert repo.get("n:b").enabled is True


def test_repository_record_check_flips_status(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    asyncio.run(repo.upsert_many("n", [_persisted("n:a", setup_status=LocalSetupStatus.AUTO)]))
    asyncio.run(repo.record_check("n:a", ok=True, error=None, latency_ms=120.0))
    assert repo.get("n:a").setup_status == LocalSetupStatus.VERIFIED
    asyncio.run(repo.record_check("n:a", ok=False, error="http_500", latency_ms=10.0))
    assert repo.get("n:a").setup_status == LocalSetupStatus.BROKEN


def test_repository_round_trip_yaml(tmp_path: Path):
    path = tmp_path / "cat.yaml"
    repo1 = LocalCatalogRepository(path=path)
    asyncio.run(repo1.upsert_many("n", [_persisted("n:a", score=0.42)]))
    asyncio.run(repo1.set_pinned("n:a", True))
    asyncio.run(repo1.save())

    repo2 = LocalCatalogRepository(path=path)
    repo2.load()
    assert repo2.get("n:a") is not None
    assert repo2.get("n:a").pinned is True
    assert repo2.get("n:a").score == 0.42


# ── Sync service (with stub client) ─────────────────────────


class _StubClient:
    def __init__(self, tags, show=None):
        self.tags = tags
        self._show = show or {}

    async def list_tags(self):
        return list(self.tags)

    async def show(self, name):
        return self._show.get(name, {})


def test_sync_service_end_to_end(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    svc = LocalCatalogSyncService(
        repository=repo,
        alias_path=tmp_path / "aliases.yaml",
        enrich_with_show=False,
    )
    client = _StubClient([
        _tag("qwen2.5:14b"),
        _tag("llama3.1:8b"),
        _tag("nomic-embed-text:latest", size=200_000_000),
    ])
    result = asyncio.run(svc.sync_node(node_id="n", client=client, auto_enable_top=2))
    assert result.ok is True
    assert result.fetched == 3
    assert result.upserted == 3
    assert result.aliases_written >= 1
    # Top 2 should be the chat-capable models, not the embedding one.
    top_ids = {m.router_model_id for m in repo.list_top("n")}
    assert "n:nomic-embed-text:latest" not in top_ids
    assert len(top_ids) == 2
    # Alias file was written.
    assert (tmp_path / "aliases.yaml").exists()


def test_sync_service_preserves_pinned_through_resync(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    svc = LocalCatalogSyncService(
        repository=repo,
        alias_path=tmp_path / "aliases.yaml",
        enrich_with_show=False,
    )
    client = _StubClient([_tag("qwen2.5:14b"), _tag("llama3.1:8b")])
    asyncio.run(svc.sync_node(node_id="n", client=client, auto_enable_top=1))
    asyncio.run(repo.set_pinned("n:llama3.1:8b", True))
    asyncio.run(svc.sync_node(node_id="n", client=client, auto_enable_top=1))
    # Pin survives.
    assert repo.get("n:llama3.1:8b").pinned is True


def test_sync_service_marks_disappeared_models_removed(tmp_path: Path):
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    svc = LocalCatalogSyncService(
        repository=repo,
        alias_path=tmp_path / "aliases.yaml",
        enrich_with_show=False,
    )
    client_full = _StubClient([_tag("qwen2.5:14b"), _tag("llama3.1:8b")])
    client_partial = _StubClient([_tag("qwen2.5:14b")])

    asyncio.run(svc.sync_node(node_id="n", client=client_full, auto_enable_top=2))
    # Two consecutive misses → REMOVED.
    asyncio.run(svc.sync_node(node_id="n", client=client_partial, auto_enable_top=2))
    asyncio.run(svc.sync_node(node_id="n", client=client_partial, auto_enable_top=2))
    assert repo.get("n:llama3.1:8b").setup_status == LocalSetupStatus.REMOVED


def test_row_to_persisted_round_trip():
    rows = normalize("n", [_tag("qwen2.5:14b")])
    m = _row_to_persisted(rows[0])
    assert m.router_model_id == "n:qwen2.5:14b"
    assert m.family == "qwen2.5"
    assert m.parameter_count == 14_000
