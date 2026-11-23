"""Local usage ledger: capture, Claude Code telemetry, dashboard API, opt-in sync.

Acceptance checks from docs/USAGE_INTELLIGENCE.md §10.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest

from ollabridge.usage import capture, context, otlp, outbox
from ollabridge.usage import store as store_module
from ollabridge.usage.contract import UsageEvent
from ollabridge.usage.store import UsageStore, row_to_event

TODAY = dt.datetime.now(dt.timezone.utc)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A private usage database for one test."""
    fresh = UsageStore(tmp_path / "usage.db")
    monkeypatch.setattr(store_module, "_store", fresh)
    return fresh


def _event(**overrides) -> UsageEvent:
    fields = dict(source="local_gateway", provider="openai", model="m",
                  usage={"input_tokens": 100, "output_tokens": 40},
                  measurement="provider_reported")
    fields.update(overrides)
    return UsageEvent(**fields)


def _request(headers=None, registry=None, request_id="req_abc"):
    return SimpleNamespace(
        headers={k.lower(): v for k, v in (headers or {}).items()},
        state=SimpleNamespace(request_id=request_id),
        app=SimpleNamespace(state=SimpleNamespace(provider_registry=registry)),
    )


class _Registry:
    def __init__(self, **kinds):
        self._kinds = kinds

    def get_config(self, provider_id):
        kind = self._kinds.get(provider_id)
        if kind is None:
            return None
        return SimpleNamespace(kind=kind, category=SimpleNamespace(value="paid"))


# ── store ───────────────────────────────────────────────────────────────

def test_store_is_idempotent_and_prefers_better_measurements(store):
    estimate = _event(event_id="att_1", measurement="estimated",
                      usage={"input_tokens": 90, "output_tokens": 30})
    reported = _event(event_id="att_1", usage={"input_tokens": 100, "cache_read_tokens": 900,
                                               "output_tokens": 40})
    assert store.record(estimate) == "accepted"
    assert store.record(estimate) == "duplicate"
    assert store.record(reported) == "merged"
    assert store.record(estimate) == "duplicate"  # never downgrades
    (row,) = store.events()
    assert (row["input_tokens"], row["cache_read_tokens"], row["measurement"]) == (
        100, 900, "provider_reported")


def test_a_merged_event_is_queued_for_upload_again(store):
    store.record(_event(event_id="att_1", measurement="estimated"))
    store.mark_synced(["att_1"])
    assert store.pending() == []
    store.record(_event(event_id="att_1", usage={"input_tokens": 7, "output_tokens": 1}))
    assert [r["event_id"] for r in store.pending()] == ["att_1"]


def test_unknown_usage_is_null_not_zero(store):
    store.record(_event(usage={}, measurement="unavailable", status="interrupted"))
    (row,) = store.events()
    assert row["input_tokens"] is None and row["output_tokens"] is None
    (rollup,) = store.rollup_rows(TODAY.date(), TODAY.date())
    assert rollup["unknown_events"] == 1 and rollup["input_tokens"] == 0


def test_rollup_budget_and_prune(store):
    old = TODAY - dt.timedelta(days=40)
    store.record(_event(agent_id="a", cost={"estimated_micro": 500}))
    store.record(_event(agent_id="a", provider="gemini", cost={"provider_reported_micro": 70}))
    store.record(_event(agent_id="b", usage={"input_tokens": 5}))  # unpriced
    store.record(_event(occurred_at=old))
    rows = store.rollup_rows(TODAY.date(), TODAY.date())
    assert sum(r["events"] for r in rows) == 3
    assert sum(r["cost_micro"] for r in rows) == 570
    assert sum(r["reported_micro"] for r in rows) == 70
    assert sum(r["unpriced_tokens"] for r in rows) == 5
    assert len(store.rollup_rows(TODAY.date(), TODAY.date(), agent_id="b")) == 1

    assert store.get_budget_limit() is None
    store.set_budget_limit(2_000_000)
    store.set_budget_limit(3_000_000)
    assert store.get_budget_limit() == 3_000_000
    store.set_budget_limit(None)
    assert store.get_budget_limit() is None

    assert store.prune(keep_days=30) == 1
    assert len(store.events()) == 3


def test_usage_db_is_owner_only(store):
    import os
    import stat

    if os.name == "posix":
        assert not (store.path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))


def test_stored_rows_round_trip_through_the_contract(store):
    store.record(_event(application_id="homepilot", agent_id="coder",
                        usage={"input_tokens": 1, "other_units": {"gpu_seconds": 2.5}}))
    (row,) = store.pending()
    event = UsageEvent.model_validate(row_to_event(row))
    assert event.usage.other_units == {"gpu_seconds": 2.5} and event.agent_id == "coder"


# ── capture from the gateway's trace hook ───────────────────────────────

def test_gateway_estimates_are_labelled_estimated(store):
    capture.record_from_trace(_request({"X-Client-Type": "homepilot"}), dict(
        requested_model="fast", resolved_model="llama3", provider="ollama-local",
        tokens_in=12, tokens_out=30, latency_ms=250, ok=True))
    (row,) = store.events()
    assert (row["measurement"], row["input_tokens"], row["output_tokens"]) == ("estimated", 12, 30)
    assert (row["provider"], row["execution"], row["billing_mode"]) == ("ollama", "local_device", "local")
    assert (row["application_id"], row["trace_id"], row["requested_model"]) == ("homepilot", "req_abc", "fast")
    assert row["estimated_micro"] is None  # local inference is not priced as API spend


def test_ollama_runtime_counts_replace_the_estimate(store):
    context.note_raw_usage({"prompt_eval_count": 26, "eval_count": 298})
    capture.record_from_trace(_request(), dict(resolved_model="llama3", provider="ollama-local",
                                               tokens_in=1, tokens_out=1, ok=True))
    (row,) = store.events()
    assert (row["measurement"], row["input_tokens"], row["output_tokens"]) == ("locally_observed", 26, 298)


def test_provider_usage_names_the_real_provider_and_openrouter_as_biller(store):
    context.note_route("openrouter", "anthropic/some-model")
    context.note_raw_usage({"prompt_tokens": 1000, "completion_tokens": 200, "cost": 0.0125,
                            "prompt_tokens_details": {"cached_tokens": 800}})
    request = _request({"X-OllaBridge-App": "gitpilot", "X-OllaBridge-Agent": "reviewer",
                        "X-OllaBridge-Task": "task-7"}, registry=_Registry(openrouter="openrouter"))
    capture.record_from_trace(request, dict(requested_model="best", resolved_model="best",
                                            provider="provider-addon", tokens_in=5, tokens_out=5, ok=True))
    (row,) = store.events()
    assert (row["provider"], row["billing_provider"], row["model"]) == (
        "anthropic", "openrouter", "anthropic/some-model")
    assert (row["input_tokens"], row["cache_read_tokens"], row["output_tokens"]) == (200, 800, 200)
    assert (row["measurement"], row["reported_micro"], row["billing_mode"]) == (
        "provider_reported", 12_500, "api")
    assert (row["application_id"], row["agent_id"], row["task_id"]) == ("gitpilot", "reviewer", "task-7")


def test_a_failed_request_has_unknown_usage(store):
    capture.record_from_trace(_request(), dict(resolved_model="m", provider="ollama-local",
                                               tokens_in=40, ok=False, error_category="timeout"))
    (row,) = store.events()
    assert (row["status"], row["measurement"], row["input_tokens"]) == ("failed", "unavailable", None)
    assert row["error_category"] == "timeout"


def test_a_relayed_request_reuses_the_clouds_attempt_id(store):
    capture.record_from_trace(_request({"X-OllaBridge-Attempt-Id": "att_fromcloud"}),
                              dict(resolved_model="m", provider="ollama-local", tokens_in=1, ok=True))
    assert store.events()[0]["event_id"] == "att_fromcloud"


def test_noted_usage_does_not_leak_into_the_next_request(store):
    context.note_raw_usage({"prompt_eval_count": 999, "eval_count": 999})
    capture.record_from_trace(_request(), dict(resolved_model="m", provider="ollama-local", ok=True))
    capture.record_from_trace(_request(request_id="req_2"),
                              dict(resolved_model="m", provider="ollama-local", tokens_in=3, ok=True))
    newest = store.events()[0]
    assert (newest["input_tokens"], newest["measurement"]) == (3, "estimated")


def test_capture_can_be_switched_off(store, monkeypatch):
    monkeypatch.setattr(capture.settings, "USAGE_ENABLED", False)
    capture.record_from_trace(_request(), dict(resolved_model="m", provider="ollama-local", ok=True))
    assert store.events() == []


def test_capture_never_raises(store):
    capture.record_from_trace(object(), {"ok": True})  # not a request at all
    assert store.events() == []


def test_catalog_prices_api_usage_and_stamps_the_version(store, tmp_path, monkeypatch):
    catalog = tmp_path / "prices.yaml"
    catalog.write_text(json.dumps({"version": "v3", "prices": [{
        "provider": "acme", "model": "*",
        "per_million_micro_usd": {"input": 1_000_000, "output": 4_000_000}}]}))
    monkeypatch.setattr(capture.settings, "USAGE_PRICING_FILE", str(catalog))
    context.note_route("acme", "acme-large")
    context.note_raw_usage({"prompt_tokens": 2_000_000, "completion_tokens": 500_000})
    capture.record_from_trace(_request(registry=_Registry(acme="openai_compatible")),
                              dict(resolved_model="x", provider="provider-addon", ok=True))
    (row,) = store.events()
    assert (row["estimated_micro"], row["pricing_version"]) == (4_000_000, "v3")


# ── Claude Code telemetry ───────────────────────────────────────────────

def _attr(key, value):
    kind = "intValue" if isinstance(value, int) else "doubleValue" if isinstance(value, float) else "stringValue"
    return {"key": key, "value": {kind: str(value) if kind == "intValue" else value}}


def _otlp_payload(*records):
    return {"resourceLogs": [{
        "resource": {"attributes": [_attr("service.name", "claude-code")]},
        "scopeLogs": [{"logRecords": [
            {"timeUnixNano": str(int(TODAY.timestamp() * 1e9)),
             "body": {"stringValue": f"claude_code.{name}"},
             "attributes": [_attr("event.name", name), *[_attr(k, v) for k, v in attrs.items()]]}
            for name, attrs in records
        ]}],
    }]}


_API_REQUEST = ("api_request", {
    "session.id": "sess-1", "request_id": "req_cc_1", "model": "claude-some-model",
    "input_tokens": 12, "output_tokens": 350, "cache_read_tokens": 9000,
    "cache_creation_tokens": 400, "cost_usd": 0.0421, "duration_ms": 1840,
    "event.timestamp": TODAY.isoformat(),
})


def test_claude_code_cache_tokens_keep_their_own_dimensions():
    (event,) = otlp.parse_logs(_otlp_payload(
        _API_REQUEST,
        ("user_prompt", {"session.id": "sess-1", "prompt": "SECRET PROMPT TEXT", "prompt_length": 18}),
    ))
    usage = event.usage
    assert (usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens, usage.output_tokens) == (
        12, 9000, 400, 350)
    assert usage.total_tokens == 9762
    assert (event.source, event.provider, event.measurement) == (
        "claude_code_otel", "anthropic", "locally_observed")
    # Subscription by default: an API-equivalent estimate, never a stated charge.
    assert event.billing_mode == "subscription"
    assert event.cost.estimated_micro == 42_100 and event.cost.provider_reported_micro is None
    assert event.latency_ms == 1840 and event.application_id == "claude-code"
    assert "SECRET" not in event.model_dump_json()


def test_claude_code_reexport_is_recognised_as_the_same_event(store):
    payload = _otlp_payload(_API_REQUEST)
    first, second = otlp.parse_logs(payload), otlp.parse_logs(payload)
    assert first[0].event_id == second[0].event_id
    assert store.record(first[0]) == "accepted" and store.record(second[0]) == "duplicate"


def test_claude_code_missing_attributes_stay_unknown():
    (event,) = otlp.parse_logs(_otlp_payload(("api_request", {"model": "m"})))
    assert not event.usage.known and event.measurement == "unavailable"
    assert event.cost.estimated_micro is None
    assert otlp.parse_logs({}) == [] and otlp.parse_logs({"resourceLogs": [{}]}) == []


# ── HTTP API ────────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from ollabridge.api.main import create_app
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "API_KEYS", "test-key")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    with TestClient(create_app()) as c:
        yield c


KEY = {"X-API-Key": "test-key"}


def test_otlp_logs_feed_the_dashboard_api(client, store):
    payload = _otlp_payload(_API_REQUEST)
    # Not loopback (TestClient's peer is "testclient"), so a key is required.
    assert client.post("/otlp/v1/logs", json=payload).status_code == 401
    assert client.post("/otlp/v1/logs", json=payload, headers=KEY).json() == {}
    assert client.post("/otlp/v1/logs", json=payload, headers=KEY).status_code == 200  # re-export
    assert len(store.events()) == 1

    assert client.get("/v1/bi/overview").status_code == 401
    overview = client.get("/v1/bi/overview", headers=KEY).json()
    assert overview["total_tokens"]["value"] == 9762
    assert overview["total_tokens"]["measurement_mix"] == {"observed": 1.0}
    # Subscription usage is an equivalent figure, not API spend.
    assert overview["estimated_cost_micro"]["value"] == 0
    assert overview["subscription_equivalent_micro"]["value"] == 42_100
    assert overview["active_agents"]["value"] == 1

    series = client.get("/v1/bi/timeseries", params={"group_by": "provider"}, headers=KEY).json()
    assert series["series"][0]["key"] == "anthropic" and len(series["days"]) == 30
    agents = client.get("/v1/bi/agents", headers=KEY).json()
    assert agents["items"][0]["application_id"] == "claude-code"
    sources = client.get("/v1/bi/sources", headers=KEY).json()
    assert sources["sources"][0]["source"] == "claude_code_otel"
    assert sources["cloud_sync"]["enabled"] is False
    events = client.get("/v1/bi/events", headers=KEY).json()["items"]
    assert "sync_state" not in events[0]
    assert "items" in client.get("/v1/bi/insights", headers=KEY).json()
    assert client.get("/v1/bi/breakdown", params={"by": "nope"}, headers=KEY).status_code == 422


def test_otlp_rejects_protobuf_with_a_fix_and_ignores_metrics(client, store):
    response = client.post("/otlp/v1/logs", content=b"\x0a\x00",
                           headers={**KEY, "Content-Type": "application/x-protobuf"})
    assert response.status_code == 415 and "http/json" in response.json()["detail"]
    assert client.post("/otlp/v1/metrics", json={"resourceMetrics": []}, headers=KEY).json() == {}
    assert store.events() == []


def test_budget_round_trips_through_the_api(client):
    assert client.get("/v1/bi/budget", headers=KEY).json()["limit_micro"] is None
    assert client.put("/v1/bi/budget", json={"limit_micro": 2_000_000_000}, headers=KEY).status_code == 200
    budget = client.get("/v1/bi/overview", headers=KEY).json()["budget"]
    assert budget["limit_micro"] == budget["remaining_micro"] == 2_000_000_000
    assert client.put("/v1/bi/budget", json={"limit_micro": -1}, headers=KEY).status_code == 422


# ── opt-in sync ─────────────────────────────────────────────────────────

def test_usage_sync_is_off_by_default_even_when_cloud_sync_is_enabled():
    from ollabridge.cloud.sync_config import METADATA_FIELDS, CloudSyncConfig

    assert "usage_metadata" in METADATA_FIELDS
    assert CloudSyncConfig(enabled=True).usage_metadata is False
    # A sync.yaml written before this category existed loads with it off.
    assert CloudSyncConfig.model_validate({"enabled": True, "health_metrics": True}).usage_metadata is False


@pytest.fixture
def paired(tmp_path, monkeypatch):
    """A paired device with usage sync switched on."""
    from ollabridge.cloud import device_config, sync_config

    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    device_config.save_cloud_device_credentials(
        device_config.CloudDeviceCredentials("https://cloud.example", "dev_1", "secret-token"))
    sync_config.save_sync_config(sync_config.CloudSyncConfig(enabled=True, usage_metadata=True))


def _run_sync(store, handler):
    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await outbox.sync_once(store, client=client)

    return asyncio.new_event_loop().run_until_complete(_go())


def test_nothing_is_uploaded_without_consent(store, tmp_path, monkeypatch):
    from ollabridge.cloud import device_config, sync_config

    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    store.record(_event())

    def _never(request):  # pragma: no cover - reaching the network is the failure
        raise AssertionError("usage was uploaded without consent")

    assert "disabled" in _run_sync(store, _never)["skipped"]
    sync_config.save_sync_config(sync_config.CloudSyncConfig(enabled=True))
    assert "usage_metadata" in _run_sync(store, _never)["skipped"]
    sync_config.save_sync_config(sync_config.CloudSyncConfig(enabled=True, usage_metadata=True))
    assert "not paired" in _run_sync(store, _never)["skipped"]
    assert len(store.pending()) == 1
    del device_config  # imported to keep the fixture's module loaded


def test_sync_uploads_metadata_and_marks_each_event(store, paired):
    store.record(_event(event_id="att_ok"))
    store.record(_event(event_id="att_dup"))
    store.record(_event(event_id="att_bad"))
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [
            {"event_id": "att_ok", "status": "accepted"},
            {"event_id": "att_dup", "status": "duplicate"},
            {"event_id": "att_bad", "status": "rejected", "reason": "x"},
        ]})

    assert _run_sync(store, handler) == {"synced": 2, "rejected": 1}
    assert seen["url"] == "https://cloud.example/v1/ledger/events"
    assert seen["auth"] == "Bearer secret-token"
    # The upload is contract-valid and carries no identity or content fields.
    for raw in seen["body"]["events"]:
        UsageEvent.model_validate(raw)
        assert not {"user_id", "org_id", "sync_state"} & set(raw)
    assert store.pending() == []
    assert store.sync_counts() == {"rejected": 1, "synced": 2}


@pytest.mark.parametrize("status", [404, 503])
def test_an_outage_or_older_cloud_keeps_events_pending(store, paired, status):
    store.record(_event())
    result = _run_sync(store, lambda request: httpx.Response(status))
    assert result == {"synced": 0, "rejected": 0, "error": f"http_{status}"}
    assert len(store.pending()) == 1

    def down(request):
        raise httpx.ConnectError("offline")

    assert _run_sync(store, down)["error"] == "ConnectError"
    assert len(store.pending()) == 1
    # Back online: the queue drains, with no duplicates.
    ok = lambda request: httpx.Response(200, json={"results": [  # noqa: E731
        {"event_id": e["event_id"], "status": "accepted"} for e in json.loads(request.content)["events"]]})
    assert _run_sync(store, ok) == {"synced": 1, "rejected": 0}
    assert _run_sync(store, ok) == {"synced": 0, "rejected": 0}


# ── display currency ────────────────────────────────────────────────────

def test_display_currency_defaults_to_usd_and_needs_an_explicit_rate(store):
    from ollabridge.usage import currency

    assert currency.get_display_currency(store) == {"code": "USD", "usd_rate": 1.0, "source": "default"}
    with pytest.raises(ValueError, match="rate is required"):
        currency.set_display_currency("EUR", None, store)
    with pytest.raises(ValueError):
        currency.set_display_currency("euro", 0.9, store)
    with pytest.raises(ValueError):
        currency.set_display_currency("EUR", -1, store)
    assert currency.set_display_currency("eur", 0.5, store) == {
        "code": "EUR", "usd_rate": 0.5, "source": "saved"}
    assert currency.format_money(1_185_430_000, currency.get_display_currency(store)) == "€592.72"
    assert currency.format_money(None, currency.get_display_currency(store)) == "—"
    assert currency.set_display_currency("USD", None, store)["usd_rate"] == 1.0


def test_display_currency_can_come_from_the_environment(store, monkeypatch):
    from ollabridge.usage import currency

    monkeypatch.setattr(capture.settings, "USAGE_DISPLAY_CURRENCY", "EUR")
    monkeypatch.setattr(capture.settings, "USAGE_DISPLAY_RATE", 0.8)
    assert currency.get_display_currency(store) == {"code": "EUR", "usd_rate": 0.8, "source": "environment"}
    # A saved choice wins.
    currency.set_display_currency("GBP", 0.7, store)
    assert currency.get_display_currency(store)["code"] == "GBP"


def test_changing_the_display_currency_never_rewrites_the_ledger(client, store):
    store.record(_event(cost={"estimated_micro": 2_000_000}))
    before = client.get("/v1/bi/overview", headers=KEY).json()["estimated_cost_micro"]["value"]
    assert client.put("/v1/bi/currency", json={"code": "EUR"}, headers=KEY).status_code == 422
    assert client.put("/v1/bi/currency", json={"code": "EUR", "usd_rate": 0.5}, headers=KEY).json() == {
        "code": "EUR", "usd_rate": 0.5, "source": "saved"}
    assert client.get("/v1/bi/currency", headers=KEY).json()["code"] == "EUR"
    # Stored and served amounts are still micro-USD.
    assert client.get("/v1/bi/overview", headers=KEY).json()["estimated_cost_micro"]["value"] == before
    assert store.events()[0]["estimated_micro"] == 2_000_000
