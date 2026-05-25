"""Unit tests for the gateway-side HF catalog (parser, scoring, snapshot, alias writer)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml

from ollabridge.addons.providers.hf_catalog.alias_writer import (
    _BEGIN_MARK,
    _END_MARK,
    build_managed_aliases,
    write_managed_aliases,
)
from ollabridge.addons.providers.hf_catalog.parser import normalize
from ollabridge.addons.providers.hf_catalog.schemas import (
    HFTask,
    ScoringProfile,
    SnapshotEntry,
)
from ollabridge.addons.providers.hf_catalog.scoring import (
    pick_top_n,
    score_rows,
)
from ollabridge.addons.providers.hf_catalog.snapshot import (
    MAX_MISSING_SYNCS_BEFORE_DROP,
    CatalogSnapshot,
)


# ── Parser ─────────────────────────────────────────────────


def test_parser_expands_each_provider_mapping_into_a_row():
    raw = [
        {
            "id": "meta-llama/Llama-3.3-70B-Instruct",
            "pipeline_tag": "text-generation",
            "trendingScore": 87.5,
            "likes": 1200,
            "tags": ["tool-use"],
            "inferenceProviderMapping": [
                {
                    "provider": "groq",
                    "status": "live",
                    "performance": {"firstTokenLatencyMs": 320, "tokensPerSecond": 220},
                    "providerDetails": {"context_length": 32000, "pricing": {"input": 0.5, "output": 0.7}},
                    "features": {"toolCalling": True, "structuredOutput": True},
                },
                {
                    "provider": "together",
                    "status": "live",
                    "performance": {"firstTokenLatencyMs": 1100, "tokensPerSecond": 90},
                    "providerDetails": {"context_length": 128000, "pricing": {"input": 0.6, "output": 0.9}},
                },
                {"provider": "offline-provider", "status": "offline"},
            ],
        }
    ]

    rows = normalize(raw)
    assert len(rows) == 2  # offline mapping dropped
    by_provider = {r.hf_provider: r for r in rows}

    groq = by_provider["groq"]
    assert groq.router_model_id == "meta-llama/Llama-3.3-70B-Instruct:groq"
    assert groq.task == HFTask.CHAT_COMPLETION
    assert groq.context_window == 32000
    assert groq.latency_s == pytest.approx(0.320)
    assert groq.throughput_tps == 220
    assert groq.supports_tools is True
    assert groq.supports_structured_output is True
    assert groq.input_price_per_1m == 0.5

    together = by_provider["together"]
    # tool-use tag at top level still surfaces, even though `features` omitted.
    assert together.supports_tools is True
    assert together.context_window == 128000


def test_parser_handles_vlm_pipeline():
    rows = normalize([
        {
            "id": "Qwen/Qwen2.5-VL-72B-Instruct",
            "pipeline_tag": "image-text-to-text",
            "trendingScore": 50.0,
            "inferenceProviderMapping": [
                {"provider": "novita", "status": "live"},
            ],
        }
    ])
    assert len(rows) == 1
    assert rows[0].task == HFTask.VLM


# ── Scoring ────────────────────────────────────────────────


def _row(**kwargs):
    base = dict(
        model_id="m/x",
        hf_provider="p",
        router_model_id="m/x:p",
        task=HFTask.CHAT_COMPLETION,
    )
    base.update(kwargs)
    base["router_model_id"] = f"{base['model_id']}:{base['hf_provider']}"
    from ollabridge.addons.providers.hf_catalog.schemas import HFInferenceModelRow
    return HFInferenceModelRow(**base)


def test_scoring_ranks_faster_and_cheaper_higher():
    fast_cheap = _row(model_id="a/fast", hf_provider="x", latency_s=0.3,
                      throughput_tps=200, input_price_per_1m=0.1, output_price_per_1m=0.2,
                      trending_score=90.0, supports_tools=True)
    slow_pricey = _row(model_id="b/slow", hf_provider="y", latency_s=3.0,
                       throughput_tps=20, input_price_per_1m=10.0, output_price_per_1m=20.0,
                       trending_score=10.0, supports_tools=False)
    scored = score_rows([fast_cheap, slow_pricey], profile=ScoringProfile.FREE_LAB)
    assert [r.model_id for r, _ in scored] == ["a/fast", "b/slow"]
    assert scored[0][1] > scored[1][1]


def test_scoring_drops_rows_with_no_signal():
    blind = _row(model_id="zzz/blind", hf_provider="p",
                 latency_s=None, throughput_tps=None, trending_score=None)
    good = _row(model_id="ok/good", hf_provider="p",
                latency_s=0.5, throughput_tps=80, trending_score=50.0)
    scored = score_rows([blind, good])
    assert len(scored) == 1
    assert scored[0][0].model_id == "ok/good"


def test_pick_top_n_dedupes_by_model_id():
    a1 = _row(model_id="m/llama", hf_provider="groq", latency_s=0.3, throughput_tps=200, trending_score=90)
    a2 = _row(model_id="m/llama", hf_provider="together", latency_s=0.5, throughput_tps=100, trending_score=90)
    b = _row(model_id="m/qwen", hf_provider="novita", latency_s=0.4, throughput_tps=150, trending_score=80)
    scored = score_rows([a1, a2, b])
    top = pick_top_n(scored, n=2)
    assert [r.model_id for r, _ in top] == ["m/llama", "m/qwen"]


# ── Snapshot ───────────────────────────────────────────────


def test_snapshot_upsert_round_trip(tmp_path):
    snap = CatalogSnapshot(path=tmp_path / "snap.yaml")
    snap.load()
    rows = [
        _row(model_id="x/a", hf_provider="groq", latency_s=0.3, throughput_tps=200, trending_score=90),
        _row(model_id="x/b", hf_provider="together", latency_s=1.0, throughput_tps=80, trending_score=70),
    ]
    scored = score_rows(rows)
    upserted, stale = snap.upsert(scored)
    assert upserted == 2
    assert stale == 0
    snap.save()

    snap2 = CatalogSnapshot(path=tmp_path / "snap.yaml")
    snap2.load()
    assert snap2.entry_count == 2
    entry = snap2.find("x/a:groq")
    assert entry is not None
    assert entry.rank == 1


def test_snapshot_drops_rows_after_repeated_misses(tmp_path):
    snap = CatalogSnapshot(path=tmp_path / "snap.yaml")
    snap.load()
    # First sync sees both rows.
    rows = [
        _row(model_id="x/a", hf_provider="groq", latency_s=0.3, throughput_tps=200, trending_score=90),
        _row(model_id="x/b", hf_provider="together", latency_s=1.0, throughput_tps=80, trending_score=70),
    ]
    snap.upsert(score_rows(rows))
    assert snap.entry_count == 2

    # Subsequent syncs only see "x/a"; "x/b" should age out.
    rows_partial = rows[:1]
    for _ in range(MAX_MISSING_SYNCS_BEFORE_DROP + 1):
        snap.upsert(score_rows(rows_partial))
    assert snap.entry_count == 1
    assert snap.find("x/b:together") is None


def test_snapshot_filter_by_capability():
    snap = CatalogSnapshot(path="/tmp/never_written.yaml")
    snap._entries = {
        "m/t:groq": SnapshotEntry(
            router_model_id="m/t:groq", model_id="m/t", hf_provider="groq",
            task=HFTask.CHAT_COMPLETION, rank=1, score=0.9,
            supports_tools=True, supports_structured_output=False,
        ),
        "m/v:novita": SnapshotEntry(
            router_model_id="m/v:novita", model_id="m/v", hf_provider="novita",
            task=HFTask.VLM, rank=2, score=0.7,
        ),
    }
    tools_only = snap.filter(supports_tools=True)
    assert [e.router_model_id for e in tools_only] == ["m/t:groq"]
    vlm_only = snap.filter(task="vlm")
    assert [e.router_model_id for e in vlm_only] == ["m/v:novita"]


# ── Alias writer ───────────────────────────────────────────


def _seed_entries() -> list[SnapshotEntry]:
    return [
        SnapshotEntry(
            router_model_id="meta-llama/Llama-3.3-70B-Instruct:groq",
            model_id="meta-llama/Llama-3.3-70B-Instruct",
            hf_provider="groq",
            task=HFTask.CHAT_COMPLETION, rank=1, score=0.92,
            latency_s=0.3, throughput_tps=220,
            supports_tools=True, supports_structured_output=True,
            input_price_per_1m=0.0, output_price_per_1m=0.0,
        ),
        SnapshotEntry(
            router_model_id="Qwen/Qwen2.5-VL-72B-Instruct:novita",
            model_id="Qwen/Qwen2.5-VL-72B-Instruct",
            hf_provider="novita",
            task=HFTask.VLM, rank=2, score=0.85,
            latency_s=0.9, throughput_tps=80,
        ),
        SnapshotEntry(
            router_model_id="deepseek-ai/DeepSeek-R1:together",
            model_id="deepseek-ai/DeepSeek-R1",
            hf_provider="together",
            task=HFTask.CHAT_COMPLETION, rank=3, score=0.80,
            latency_s=2.0, throughput_tps=40,
            labels=["reasoning"],
        ),
        SnapshotEntry(
            router_model_id="black-forest-labs/FLUX.1-Krea-dev:fal",
            model_id="black-forest-labs/FLUX.1-Krea-dev",
            hf_provider="fal",
            task=HFTask.IMAGE, rank=4, score=0.75,
        ),
    ]


def test_build_managed_aliases_picks_correct_buckets():
    managed = build_managed_aliases(_seed_entries())
    # Capability buckets all present and pointing to live entries.
    assert "ollabridge:fast" in managed
    assert managed["ollabridge:tools"][0]["model"] == "meta-llama/Llama-3.3-70B-Instruct:groq"
    assert managed["ollabridge:vision"][0]["model"] == "Qwen/Qwen2.5-VL-72B-Instruct:novita"
    assert managed["ollabridge:reasoning"][0]["model"] == "deepseek-ai/DeepSeek-R1:together"
    assert managed["ollabridge:image"][0]["model"] == "black-forest-labs/FLUX.1-Krea-dev:fal"
    # Synonym sanity:
    assert managed["hf:best"][0]["model"] == "meta-llama/Llama-3.3-70B-Instruct:groq"
    # Deepseek convenience bucket matches by label not hardcoded id.
    assert any("DeepSeek" in c["model"] for c in managed["hf:deepseek"])


def test_write_managed_aliases_round_trip(tmp_path):
    path = tmp_path / "model_aliases.yaml"
    path.write_text(
        "aliases:\n"
        "  ollabridge:auto:\n"
        "    - provider: ollama-node-01\n"
        "      model: qwen2.5:14b\n",
        encoding="utf-8",
    )
    managed = build_managed_aliases(_seed_entries())
    written = write_managed_aliases(path, managed)
    assert written == len(managed)

    text = path.read_text(encoding="utf-8")
    assert _BEGIN_MARK in text
    assert _END_MARK in text

    # Manual entry above sentinel survives.
    assert "ollabridge:auto" in text.split(_BEGIN_MARK)[0]

    # File still valid YAML and loads expected aliases.
    parsed = yaml.safe_load(text)
    assert "ollabridge:tools" in parsed["aliases"]
    assert parsed["aliases"]["ollabridge:vision"][0]["provider"] == "huggingface-free"


def test_write_managed_aliases_is_idempotent(tmp_path):
    path = tmp_path / "model_aliases.yaml"
    path.write_text("aliases: {}\n", encoding="utf-8")
    managed = build_managed_aliases(_seed_entries())
    write_managed_aliases(path, managed)
    text1 = path.read_text(encoding="utf-8")
    write_managed_aliases(path, managed)
    text2 = path.read_text(encoding="utf-8")
    assert text1 == text2


# ── SecretStore ────────────────────────────────────────────


def test_secret_store_encrypt_round_trip(tmp_path, monkeypatch):
    from ollabridge.addons.providers.secret_store import SecretStore

    store = SecretStore(path=tmp_path / "secrets.enc", secret="test-secret-123")
    store.set("huggingface", "hf_abcdef")
    assert store.get("huggingface") == "hf_abcdef"
    # Cipher text should be opaque on disk.
    on_disk = (tmp_path / "secrets.enc").read_text(encoding="utf-8")
    assert "hf_abcdef" not in on_disk

    store2 = SecretStore(path=tmp_path / "secrets.enc", secret="test-secret-123")
    assert store2.get("huggingface") == "hf_abcdef"


def test_secret_store_wrong_key_drops_entry(tmp_path):
    from ollabridge.addons.providers.secret_store import SecretStore

    store = SecretStore(path=tmp_path / "secrets.enc", secret="correct")
    store.set("huggingface", "hf_abcdef")

    bad = SecretStore(path=tmp_path / "secrets.enc", secret="wrong")
    assert bad.get("huggingface") is None


def test_secret_store_plaintext_mode_when_no_secret(tmp_path):
    from ollabridge.addons.providers.secret_store import SecretStore

    store = SecretStore(path=tmp_path / "secrets.enc", secret="")
    assert store.is_encrypted is False
    store.set("groq", "gsk_abc")
    assert store.get("groq") == "gsk_abc"
