"""Generic External Sources API (/admin/sources/*).

Covers the contract behind the Sources tab: add any provider with one
pattern, safe defaults (local-only / private / routing-off), key encrypted
and never echoed, test/rotate/remove, and the catalog of not-yet-configured
sources.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ollabridge.core.settings import settings


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


def _ok_get(url, headers=None, timeout=None):
    return httpx.Response(200, text="{}", request=httpx.Request("GET", url))


def test_list_shows_catalog_when_nothing_configured(client):
    r = client.get("/admin/sources", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] == []
    names = {s["name"] for s in body["available"]}
    assert {"openai", "anthropic", "gemini", "groq", "custom"} <= names


def test_requires_auth(client):
    assert client.get("/admin/sources").status_code == 401


def test_add_source_safe_defaults_and_redaction(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/openai",
            headers=AUTH,
            json={
                "api_key": "sk-supersecretvalue1234567890",
                "display_name": "Personal OpenAI",
            },
        )
    assert r.status_code == 200, r.text
    src = r.json()["source"]
    assert src["storage_mode"] == "local_only"
    assert src["sharing"] == "private"
    assert src["allow_routing"] is False
    assert "supersecret" not in r.text
    assert src["key_configured"] is True
    assert src["key"].startswith("sk-s")
    assert r.json()["test"]["ok"] is True
    assert src["status"] == "connected"


def test_unknown_source_rejected(client):
    r = client.post("/admin/sources/fakeai", headers=AUTH, json={"api_key": "x"})
    assert r.status_code == 404


def test_custom_requires_base_url(client):
    r = client.post(
        "/admin/sources/custom", headers=AUTH, json={"api_key": "k12345678"}
    )
    assert r.status_code == 422
    assert "base_url" in r.text


def test_open_webui_requires_base_url(client):
    # The Open WebUI-compatible source cannot be saved without its server URL —
    # enforced server-side so the frontend rule cannot be bypassed.
    r = client.post(
        "/admin/sources/open_webui", headers=AUTH, json={"api_key": "sk-12345678"}
    )
    assert r.status_code == 422
    assert "base_url" in r.text


def _openwebui_catalog(_req):
    return httpx.Response(200, json={"data": [
        {"id": "llama", "name": "Llama", "connection_type": "local", "tags": [{"name": "internal"}]},
        {"id": "gpt", "name": "GPT", "connection_type": "external", "tags": ["legal"]},
        {"id": "img", "name": "Image", "connection_type": "external",
         "tags": [{"name": "image"}], "pipe": {"type": "img"}},
    ]})


def _patch_openwebui_upstream(monkeypatch):
    """Route the adapter's async client through a MockTransport catalog."""
    from ollabridge.addons.providers.adapters import open_webui as ow_mod

    real = ow_mod.httpx.AsyncClient
    transport = httpx.MockTransport(_openwebui_catalog)

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(ow_mod.httpx, "AsyncClient", _patched)


def test_open_webui_upsert_returns_discovery_and_models_filter(client, monkeypatch):
    _patch_openwebui_upstream(monkeypatch)
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/open_webui",
            headers=AUTH,
            json={"api_key": "sk-owkey123456", "base_url": "https://h.example/api"},
        )
    assert r.status_code == 200, r.text
    disc = r.json()["discovery"]
    assert disc["count"] == 3
    assert disc["connection_types"] == {"local": 1, "external": 2}
    assert disc["persona_compatible"] == 2  # the image pipe is excluded
    assert "sk-owkey" not in r.text  # key never echoed

    # Filters return live, normalized data — not an empty/fake list.
    all_models = client.get("/admin/sources/open_webui/models", headers=AUTH).json()
    assert {m["upstream_model_id"] for m in all_models["models"]} == {"llama", "gpt", "img"}
    local = client.get("/admin/sources/open_webui/models?connection_type=local", headers=AUTH).json()
    assert {m["upstream_model_id"] for m in local["models"]} == {"llama"}
    legal = client.get("/admin/sources/open_webui/models?tag=legal", headers=AUTH).json()
    assert {m["upstream_model_id"] for m in legal["models"]} == {"gpt"}
    persona = client.get("/admin/sources/open_webui/models?persona_compatible=true", headers=AUTH).json()
    assert {m["upstream_model_id"] for m in persona["models"]} == {"llama", "gpt"}


#: A Groq-shaped ``/openai/v1/models`` listing: chat models plus the non-chat
#: ones Groq reports in the same payload.
_CATALOG_MODELS = [
    {"id": "openai/gpt-oss-20b", "object": "model", "owned_by": "OpenAI"},
    {"id": "openai/gpt-oss-120b", "object": "model", "owned_by": "OpenAI"},
    {"id": "some-vendor/paid-model", "object": "model", "owned_by": "Vendor"},
    {"id": "whisper-large-v3", "object": "model", "owned_by": "OpenAI"},
]


def _groq_catalog(_req):
    return httpx.Response(200, json={"data": _CATALOG_MODELS})


def _patch_openai_compatible_upstream(monkeypatch, handler=_groq_catalog):
    """Route every OpenAI-compatible adapter's async client at a mock upstream."""
    from ollabridge.addons.providers.adapters import openai_compatible as oc_mod

    real = oc_mod.httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(oc_mod.httpx, "AsyncClient", _patched)


def test_models_endpoint_rejects_source_that_cannot_discover(client, monkeypatch):
    """Anthropic does not speak an OpenAI-style listing, so discovery is refused
    rather than attempted and failed."""
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/anthropic", headers=AUTH, json={"api_key": "sk-ant-key12345"}
        )
    r = client.get("/admin/sources/anthropic/models", headers=AUTH)
    assert r.status_code == 400 and "discovery" in r.text


def test_groq_discovers_live_models_and_flags_free_ones(client, monkeypatch):
    _patch_openai_compatible_upstream(monkeypatch)
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/groq", headers=AUTH, json={"api_key": "gsk_key1234567890"}
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["discovery"]["count"] == 4
    assert body["discovery"]["free"] == 2  # only the gpt-oss pair is free-tier
    assert "gsk_key" not in r.text  # key never echoed

    listing = client.get("/admin/sources/groq/models", headers=AUTH).json()
    assert {m["id"] for m in listing["models"]} == {
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "some-vendor/paid-model",
        "whisper-large-v3",
    }
    # A transcription model is discovered but never offered as a chat default.
    by_id = {m["id"]: m for m in listing["models"]}
    assert by_id["whisper-large-v3"]["category"] == "audio"
    assert by_id["openai/gpt-oss-20b"]["free"] is True
    assert by_id["some-vendor/paid-model"]["free"] is False

    free_only = client.get("/admin/sources/groq/models?free=true", headers=AUTH).json()
    assert {m["id"] for m in free_only["models"]} == {
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
    }


def test_source_defaults_to_a_free_model(client, monkeypatch):
    """A source saved without a model gets the preferred free one, not blank."""
    _patch_openai_compatible_upstream(monkeypatch)
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/groq", headers=AUTH, json={"api_key": "gsk_key1234567890"}
        )
    assert r.json()["source"]["default_model"] == "openai/gpt-oss-20b"


def test_a_settings_toggle_does_not_call_the_provider(client, monkeypatch):
    """Discovery is a round-trip upstream, so it runs when the credential
    changed or a default model is still needed — not on every checkbox."""
    calls: list[str] = []

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": _CATALOG_MODELS})

    _patch_openai_compatible_upstream(monkeypatch, counting)
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/groq", headers=AUTH, json={"api_key": "gsk_key1234567890"}
        )
        assert len(calls) == 1  # the key was new, so the catalog was fetched

        r = client.post("/admin/sources/groq", headers=AUTH, json={"allow_routing": True})
    assert r.json()["source"]["allow_routing"] is True
    assert len(calls) == 1  # unchanged: no second round-trip for a toggle


def test_explicit_default_model_is_never_overridden(client, monkeypatch):
    _patch_openai_compatible_upstream(monkeypatch)
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/groq",
            headers=AUTH,
            json={"api_key": "gsk_key1234567890", "default_model": "openai/gpt-oss-120b"},
        )
    assert r.json()["source"]["default_model"] == "openai/gpt-oss-120b"


def test_update_toggles_without_touching_key(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/groq", headers=AUTH, json={"api_key": "gsk_key1234567890"}
        )
        r = client.post(
            "/admin/sources/groq",
            headers=AUTH,
            json={
                "allow_routing": True,
                "sharing": "workspace",
                "default_model": "openai/gpt-oss-120b",
            },
        )
    src = r.json()["source"]
    assert src["allow_routing"] is True
    assert src["sharing"] == "workspace"
    assert src["default_model"] == "openai/gpt-oss-120b"
    assert src["key_configured"] is True


def test_test_endpoint(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/gemini", headers=AUTH, json={"api_key": "AIzakey1234567890"}
        )
        r = client.post("/admin/sources/gemini/test", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_rotate_requires_key_and_restamps(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/deepseek",
            headers=AUTH,
            json={"api_key": "sk-old1234567890"},
        )
        assert (
            client.post(
                "/admin/sources/deepseek/rotate", headers=AUTH, json={}
            ).status_code
            == 422
        )
        r = client.post(
            "/admin/sources/deepseek/rotate",
            headers=AUTH,
            json={"api_key": "sk-new1234567890"},
        )
    assert r.status_code == 200
    assert r.json()["source"]["rotated_at"]
    assert "sk-new" not in r.text


def test_delete_removes_source_and_key(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/mistral", headers=AUTH, json={"api_key": "key1234567890"}
        )
    r = client.delete("/admin/sources/mistral", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True
    body = client.get("/admin/sources", headers=AUTH).json()
    assert "mistral" not in {s["name"] for s in body["configured"]}
    assert client.delete("/admin/sources/mistral", headers=AUTH).status_code == 404


def test_missing_key_status(client):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        client.post(
            "/admin/sources/openrouter",
            headers=AUTH,
            json={"api_key": "sk-or-key1234567890"},
        )
    from ollabridge.provider_ops import delete_secret

    delete_secret("openrouter")
    src = client.get("/admin/sources/openrouter", headers=AUTH).json()
    assert src["status"] == "missing_key"
    assert src["key_configured"] is False
