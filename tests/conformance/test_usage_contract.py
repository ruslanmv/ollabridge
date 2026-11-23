"""Conformance for the shared usage contract (``ollabridge-usage/1``).

This file, the fixtures beside it and the four vendored modules are identical
in both OllaBridge repositories. The manifest pins their hashes: a change to
one copy fails here until the other repository is updated to match.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "usage_fixtures"

for _package in ("ollabridge_cloud.usage", "ollabridge.usage"):
    try:
        contract = importlib.import_module(f"{_package}.contract")
    except ModuleNotFoundError:
        continue
    normalize = importlib.import_module(f"{_package}.normalize")
    pricing = importlib.import_module(f"{_package}.pricing")
    bi_core = importlib.import_module(f"{_package}.bi_core")
    break
else:  # pragma: no cover
    raise ImportError("no OllaBridge usage package importable")

CASES = json.loads((FIXTURES / "provider_usage.json").read_text(encoding="utf-8"))["cases"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vendored_files_match_the_shared_manifest():
    manifest = json.loads((FIXTURES / "vendored.sha256.json").read_text(encoding="utf-8"))
    package_dir = Path(contract.__file__).parent
    actual = {name: _sha256(package_dir / name) for name in manifest["modules"]}
    actual_fixtures = {name: _sha256(FIXTURES / name) for name in manifest["fixtures"]}
    assert actual == manifest["modules"], "vendored usage module drifted from the other repository"
    assert actual_fixtures == manifest["fixtures"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_provider_usage_normalises_to_disjoint_dimensions(case):
    usage = normalize.normalize_usage(case["raw"])
    assert {d: getattr(usage, d) for d in contract.TOKEN_DIMENSIONS} == case["expect"]
    assert usage.total_tokens == case["total"]
    if "reported_cost_micro" in case:
        assert normalize.reported_cost_micro(case["raw"]) == case["reported_cost_micro"]


def test_schema_has_no_room_for_content():
    with pytest.raises(ValidationError):
        contract.UsageEvent(source="local_gateway", provider="openai", prompt="secret text")
    with pytest.raises(ValidationError):
        contract.UsageEvent(source="local_gateway", provider="openai",
                            usage={"input_tokens": 1, "messages": ["hi"]})


def test_labels_are_sanitised_and_ids_are_strict():
    event = contract.UsageEvent(
        source="local_gateway", provider="OpenAI",
        application_id="home<script>pilot\n", agent_id="x" * 500,
    )
    assert event.provider == "openai"
    assert event.application_id == "homescriptpilot"
    assert len(event.agent_id) == 128
    with pytest.raises(ValidationError):
        contract.UsageEvent(source="local_gateway", provider="openai", event_id="bad id!")


def test_negative_tokens_are_rejected():
    with pytest.raises(ValidationError):
        contract.UsageEvent(source="local_gateway", provider="openai", usage={"input_tokens": -1})


def test_usd_to_micro_is_exact():
    assert normalize.usd_to_micro("0.000001") == 1
    assert normalize.usd_to_micro(1185.43) == 1_185_430_000
    assert normalize.usd_to_micro("nan") is None
    assert normalize.usd_to_micro(-1) is None


def test_pricing_is_integer_versioned_and_date_aware():
    catalog = pricing.PriceCatalog.from_dict({
        "version": "test-1",
        "prices": [
            {"provider": "acme", "model": "big-*", "effective_from": "2026-06-01",
             "per_million_micro_usd": {"input": 3_000_000, "output": 15_000_000,
                                       "cache_read": 300_000}},
        ],
    })
    usage = contract.Usage(input_tokens=1000, cache_read_tokens=10_000,
                           cache_write_tokens=100, output_tokens=200, reasoning_tokens=50)
    # 1000*3 + 10000*0.3 + 100*3 (falls back to input) + 200*15 + 50*15 (falls back to output)
    # = 3000 + 3000 + 300 + 3000 + 750 = 10050 micro-USD
    assert catalog.cost_micro("acme", "big-model", usage, dt.date(2026, 7, 1)) == (10050, "test-1")
    assert catalog.cost_micro("acme", "big-model", usage, dt.date(2026, 5, 1)) == (None, None)
    assert catalog.cost_micro("acme", "small", usage, dt.date(2026, 7, 1)) == (None, None)
    assert catalog.cost_micro("acme", "big-model", contract.Usage(), dt.date(2026, 7, 1)) == (None, None)


def test_pricing_rejects_incomplete_entries():
    with pytest.raises(ValueError):
        pricing.PriceCatalog.from_dict(
            {"prices": [{"provider": "a", "model": "m", "per_million_micro_usd": {"input": 1}}]}
        )


def _row(**overrides):
    row = {
        "day": "2026-11-10", "provider": "openai", "billing_provider": "openai", "model": "m",
        "application_id": "app", "agent_id": "agent-a", "device_id": None,
        "billing_mode": "api", "measurement": "provider_reported", "status": "completed",
        "events": 1, "unknown_events": 0, "input_tokens": 100, "cache_read_tokens": 0,
        "cache_write_tokens": 0, "output_tokens": 50, "reasoning_tokens": 0,
        "cost_micro": 1000, "reported_micro": 0, "unpriced_tokens": 0,
    }
    row.update(overrides)
    return row


def test_overview_keeps_subscription_usage_out_of_api_spend():
    rows = [
        _row(),
        _row(provider="anthropic", billing_mode="subscription", measurement="locally_observed",
             agent_id="claude-code", cost_micro=9000, input_tokens=1000, output_tokens=0),
    ]
    result = bi_core.overview(rows, [_row(input_tokens=50, output_tokens=25, cost_micro=500)],
                              start=dt.date(2026, 11, 1), end=dt.date(2026, 11, 15),
                              budget_limit_micro=10_000, month_rows=rows, today=dt.date(2026, 11, 15))
    assert result["total_tokens"]["value"] == 1150
    assert result["total_tokens"]["delta_pct"] == round((1150 - 75) / 75 * 100, 1)
    assert result["estimated_cost_micro"]["value"] == 1000
    assert result["subscription_equivalent_micro"]["value"] == 9000
    assert result["active_agents"]["value"] == 2
    assert result["budget"]["spent_micro"] == 1000
    assert result["budget"]["remaining_micro"] == 9000
    assert result["forecast"]["projected_month_end_micro"] == 2000
    mix = result["total_tokens"]["measurement_mix"]
    assert mix["verified"] == round(150 / 1150, 4) and mix["observed"] == round(1000 / 1150, 4)


def test_timeseries_fills_every_day_and_buckets_the_tail():
    rows = [_row(provider=f"p{i}", input_tokens=100 * (i + 1), output_tokens=0) for i in range(8)]
    result = bi_core.timeseries(rows, start=dt.date(2026, 11, 9), end=dt.date(2026, 11, 11), top=3)
    assert result["days"] == ["2026-11-09", "2026-11-10", "2026-11-11"]
    assert [s["key"] for s in result["series"]] == ["p7", "p6", "p5", "others"]
    assert result["series"][0]["values"] == [0, 800, 0]
    assert result["series"][-1]["total"] == 100 + 200 + 300 + 400 + 500


def test_breakdown_and_agents():
    rows = [_row(cost_micro=3000), _row(provider="gemini", agent_id=None, cost_micro=1000,
                                        status="failed")]
    shares = bi_core.breakdown(rows, by="provider", metric="cost")
    assert [(i["key"], i["share"]) for i in shares["items"]] == [("openai", 0.75), ("gemini", 0.25)]
    table = bi_core.agents(rows, [_row(input_tokens=50, output_tokens=50)])
    assert table["items"][0]["agent_id"] == "agent-a"
    assert table["items"][0]["delta_pct"] == 50.0
    assert table["items"][1]["agent_id"] == bi_core.UNATTRIBUTED
    assert table["items"][1]["failed"] == 1


def test_insights_are_evidence_backed():
    rows = [_row(status="failed", cost_micro=700), _row(agent_id=None, measurement="estimated")]
    found = {item["id"]: item for item in bi_core.insights(rows)}
    assert found["failed_attempts"]["estimated_saving_micro"] == 700
    assert "unattributed_usage" in found and "estimated_share" in found
    assert bi_core.insights([]) == []
