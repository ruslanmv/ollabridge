"""Provider-specific non-secret config (``extra_fields``).

Some sources need more than an API key: watsonx.ai scopes every chat
request to a project id. The catalog declared those fields but nothing
read them, so there was no way to supply one. These cover the storage
rules (metadata, never the key store), the env fallback, and the Sources
API contract the UI renders from.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ollabridge.core import paths
from ollabridge.core.settings import settings
from ollabridge.provider_ops import set_secret
from ollabridge.provider_ops import test_provider as probe_provider
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    ProviderRecord,
    apply_extras,
    extra_fields_for,
    get_extra,
    get_record,
    missing_extras,
    upsert_record,
)

PROJECT_ID = "2762997c-30dd-4b93-ad9f-dc6bbb5a343c"


def _watsonx_record(**kwargs) -> ProviderRecord:
    return ProviderRecord(
        name="watsonx",
        kind="watsonx",
        base_url="https://us-south.ml.cloud.ibm.com",
        **kwargs,
    )


# ── Catalog declarations ────────────────────────────────────


def test_watsonx_declares_a_required_project_id():
    fields = {f.name: f for f in extra_fields_for("watsonx")}
    assert fields["project_id"].required is True
    assert fields["project_id"].env_var == "WATSONX_PROJECT_ID"
    assert fields["space_id"].required is False


def test_providers_without_extra_config_declare_none():
    assert extra_fields_for("openai") == []
    assert extra_fields_for("groq") == []


def test_base_url_carries_the_region():
    """The region lives in base_url — never as a second, divergent field."""
    assert PROVIDER_CATALOG["watsonx"].base_url == "https://us-south.ml.cloud.ibm.com"
    assert "region" not in {f.name for f in extra_fields_for("watsonx")}


# ── apply_extras / get_extra ────────────────────────────────


def test_apply_and_read_back(ollabridge_home):
    rec = _watsonx_record()
    assert apply_extras(rec, {"project_id": PROJECT_ID}) == ["project_id"]
    assert get_extra(rec, "project_id") == PROJECT_ID


def test_values_are_trimmed(ollabridge_home):
    rec = _watsonx_record()
    apply_extras(rec, {"project_id": f"  {PROJECT_ID}  "})
    assert rec.extra == {"project_id": PROJECT_ID}


def test_undeclared_fields_are_ignored(ollabridge_home):
    rec = _watsonx_record()
    apply_extras(rec, {"project_id": PROJECT_ID, "api_key": "sk-leak"})
    assert rec.extra == {"project_id": PROJECT_ID}


def test_blank_value_clears_a_field(ollabridge_home):
    rec = _watsonx_record(extra={"project_id": PROJECT_ID})
    assert apply_extras(rec, {"project_id": ""}) == ["project_id"]
    assert rec.extra == {}


def test_env_var_is_the_fallback(ollabridge_home, monkeypatch):
    monkeypatch.setenv("WATSONX_PROJECT_ID", "from-env")
    assert get_extra(_watsonx_record(), "project_id") == "from-env"


def test_configured_value_wins_over_env(ollabridge_home, monkeypatch):
    monkeypatch.setenv("WATSONX_PROJECT_ID", "from-env")
    rec = _watsonx_record(extra={"project_id": PROJECT_ID})
    assert get_extra(rec, "project_id") == PROJECT_ID


def test_missing_extras_reports_only_required_fields(ollabridge_home):
    assert missing_extras(_watsonx_record()) == ["Project ID"]
    # space_id is optional, so a project id alone is complete.
    assert missing_extras(_watsonx_record(extra={"project_id": PROJECT_ID})) == []


# ── Persistence ─────────────────────────────────────────────


def test_project_id_persists_across_a_reload(ollabridge_home):
    upsert_record(_watsonx_record(extra={"project_id": PROJECT_ID}))
    assert get_record("watsonx").extra == {"project_id": PROJECT_ID}


def test_project_id_lives_in_providers_yaml_not_the_key_store(ollabridge_home):
    set_secret("watsonx", "ibm-key-supersecret")
    upsert_record(_watsonx_record(extra={"project_id": PROJECT_ID}))

    text = paths.providers_file().read_text(encoding="utf-8")
    assert PROJECT_ID in text, "a project id is metadata and belongs in providers.yaml"
    assert "ibm-key-supersecret" not in text


# ── Credential probe ────────────────────────────────────────


def _iam_ok(url, data=None, headers=None, timeout=None):
    return httpx.Response(
        200,
        json={"access_token": "iam-token-1", "expires_in": 3600},
        request=httpx.Request("POST", url),
    )


def _models_ok(url, headers=None, timeout=None):
    return httpx.Response(200, text="{}", request=httpx.Request("GET", url))


def test_probe_exchanges_the_api_key_for_an_iam_token(ollabridge_home):
    """watsonx rejects the raw IBM Cloud key as a bearer token."""
    set_secret("watsonx", "ibm-key")
    upsert_record(_watsonx_record(extra={"project_id": PROJECT_ID}))

    with patch("httpx.post", side_effect=_iam_ok) as post, \
            patch("httpx.get", side_effect=_models_ok) as get:
        ok, detail = probe_provider("watsonx")

    assert ok is True, detail
    assert post.call_args.args[0] == "https://iam.cloud.ibm.com/identity/token"
    assert post.call_args.kwargs["data"]["apikey"] == "ibm-key"
    # The models call carries the IAM token, not the API key.
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer iam-token-1"


def _iam_denied(url, data=None, headers=None, timeout=None):
    return httpx.Response(
        400, json={"errorCode": "BXNIM0415E"}, request=httpx.Request("POST", url)
    )


def test_probe_reports_a_rejected_ibm_key_clearly(ollabridge_home):
    set_secret("watsonx", "bad-key")
    upsert_record(_watsonx_record(extra={"project_id": PROJECT_ID}))

    with patch("httpx.post", side_effect=_iam_denied):
        ok, detail = probe_provider("watsonx")

    assert ok is False
    assert "IAM" in detail


def test_a_rejected_ibm_key_is_recorded_on_the_source(ollabridge_home):
    """An IAM rejection must be stamped, or the card keeps saying Connected."""
    set_secret("watsonx", "bad-key")
    upsert_record(_watsonx_record(extra={"project_id": PROJECT_ID}))

    with patch("httpx.post", side_effect=_iam_denied):
        probe_provider("watsonx")

    rec = get_record("watsonx")
    assert rec.last_test_ok is False
    assert rec.last_test_at is not None


def test_probe_fails_when_the_project_id_is_missing(ollabridge_home):
    """A valid key is not a usable source without the project id."""
    set_secret("watsonx", "ibm-key")
    upsert_record(_watsonx_record())

    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        ok, detail = probe_provider("watsonx")

    assert ok is False
    assert "Project ID" in detail
    assert "key valid" in detail, "the key outcome should still be reported"


# ── Sources API ─────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.sources_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-key-abc"}


def test_catalog_advertises_the_fields_a_source_needs(client):
    body = client.get("/admin/sources", headers=AUTH).json()
    watsonx = next(s for s in body["available"] if s["name"] == "watsonx")
    fields = {f["name"]: f for f in watsonx["extra_fields"]}
    assert fields["project_id"]["required"] is True
    assert fields["project_id"]["label"] == "Project ID"


def test_upsert_saves_the_project_id(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        r = client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"api_key": "ibm-key", "extra": {"project_id": PROJECT_ID}},
        )
    assert r.status_code == 200
    assert r.json()["source"]["extra"]["project_id"] == PROJECT_ID
    assert get_record("watsonx").extra["project_id"] == PROJECT_ID


def test_upsert_can_add_a_project_id_without_resending_the_key(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        client.post(
            "/admin/sources/watsonx", headers=AUTH, json={"api_key": "ibm-key"}
        )
        r = client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"extra": {"project_id": PROJECT_ID}},
        )
    assert r.status_code == 200
    body = r.json()["source"]
    assert body["key_configured"] is True
    assert body["extra"]["project_id"] == PROJECT_ID


def test_source_view_flags_an_incomplete_configuration(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        r = client.post(
            "/admin/sources/watsonx", headers=AUTH, json={"api_key": "ibm-key"}
        )
    body = r.json()["source"]
    assert body["missing_config"] == ["Project ID"]
    assert body["status"] == "missing_config"


def test_source_view_is_connected_once_fully_configured(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        r = client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"api_key": "ibm-key", "extra": {"project_id": PROJECT_ID}},
        )
    body = r.json()["source"]
    assert body["missing_config"] == []
    assert body["status"] == "connected"


def test_source_view_never_echoes_the_key(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        r = client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"api_key": "ibm-key-supersecret", "extra": {"project_id": PROJECT_ID}},
        )
    assert "ibm-key-supersecret" not in r.text


def test_extra_fields_carry_current_values_for_the_form(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"api_key": "ibm-key", "extra": {"project_id": PROJECT_ID}},
        )
    body = client.get("/admin/sources/watsonx", headers=AUTH).json()
    fields = {f["name"]: f for f in body["extra_fields"]}
    assert fields["project_id"]["value"] == PROJECT_ID
    assert fields["space_id"]["value"] == ""


def test_undeclared_extra_keys_are_rejected_silently(client):
    with patch("httpx.post", side_effect=_iam_ok), \
            patch("httpx.get", side_effect=_models_ok):
        r = client.post(
            "/admin/sources/watsonx",
            headers=AUTH,
            json={"api_key": "ibm-key", "extra": {"storage_mode": "organization_vault"}},
        )
    assert r.status_code == 200
    rec = get_record("watsonx")
    assert rec.extra == {}
    assert rec.storage_mode == "local_only", "extra must not reach real fields"
