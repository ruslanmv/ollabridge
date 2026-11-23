"""Per-model usage view: docs/USAGE_BY_MODEL_DESIGN.md §5."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from ollabridge.usage import capture, context, model_usage
from ollabridge.usage import store as store_module
from ollabridge.usage.contract import UsageEvent
from ollabridge.usage.store import UsageStore

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date()
START = TODAY - dt.timedelta(days=29)


@pytest.fixture
def store(tmp_path, monkeypatch):
    fresh = UsageStore(tmp_path / "usage.db")
    monkeypatch.setattr(store_module, "_store", fresh)
    return fresh


def _record(store, days_ago=0, **overrides):
    fields = dict(source="local_gateway", provider="acme", model="acme/m1",
                  usage={"input_tokens": 100, "output_tokens": 40},
                  measurement="provider_reported", billing_mode="api",
                  occurred_at=NOW - dt.timedelta(days=days_ago))
    fields.update(overrides)
    store.record(UsageEvent(**fields))


def _view(store, **kwargs):
    return model_usage.build(store.model_rows(START, TODAY), start=START, end=TODAY, **kwargs)


def _row(view, provider, model):
    return next(m for m in view["models"] if (m["provider"], m["model"]) == (provider, model))


# ── reconciliation ──────────────────────────────────────────────────────

def test_totals_table_and_chart_reconcile(store):
    _record(store, usage={"input_tokens": 100, "cache_read_tokens": 50, "output_tokens": 40})
    _record(store, days_ago=3, model="acme/m2", usage={"input_tokens": 7, "output_tokens": 3,
                                                        "reasoning_tokens": 2})
    _record(store, days_ago=10, provider="other", model="o/x", billing_mode="local")
    _record(store, model="acme/m1", status="failed", usage={}, measurement="unavailable")
    view = _view(store)

    totals, models = view["totals"], view["models"]
    assert totals["tokens"]["total"] == 150 + 40 + 7 + 3 + 2 + 140
    assert totals["tokens"]["total"] == sum(m["tokens"]["total"] or 0 for m in models)
    assert totals["tokens"]["total"] == sum(view["daily"]["tokens"])
    assert totals["tokens"]["total"] == sum(sum(m["daily"]["tokens"]) for m in models)
    assert totals["requests"] == sum(m["requests"] for m in models) == sum(view["daily"]["requests"]) == 4
    assert totals["tokens"]["input"] + totals["tokens"]["output"] == totals["tokens"]["total"]
    assert totals["failed"] == 1 and totals["failed_pct"] == 25.0
    assert totals["models_used"] == 3


def test_unknown_tokens_are_not_zero(store):
    _record(store, status="failed", usage={}, measurement="unavailable", error_category="provider_timeout")
    view = _view(store)
    row = _row(view, "acme", "acme/m1")
    assert row["tokens"]["total"] is None
    assert row["unknown_usage"] == 1
    assert row["errors"] == {"provider_timeout": 1}
    assert view["totals"]["tokens"]["total"] is None
    assert row["cost"]["state"] == "none"


# ── cost ────────────────────────────────────────────────────────────────

def test_missing_pricing_is_unpriced_not_zero(store):
    _record(store)  # api, no price
    view = _view(store)
    assert _row(view, "acme", "acme/m1")["cost"] == {
        "state": "unpriced", "micro": None, "unpriced_tokens": 140, "modes": ["api"]}
    assert view["totals"]["cost"]["state"] == "unpriced"
    assert any(i["kind"] == "unpriced_usage" for i in view["insights"])


def test_partly_priced_is_a_floor_and_fully_priced_is_a_figure(store):
    priced = {"estimated_micro": 2500}
    _record(store, cost=priced)
    _record(store)
    _record(store, model="acme/m2", cost=priced)
    view = _view(store)
    assert _row(view, "acme", "acme/m1")["cost"]["state"] == "partial"
    assert _row(view, "acme", "acme/m1")["cost"]["micro"] == 2500
    assert _row(view, "acme", "acme/m2")["cost"] == {
        "state": "priced", "micro": 2500, "unpriced_tokens": 0, "modes": ["api"]}
    assert view["totals"]["cost"]["state"] == "partial"
    assert view["totals"]["cost"]["micro"] == 5000 == sum(view["daily"]["cost"])


def test_local_and_free_tier_are_not_billed(store):
    _record(store, billing_mode="local", provider="ollama", model="llama")
    _record(store, billing_mode="free_tier")
    view = _view(store)
    assert _row(view, "ollama", "llama")["cost"]["state"] == "not_billed"
    assert _row(view, "acme", "acme/m1")["cost"]["modes"] == ["free_tier"]
    assert view["totals"]["cost"]["state"] == "not_billed"
    assert view["totals"]["cost"]["micro"] is None


# ── identity ────────────────────────────────────────────────────────────

def test_same_model_through_two_providers_is_two_rows(store):
    _record(store, provider="acme", model="shared/model")
    _record(store, provider="other", model="shared/model")
    view = _view(store)
    assert {(m["provider"], m["model"]) for m in view["models"]} == {
        ("acme", "shared/model"), ("other", "shared/model")}


def test_an_alias_is_counted_once_under_the_resolved_model(store):
    _record(store, requested_model="coding", model="acme/m1")
    _record(store, model="acme/m1")
    view = _view(store)
    assert len(view["models"]) == 1
    row = view["models"][0]
    assert row["requests"] == 2 and row["tokens"]["total"] == 280
    assert row["requested_as"] == {"coding": 1}


# ── inventory ───────────────────────────────────────────────────────────

INVENTORY = [
    {"id": "acme/m1", "provider_id": "acme", "source": "open_webui", "source_display_name": "Acme"},
    {"id": "acme/unused", "provider_id": "acme", "source": "open_webui", "source_display_name": "Acme"},
    {"id": "llama", "source": "ollama", "source_display_name": "Ollama"},
]


def test_inventory_is_kept_apart_from_usage(store):
    _record(store)  # in inventory
    _record(store, model="acme/removed", status="failed", usage={}, measurement="unavailable")
    _record(store, provider="ollama", model="llama", billing_mode="local")
    view = _view(store, inventory=INVENTORY)
    inv = view["inventory"]
    assert inv["available"] == 3
    assert inv["used"] == 3 and inv["used_in_inventory"] == 2
    assert inv["never_used"] == 1
    assert [m["model"] for m in inv["never_used_models"]] == ["acme/unused"]
    assert _row(view, "acme", "acme/removed")["in_inventory"] is False
    assert _row(view, "ollama", "llama")["in_inventory"] is True
    assert len(view["models"]) == 3  # inventory adds no usage rows
    assert any(i["kind"] == "not_in_inventory" and i["model"] == "acme/removed" for i in view["insights"])


def test_an_unreachable_runtime_is_reported_not_called_removed(store):
    _record(store, provider="ollama", model="llama3", billing_mode="local")
    view = _view(store, inventory=INVENTORY[:2],
                 unreachable=[{"source": "ollama", "name": "local", "reason": "unhealthy"}])
    row = _row(view, "ollama", "llama3")
    assert row["runtime_unreachable"] is True
    assert row["in_inventory"] is None
    assert not any(i["kind"] == "not_in_inventory" for i in view["insights"])
    assert view["inventory"]["unreachable"][0]["reason"] == "unhealthy"


def test_without_an_inventory_nothing_is_claimed(store):
    _record(store)
    view = _view(store, inventory=None)
    assert view["inventory"]["available"] is None
    assert view["models"][0]["in_inventory"] is None


def test_byok_sources_join_on_the_provider_id():
    assert model_usage.inventory_key({"id": "m", "source": "byok:work"}) == ("byok-work", "m")
    assert model_usage.inventory_key({"id": "m", "source": "relay"}) == ("ollama", "m")


# ── sources ─────────────────────────────────────────────────────────────

def test_sources_say_when_nothing_is_attributed(store):
    _record(store)
    assert _view(store)["sources"]["attributed"] is False
    _record(store, application_id="daypilot")
    sources = _view(store)["sources"]
    assert sources["attributed"] is True
    assert {s["key"] for s in sources["items"]} == {"daypilot", "unattributed"}


# ── insights ────────────────────────────────────────────────────────────

def test_repeated_failures_need_three_and_half(store):
    for _ in range(2):
        _record(store, status="failed", usage={}, measurement="unavailable", error_category="provider_bad_request")
    assert not any(i["kind"] == "repeated_failures" for i in _view(store)["insights"])
    _record(store, status="failed", usage={}, measurement="unavailable", error_category="provider_bad_request")
    (hit,) = [i for i in _view(store)["insights"] if i["kind"] == "repeated_failures"]
    assert hit["evidence"] == {"failed": 3, "requests": 3, "top_error": "provider_bad_request",
                               "in_inventory": None}


def test_a_failing_removed_model_is_one_insight_not_two(store):
    for _ in range(3):
        _record(store, model="acme/removed", status="failed", usage={}, measurement="unavailable")
    kinds = [i["kind"] for i in _view(store, inventory=INVENTORY)["insights"]]
    assert kinds == ["repeated_failures"]


def test_spike_needs_history_and_a_threefold_day(store):
    for ago in range(6, 1, -1):
        _record(store, days_ago=ago, usage={"input_tokens": 100})
    _record(store, days_ago=1, usage={"input_tokens": 290})
    assert not any(i["kind"] == "spike" for i in _view(store)["insights"])
    _record(store, days_ago=0, usage={"input_tokens": 300})
    (spike,) = [i for i in _view(store)["insights"] if i["kind"] == "spike"]
    assert spike["evidence"]["factor"] == 3.0


# ── capture: failed provider requests ───────────────────────────────────

def _request():
    return SimpleNamespace(
        headers={}, state=SimpleNamespace(request_id="req_1"),
        app=SimpleNamespace(state=SimpleNamespace(provider_registry=None)),
    )


def test_a_failed_provider_request_is_filed_under_that_provider(store):
    context.note_route("openwebui", "openwebui/internal-x")
    capture.record_from_trace(_request(), dict(requested_model="openwebui/internal-x",
                                               resolved_model="openwebui/internal-x",
                                               ok=False, error_category="provider_bad_request"))
    (event,) = store.events()
    assert event["provider"] == "openwebui"
    assert event["execution"] == "provider_api"


def test_a_failed_local_request_stays_local(store):
    capture.record_from_trace(_request(), dict(resolved_model="llama", provider="ollama-local", ok=False))
    (event,) = store.events()
    assert event["provider"] == "ollama"


# ── API ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    from fastapi.testclient import TestClient

    from ollabridge.api.main import create_app
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "API_KEYS", "test-key")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    with TestClient(create_app()) as c:
        yield c


def test_models_endpoint_serves_the_view(client, store):
    _record(store)
    async def fake_collect():
        return INVENTORY, []
    client.app.state.collect_models = fake_collect
    body = client.get("/v1/bi/models", headers={"X-API-Key": "test-key"}).json()
    assert body["totals"]["requests"] == 1
    assert body["inventory"]["available"] == 3
    assert body["models"][0]["in_inventory"] is True
    assert client.get("/v1/bi/models").status_code == 401


def test_models_endpoint_survives_an_inventory_failure(client, store):
    _record(store)
    async def broken():
        raise RuntimeError("down")
    client.app.state.collect_models = broken
    body = client.get("/v1/bi/models", headers={"X-API-Key": "test-key"}).json()
    assert body["inventory"]["available"] is None
    assert body["totals"]["requests"] == 1
