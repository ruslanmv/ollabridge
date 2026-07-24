"""CloudBridgeManager publishes ONLY the admin-approved cloud manifest.

Regression: `_discover_models` used to advertise every model returned by the
local gateway's `/v1/models`, and fall back to *all* Ollama models on error.
That leaked private local models to OllaBridge Cloud. It must now fail closed
and publish only models flagged ``enabled AND visible_cloud``.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.cloud.bridge_manager import BridgeState, CloudBridgeManager


def _manifest_response(models):
    req = httpx.Request("GET", "http://127.0.0.1:11435/admin/model-access/manifest/cloud")
    return httpx.Response(200, json={"models": models, "count": len(models)}, request=req)


class _FakeAsyncClient:
    """Minimal async httpx client stub driven by a response factory."""

    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return self._handler(url)


@pytest.mark.asyncio
async def test_discover_publishes_only_approved_models(monkeypatch):
    mgr = CloudBridgeManager()

    def handler(url):
        assert url.endswith("/admin/model-access/manifest/cloud")
        return _manifest_response([
            {"model_id": "llama3.1:latest", "source_id": "ollama",
             "allowed_apps": ["yourfriend.online"], "allow_routing": False},
        ])

    monkeypatch.setattr(
        "ollabridge.cloud.bridge_manager.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(handler),
    )

    models = await mgr._discover_models()
    assert models == ["llama3.1:latest"]

    manifest = await mgr._fetch_cloud_manifest()
    assert manifest[0]["allowed_apps"] == ["yourfriend.online"]


@pytest.mark.asyncio
async def test_discover_fails_closed_on_error(monkeypatch):
    """Manifest endpoint errors → publish NOTHING (no all-Ollama fallback)."""
    mgr = CloudBridgeManager()

    def handler(url):
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr(
        "ollabridge.cloud.bridge_manager.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(handler),
    )

    assert await mgr._discover_models() == []


@pytest.mark.asyncio
async def test_refresh_models_now_noop_when_disconnected(monkeypatch):
    mgr = CloudBridgeManager()
    mgr.status.state = BridgeState.DISCONNECTED
    mgr.status.models_shared = ["prev"]
    # No ws attached → returns current shared list without raising.
    assert await mgr.refresh_models_now() == ["prev"]
