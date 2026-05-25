"""Integration tests for the /admin/providers REST API."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFTask,
    SnapshotEntry,
    SyncResult,
)
from ollabridge.addons.providers.hf_catalog.snapshot import CatalogSnapshot
from ollabridge.addons.providers.models import (
    AliasCandidate,
    HealthStatus,
    ProviderCategory,
    ProviderConfig,
    ProviderState,
    ProviderTier,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter
from ollabridge.addons.providers.secret_store import SecretStore


class _FakeAdapter:
    def __init__(self):
        self.api_key: str | None = None
        self.bill_to: str | None = None

    async def chat(self, model, messages, **kwargs):
        return {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "pong"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": model,
        }


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.setenv("AUTH_MODE", "required")

    import importlib

    from ollabridge.core import settings as settings_mod

    importlib.reload(settings_mod)

    # Build a real FastAPI app with just the providers router mounted, so we
    # don't drag in the whole gateway startup (DB, relay, cloud bridge, etc).
    application = FastAPI()

    registry = ProviderRegistry()
    config = ProviderConfig(
        id="huggingface-free",
        name="HF",
        kind="huggingface",
        enabled=True,
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE_FLEX,
        base_url="https://router.huggingface.co",
    )
    adapter = _FakeAdapter()
    # ProviderRegistry.register is async — call via sync wrapper for the fixture.
    import asyncio
    asyncio.get_event_loop().run_until_complete(registry.register(config, adapter))
    registry.set_aliases({
        "ollabridge:tools": [AliasCandidate(provider="huggingface-free", model="m/x:groq")],
    })
    # Force the state to healthy so the router considers it available.
    asyncio.get_event_loop().run_until_complete(
        registry.update_health("huggingface-free", HealthStatus.HEALTHY)
    )

    prouter = ProviderRouter(registry)
    application.state.provider_registry = registry
    application.state.provider_router = prouter
    application.state.secret_store = SecretStore(
        path=tmp_path / "secrets.enc", secret="test"
    )

    snapshot = CatalogSnapshot(path=tmp_path / "snap.yaml")
    snapshot._entries["x/a:groq"] = SnapshotEntry(
        router_model_id="x/a:groq", model_id="x/a", hf_provider="groq",
        task=HFTask.CHAT_COMPLETION, rank=1, score=0.9,
        supports_tools=True, supports_structured_output=True,
        input_price_per_1m=0.0, output_price_per_1m=0.0,
    )
    snapshot._entries["x/v:novita"] = SnapshotEntry(
        router_model_id="x/v:novita", model_id="x/v", hf_provider="novita",
        task=HFTask.VLM, rank=2, score=0.7,
    )

    application.state.hf_catalog_snapshot = snapshot

    fake_sync = AsyncMock()
    fake_sync.last_result = SyncResult(
        started_at=dt.datetime.now(dt.timezone.utc),
        finished_at=dt.datetime.now(dt.timezone.utc),
        fetched=2, upserted=2,
    )
    fake_sync.run = AsyncMock(return_value=fake_sync.last_result)

    class _FakeClient:
        token = None

    fake_sync.client = _FakeClient()
    application.state.hf_catalog_sync = fake_sync

    from ollabridge.api.providers_routes import router as providers_router
    application.include_router(providers_router)

    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def _h():
    return {"X-API-Key": "test-key"}


def test_list_providers(client):
    r = client.get("/admin/providers", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["providers"][0]["id"] == "huggingface-free"
    assert body["providers"][0]["state"]["health"] == "healthy"


def test_list_aliases(client):
    r = client.get("/admin/providers/aliases", headers=_h())
    assert r.status_code == 200
    assert "ollabridge:tools" in r.json()["aliases"]


def test_enable_disable(client):
    r = client.post("/admin/providers/huggingface-free/disable", headers=_h())
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.post("/admin/providers/huggingface-free/enable", headers=_h())
    assert r.status_code == 200 and r.json()["enabled"] is True


def test_hf_connect_stores_token_and_swaps_adapter(client, app):
    r = client.post(
        "/admin/providers/huggingface/connect",
        headers=_h(),
        json={"token": "hf_secret_123", "bill_to": "my-org", "mode": "free_credit_only"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["bill_to"] == "my-org"
    # SecretStore got the token (we can't read plaintext through API, that's intentional).
    assert app.state.secret_store.get("huggingface") == "hf_secret_123"
    # Adapter has been hot-swapped — chat() would now send the new auth header.
    adapter = app.state.provider_registry.get_adapter("huggingface-free")
    assert adapter.api_key == "hf_secret_123"
    assert adapter.bill_to == "my-org"


def test_hf_disconnect_clears_everything(client, app):
    app.state.secret_store.set("huggingface", "hf_x")
    app.state.provider_registry.get_adapter("huggingface-free").api_key = "hf_x"

    r = client.post("/admin/providers/huggingface/disconnect", headers=_h())
    assert r.status_code == 200
    assert app.state.secret_store.get("huggingface") is None
    assert app.state.provider_registry.get_adapter("huggingface-free").api_key is None


def test_hf_status_reports_catalog_size_and_last_sync(client):
    r = client.get("/admin/providers/huggingface/status", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert body["catalog"]["entries"] == 2
    assert body["catalog"]["last_sync"]["ok"] is True


def test_hf_models_filter_by_capability(client):
    r = client.get(
        "/admin/providers/huggingface/models",
        headers=_h(),
        params={"task": "vlm"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["models"][0]["router_model_id"] == "x/v:novita"


def test_hf_recommendations_returns_intent_buckets(client):
    r = client.get(
        "/admin/providers/huggingface/recommendations",
        headers=_h(), params={"n": 2},
    )
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    # Tools bucket should pick the chat row with supports_tools=True.
    assert any(c["model"] == "x/a:groq" for c in buckets.get("ollabridge:tools", []))
    # Vision bucket picks the VLM row.
    assert any(c["model"] == "x/v:novita" for c in buckets.get("ollabridge:vision", []))


def test_unauthenticated_request_rejected(client):
    r = client.get("/admin/providers")
    assert r.status_code in (401, 403)
