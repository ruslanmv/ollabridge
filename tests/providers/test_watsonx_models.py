"""watsonx.ai model discovery and default selection.

The settings form used to ship ``ibm/granite-3-8b-instruct`` as the default.
That is wrong for anyone whose account does not carry it — the watsonx
foundation-model catalog is per region, per plan and per account — and it
goes stale as IBM revises the Granite generations.

These tests pin the replacement: ask the account what it can run, keep only
the live chat models, and rank the answer by family so no exact model id is
hard-coded anywhere in application code.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers import model_defaults
from ollabridge.addons.providers.adapters.watsonx import (
    CHAT_MODELS_FILTER,
    WATSONX_API_VERSION,
    WatsonxAdapter,
)
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
)
from ollabridge.addons.providers.services import dynamic_source_sync as dss
from ollabridge.providers_meta import ProviderRecord

BASE = "https://us-south.ml.cloud.ibm.com"

#: A foundation_model_specs page shaped like the real one: a couple of
#: Granite generations, a third-party chat model, a deprecated model, an
#: embedding model and a safety guard.
CATALOG = {
    "resources": [
        {
            "model_id": "ibm/granite-3-8b-instruct",
            "label": "granite-3-8b-instruct",
            "provider": "IBM",
            "short_description": "Granite 3 instruct",
            "model_limits": {"max_sequence_length": 8192},
            "lifecycle": [{"id": "deprecated", "start_date": "2026-06-01"}],
        },
        {
            "model_id": "ibm/granite-4-h-small",
            "label": "granite-4-h-small",
            "provider": "IBM",
            "model_limits": {"max_sequence_length": 131072},
            "lifecycle": [{"id": "available"}],
        },
        {
            "model_id": "mistralai/mistral-large",
            "label": "mistral-large",
            "provider": "Mistral AI",
            "lifecycle": [{"id": "available"}],
        },
        {
            "model_id": "ibm/slate-125m-english-rtrvr-embedding",
            "label": "slate embedding",
            "provider": "IBM",
        },
        {
            "model_id": "ibm/granite-guardian-3-8b",
            "label": "granite guardian",
            "provider": "IBM",
        },
    ]
}


def _iam_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "iam-tok", "expires_in": 3600})


def _adapter(monkeypatch, handler, **kwargs) -> WatsonxAdapter:
    """A watsonx adapter whose IAM exchange succeeds and whose watsonx calls
    go to ``handler``."""
    from ollabridge.addons.providers.adapters import watsonx as wx

    real = wx.httpx.AsyncClient

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "iam.cloud.ibm.com":
            return _iam_ok(request)
        return handler(request)

    transport = httpx.MockTransport(route)

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(wx.httpx, "AsyncClient", _patched)
    kwargs.setdefault("api_key", "ibm-cloud-key")
    return WatsonxAdapter(base_url=BASE, **kwargs)


# ── The catalog request ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_listing_asks_for_chat_models_with_the_iam_token(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=CATALOG)

    adapter = _adapter(monkeypatch, handler)
    await adapter.list_models()

    assert seen["url"].startswith(f"{BASE}/ml/v1/foundation_model_specs?")
    assert f"version={WATSONX_API_VERSION}" in seen["url"]
    # Only chat models can serve /ml/v1/text/chat, so the catalog is filtered
    # upstream rather than guessed at from the ids.
    assert f"filters={CHAT_MODELS_FILTER}" in seen["url"]
    # The IBM Cloud API key is never sent as a bearer token — the IAM token is.
    assert seen["auth"] == "Bearer iam-tok"


@pytest.mark.asyncio
async def test_listing_keeps_the_label_provider_and_lifecycle(monkeypatch):
    adapter = _adapter(monkeypatch, lambda _r: httpx.Response(200, json=CATALOG))
    by_id = {m["id"]: m for m in await adapter.list_models()}

    assert by_id["ibm/granite-4-h-small"]["name"] == "granite-4-h-small"
    assert by_id["ibm/granite-4-h-small"]["owned_by"] == "IBM"
    assert by_id["ibm/granite-4-h-small"]["context_window"] == 131072
    assert by_id["ibm/granite-4-h-small"]["deprecated"] is False
    assert by_id["ibm/granite-3-8b-instruct"]["deprecated"] is True
    assert by_id["ibm/granite-3-8b-instruct"]["lifecycle"] == ["deprecated"]


@pytest.mark.asyncio
async def test_listing_follows_pagination_and_dedupes(monkeypatch):
    pages = [
        {
            "resources": [{"model_id": "ibm/granite-4-h-small"}],
            "next": {"start": "cursor-2"},
        },
        {
            "resources": [
                {"model_id": "ibm/granite-4-h-small"},  # repeat across pages
                {"model_id": "mistralai/mistral-large"},
            ]
        },
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=pages[min(len(calls) - 1, 1)])

    adapter = _adapter(monkeypatch, handler)
    models = await adapter.list_models()

    assert len(calls) == 2
    assert "start=cursor-2" in calls[1]
    assert [m["id"] for m in models] == [
        "ibm/granite-4-h-small",
        "mistralai/mistral-large",
    ]


@pytest.mark.asyncio
async def test_a_next_href_is_accepted_as_well_as_a_start_cursor(monkeypatch):
    pages = [
        {
            "resources": [{"model_id": "a"}],
            "next": {"href": "/ml/v1/foundation_model_specs?version=x&start=cur%2F2"},
        },
        {"resources": [{"model_id": "b"}]},
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=pages[min(len(calls) - 1, 1)])

    adapter = _adapter(monkeypatch, handler)
    assert [m["id"] for m in await adapter.list_models()] == ["a", "b"]
    assert "start=cur%2F2" in calls[1]


# ── Errors ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_rejected_ibm_cloud_key_is_an_auth_error(monkeypatch):
    from ollabridge.addons.providers.adapters import watsonx as wx

    real = wx.httpx.AsyncClient
    # IAM answers a bad API key with a 400, which is still "your key is wrong".
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(400, text="Provided API key could not be found")
    )

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(wx.httpx, "AsyncClient", _patched)
    with pytest.raises(ProviderAuthError):
        await WatsonxAdapter(base_url=BASE, api_key="bad").list_models()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [(403, ProviderAuthError), (429, ProviderQuotaExceeded), (404, ProviderBadRequest)],
)
async def test_catalog_errors_map_to_routing_aware_exceptions(
    monkeypatch, status, expected
):
    adapter = _adapter(monkeypatch, lambda _r: httpx.Response(status, text="nope"))
    with pytest.raises(expected):
        await adapter.list_models()


@pytest.mark.asyncio
async def test_errors_never_leak_the_key_or_the_iam_token(monkeypatch):
    adapter = _adapter(
        monkeypatch,
        lambda _r: httpx.Response(400, text="bad ibm-cloud-key and iam-tok"),
        api_key="ibm-cloud-key",
    )
    with pytest.raises(ProviderBadRequest) as exc:
        await adapter.list_models()
    assert "ibm-cloud-key" not in str(exc.value)
    assert "iam-tok" not in str(exc.value)


@pytest.mark.asyncio
async def test_chat_without_a_project_id_fails_clearly(monkeypatch):
    monkeypatch.delenv("WATSONX_PROJECT_ID", raising=False)
    monkeypatch.delenv("WATSONX_SPACE_ID", raising=False)
    adapter = _adapter(monkeypatch, lambda _r: httpx.Response(200, json={}))
    with pytest.raises(ProviderBadRequest) as exc:
        await adapter.chat("ibm/granite-4-h-small", [{"role": "user", "content": "hi"}])
    assert "project id" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_chat_scopes_the_request_to_the_project(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen["url"] = str(request.url)
        seen["body"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]},
        )

    adapter = _adapter(monkeypatch, handler, project_id="proj-123")
    out = await adapter.chat("ibm/granite-4-h-small", [{"role": "user", "content": "yo"}])

    assert seen["url"] == f"{BASE}/ml/v1/text/chat?version={WATSONX_API_VERSION}"
    assert seen["body"]["project_id"] == "proj-123"
    assert seen["body"]["model_id"] == "ibm/granite-4-h-small"
    assert out["choices"][0]["message"]["content"] == "hi"


def test_a_project_id_wins_over_a_space_id():
    both = WatsonxAdapter(base_url=BASE, api_key="k", project_id="p", space_id="s")
    assert both._scope() == ("project_id", "p")
    assert WatsonxAdapter(base_url=BASE, api_key="k", space_id="s")._scope() == (
        "space_id",
        "s",
    )


# ── Default selection ────────────────────────────────────────────────


def _normalized() -> list[dict]:
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    raw = [
        WatsonxAdapter._normalize_spec(str(s["model_id"]), s)
        for s in CATALOG["resources"]
    ]
    return dss.normalize_models(rec, raw)


def test_the_default_is_the_best_live_chat_model_the_account_can_run():
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    # Granite 4 beats Granite 3 (more specific prefix), and beats Mistral
    # (earlier in the preference order). The deprecated Granite 3 is skipped
    # even though it matches a preference prefix.
    assert dss.default_model_for(rec, _normalized()) == "ibm/granite-4-h-small"


def test_the_default_never_picks_an_embedding_or_guard_model():
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    by_id = {m["id"]: m for m in _normalized()}
    assert by_id["ibm/slate-125m-english-rtrvr-embedding"]["category"] == "embedding"
    assert by_id["ibm/granite-guardian-3-8b"]["category"] == "guard"

    only_non_chat = [
        m for m in _normalized() if m["category"] in ("embedding", "guard")
    ]
    assert dss.default_model_for(rec, only_non_chat) == ""


def test_the_default_falls_back_to_the_next_family_when_granite_is_absent():
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    no_granite = [m for m in _normalized() if not m["id"].startswith("ibm/granite")]
    assert dss.default_model_for(rec, no_granite) == "mistralai/mistral-large"


def test_an_account_with_no_preferred_family_gets_no_default():
    """Better an empty field the user fills in than a model that 404s."""
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    models = dss.normalize_models(rec, [{"id": "some-vendor/unknown-model"}])
    assert dss.default_model_for(rec, models) == ""


def test_watsonx_has_no_free_models():
    """Every watsonx foundation model is billed, so none is ever badged free."""
    assert model_defaults.free_models("watsonx") == []
    assert not model_defaults.is_free("watsonx", "ibm/granite-4-h-small")
    assert all(m["free"] is False for m in _normalized())


def test_nothing_is_suggested_before_the_account_has_been_asked():
    """The old UI shipped ibm/granite-3-8b-instruct as a placeholder. There is
    no honest fixed suggestion for a per-account catalog, so there is none."""
    assert model_defaults.suggested_models("watsonx") == []
    assert model_defaults.preferred_default("watsonx") == ""


def test_the_preference_order_is_by_family_not_by_exact_id():
    """A Granite revision nobody has heard of still ranks as Granite."""
    rec = ProviderRecord(name="watsonx", kind="watsonx")
    future = dss.normalize_models(
        rec, [{"id": "ibm/granite-9-ultra-instruct"}, {"id": "meta-llama/llama-3-70b"}]
    )
    assert dss.default_model_for(rec, future) == "ibm/granite-9-ultra-instruct"


# ── Wiring ───────────────────────────────────────────────────────────


def test_discovery_builds_a_watsonx_adapter_carrying_the_project_id():
    rec = ProviderRecord(
        name="watsonx", kind="watsonx", base_url=BASE, extra={"project_id": "proj-9"}
    )
    adapter = dss.build_adapter(rec, "ibm-cloud-key")
    assert isinstance(adapter, WatsonxAdapter)
    assert adapter.project_id == "proj-9"
    assert adapter.api_key == "ibm-cloud-key"


def test_discovery_works_before_a_project_id_has_been_entered():
    """Listing the catalog needs only the key. If discovery required the
    project id too, the form could never offer a model list while the user
    was still filling it in."""
    rec = ProviderRecord(name="watsonx", kind="watsonx", base_url=BASE)
    adapter = dss.build_adapter(rec, "ibm-cloud-key")
    assert isinstance(adapter, WatsonxAdapter)
    assert adapter.is_configured is False  # chat would still refuse


def test_discovery_falls_back_to_the_catalog_base_url():
    rec = ProviderRecord(name="watsonx", kind="watsonx", base_url="")
    adapter = dss.build_adapter(rec, "k")
    assert isinstance(adapter, WatsonxAdapter)
    assert adapter._models_url().startswith(BASE)
