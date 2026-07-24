"""Per-model access: the layer that separates a configured source from where
each model is visible. Local Ollama defaults to cloud-shared; other
sources remain private unless visible_cloud is enabled.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ollabridge import model_access as ma
from ollabridge.core.settings import settings


def test_default_ollama_access_is_local_and_cloud(ollabridge_home):
    rec = ma.get("ollama", "qwen2.5:0.5b")
    assert rec.visible_local is True
    assert rec.visible_cloud is True
    assert rec.visible_lan is False
    assert rec.allowed_apps == []
    assert rec.allow_routing is False


def test_default_external_source_access_is_cloud_private(ollabridge_home):
    rec = ma.get("watsonx", "granite")
    assert rec.visible_local is True
    assert rec.visible_cloud is False


def test_set_and_persist_access(ollabridge_home):
    ma.set_access(
        "ollama", "qwen2.5:0.5b", visible_cloud=True, allowed_apps=["yourfriend.online"]
    )
    rec = ma.get("ollama", "qwen2.5:0.5b")
    assert rec.visible_cloud is True
    assert rec.allowed_apps == ["yourfriend.online"]
    # local default untouched
    assert rec.visible_local is True


def test_partial_update_keeps_other_flags(ollabridge_home):
    ma.set_access("ollama", "m", visible_cloud=True, allow_routing=True)
    ma.set_access("ollama", "m", visible_cloud=False)  # only flip cloud
    rec = ma.get("ollama", "m")
    assert rec.visible_cloud is False
    assert rec.allow_routing is True


def test_access_file_never_holds_secrets(ollabridge_home):
    ma.set_access("watsonx", "granite-3-8b", visible_cloud=True)
    text = (ollabridge_home / "model_access.yaml").read_text()
    assert "key" not in text.lower() or "api_key" not in text
    assert "metadata only" in text


def test_cloud_manifest_filters_by_visible_cloud(ollabridge_home):
    ma.set_access(
        "ollama", "shared", visible_cloud=True, allowed_apps=["yourfriend.online"]
    )
    ma.set_access("ollama", "private", visible_cloud=False)
    inventory = [
        ("ollama", "Ollama on this PC", "shared"),
        ("ollama", "Ollama on this PC", "private"),
        ("ollama", "Ollama on this PC", "neverset"),
    ]
    manifest = ma.cloud_manifest(inventory)
    ids = [m["model_id"] for m in manifest]
    assert ids == ["shared", "neverset"]  # unset Ollama models share by default
    assert manifest[0]["allowed_apps"] == ["yourfriend.online"]
    assert manifest[0]["requires_device_online"] is True


def test_remove_source_drops_its_access(ollabridge_home):
    ma.set_access("ollama", "a", visible_cloud=True)
    ma.set_access("watsonx", "b", visible_cloud=True)
    removed = ma.remove_source("ollama")
    assert removed == 1
    assert ma.cloud_manifest([("watsonx", "IBM watsonx.ai", "b")])[0]["model_id"] == "b"


# ── API ──────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "k")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("AUTH_MODE", "required")
    from ollabridge.api.model_access_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer k"}


def _fake_tags(url, timeout=None):
    return httpx.Response(
        200,
        json={"models": [{"name": "qwen2.5:0.5b"}, {"name": "llama3.1:8b"}]},
        request=httpx.Request("GET", url),
    )


def test_api_lists_inventory_with_access(client, ollabridge_home):
    with patch("ollabridge.api.model_access_routes.httpx.get", _fake_tags):
        r = client.get("/admin/model-access", headers=AUTH)
    assert r.status_code == 200
    sources = r.json()["sources"]
    assert sources[0]["source_id"] == "ollama"
    models = {m["model_id"]: m for m in sources[0]["models"]}
    assert models["qwen2.5:0.5b"]["visible_local"] is True
    assert models["qwen2.5:0.5b"]["visible_cloud"] is True


def test_api_set_then_manifest(client, ollabridge_home):
    with patch("ollabridge.api.model_access_routes.httpx.get", _fake_tags):
        r = client.post(
            "/admin/model-access/ollama/qwen2.5:0.5b",
            headers=AUTH,
            json={"visible_cloud": True, "allowed_apps": ["yourfriend.online"]},
        )
        assert r.status_code == 200 and r.json()["visible_cloud"] is True
        m = client.get("/admin/model-access/manifest/cloud", headers=AUTH).json()
    assert m["count"] == 2
    models = {item["model_id"]: item for item in m["models"]}
    assert models["qwen2.5:0.5b"]["allowed_apps"] == ["yourfriend.online"]
    assert models["llama3.1:8b"]["allowed_apps"] == []


def test_api_requires_auth(client):
    assert client.get("/admin/model-access").status_code == 401
