"""``/v1/models`` says where every entry is served from.

Regression for the Runtimes page reporting "54 Ollama model(s) discovered"
while Ollama was unreachable (2026-10-13). Local Ollama entries carried no
``owned_by`` at all, Open WebUI and BYOK entries did, and the dashboard
counted everything without a ``persona:`` prefix as Ollama. Every entry now
carries ``source`` (``ollama`` | ``homepilot`` | ``relay`` | ``direct_endpoint``
| ``open_webui`` | ``byok:<name>``) and, where known, ``source_display_name``;
``owned_by`` is filled for the local runtime and left alone wherever an
upstream already set it. The OpenAI shape is unchanged for clients.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}


class _Registry:
    """Just enough of ``ProviderRegistry`` for the listing route."""

    def __init__(self, configs, adapters=None):
        self._configs = list(configs)
        self._adapters = dict(adapters or {})

    def list_enabled(self):
        return [c for c in self._configs if c.enabled]

    def list_providers(self):
        return list(self._configs)

    def get_adapter(self, provider_id):
        return self._adapters.get(provider_id)


OPEN_WEBUI_CFG = ProviderConfig(
    id="openwebui",
    name="Open WebUI (compatible)",
    kind="open_webui",
    model_prefix="openwebui",
    dynamic_models=True,
)
BYOK_CFG = ProviderConfig(
    id="byok-watsonx",
    name="IBM watsonx",
    kind="watsonx",
    models=["ibm/granite-4-h-small"],
)


def _open_webui_entry(upstream_id: str) -> dict:
    # The adapter's own normalisation (not under test here): namespaced id,
    # the namespace as owner, the upstream id kept.
    return {
        "id": f"openwebui/{upstream_id}",
        "object": "model",
        "owned_by": "openwebui",
        "upstream_model_id": upstream_id,
    }


def _node(node_id: str, connector: str, endpoint: str = "", meta: dict | None = None):
    return RuntimeNodeState(
        node_id=node_id,
        connector=connector,
        endpoint=endpoint,
        tags=[],
        models=[],
        capacity=1,
        meta=meta or {},
    )


@pytest.fixture
def app_and_client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        # Startup seeds the provider registry in a background task that ends
        # by setting ``hf_catalog_sync`` on both its success and failure paths.
        # Wait for it so a test's own registry is not overwritten mid-flight.
        deadline = time.monotonic() + 10
        while not hasattr(app.state, "hf_catalog_sync") and time.monotonic() < deadline:
            time.sleep(0.05)
        app.state.provider_router = None
        yield app, client


def _register(app, *nodes: RuntimeNodeState) -> None:
    """Replace whatever startup registered with exactly these nodes."""

    async def go():
        registry = app.state.obridge.registry
        for n in await registry.list():
            await registry.remove(n.node_id)
        for n in nodes:
            await registry.upsert(n)

    asyncio.run(go())


def _list(client):
    r = client.get("/v1/models", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    return r, body["data"]


# --- the helper itself -------------------------------------------------------


def test_stamp_fills_owner_only_when_upstream_left_it_empty():
    from ollabridge.api.main import _stamp_model_source

    bare = _stamp_model_source(
        {"id": "llama3"}, source="ollama", display_name="Ollama", owned_by="ollama"
    )
    assert bare == {
        "id": "llama3",
        "object": "model",
        "owned_by": "ollama",
        "source": "ollama",
        "source_display_name": "Ollama",
    }

    owned = _stamp_model_source(
        {"id": "openwebui/x", "object": "model", "owned_by": "openwebui"},
        source="open_webui",
        display_name="Open WebUI (compatible)",
        owned_by="should-not-win",
    )
    assert owned["owned_by"] == "openwebui"
    assert owned["source"] == "open_webui"
    assert owned["source_display_name"] == "Open WebUI (compatible)"


def test_dynamic_provider_source_mapping():
    from ollabridge.api.main import _dynamic_provider_source

    assert _dynamic_provider_source(OPEN_WEBUI_CFG) == (
        "open_webui",
        "Open WebUI (compatible)",
    )
    assert _dynamic_provider_source(BYOK_CFG) == ("byok:watsonx", "IBM watsonx")
    other = ProviderConfig(id="groq-free", name="Groq", kind="groq", dynamic_models=True)
    assert _dynamic_provider_source(other) == ("groq", "Groq")


def test_byok_runtime_models_carry_their_source():
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    entries = dss.byok_runtime_models(_Registry([BYOK_CFG]))
    assert entries == [
        {
            "id": "ibm/granite-4-h-small",
            "object": "model",
            "owned_by": "IBM watsonx",
            "source": "byok:watsonx",
            "source_display_name": "IBM watsonx",
        }
    ]


# --- the route ---------------------------------------------------------------


def test_every_entry_says_where_it_is_served_from(app_and_client):
    app, client = app_and_client
    _register(
        app,
        _node(settings.LOCAL_NODE_ID, "local_ollama", "http://localhost:11434"),
        _node(settings.HOMEPILOT_NODE_ID, "homepilot", "http://localhost:8000", {"api_key": ""}),
        _node("relay-1", "relay_link"),
        _node("edge-1", "direct_endpoint", "http://10.0.0.7:11436"),
    )
    app.state.homepilot_connector = SimpleNamespace(
        models=AsyncMock(return_value={"data": [{"id": "persona:ana", "object": "model"}]})
    )
    app.state.relay_hub.request = AsyncMock(
        return_value={"data": {"object": "list", "data": [{"id": "relay-llama", "object": "model"}]}}
    )
    app.state.obridge.direct.models = AsyncMock(
        return_value={"data": [{"id": "edge-mistral", "object": "model", "owned_by": "edge-box"}]}
    )
    adapter = SimpleNamespace(list_models=AsyncMock(return_value=[_open_webui_entry("gemma4")]))
    app.state.provider_registry = _Registry([OPEN_WEBUI_CFG, BYOK_CFG], {"openwebui": adapter})

    with patch(
        "ollabridge.providers.ollama_client.list_models",
        new=AsyncMock(return_value=["llama3:8b"]),
    ):
        r, data = _list(client)

    by_id = {m["id"]: m for m in data}
    assert set(by_id) == {
        "llama3:8b",
        "persona:ana",
        "relay-llama",
        "edge-mistral",
        "openwebui/gemma4",
        "ibm/granite-4-h-small",
    }

    assert by_id["llama3:8b"] == {
        "id": "llama3:8b",
        "object": "model",
        "owned_by": "ollama",
        "source": "ollama",
        "source_display_name": "Ollama",
    }
    assert by_id["persona:ana"]["source"] == "homepilot"
    assert by_id["persona:ana"]["owned_by"] == "homepilot"
    assert by_id["persona:ana"]["source_display_name"] == "HomePilot"

    assert by_id["relay-llama"]["source"] == "relay"
    assert by_id["relay-llama"]["owned_by"] == "relay"
    assert by_id["relay-llama"]["source_display_name"] == "Relay node relay-1"

    assert by_id["edge-mistral"]["source"] == "direct_endpoint"
    assert by_id["edge-mistral"]["owned_by"] == "edge-box"  # upstream owner kept
    assert by_id["edge-mistral"]["source_display_name"] == "http://10.0.0.7:11436"

    assert by_id["openwebui/gemma4"]["source"] == "open_webui"
    assert by_id["openwebui/gemma4"]["owned_by"] == "openwebui"  # adapter's namespace kept
    assert by_id["openwebui/gemma4"]["source_display_name"] == "Open WebUI (compatible)"

    assert by_id["ibm/granite-4-h-small"]["source"] == "byok:watsonx"
    assert by_id["ibm/granite-4-h-small"]["owned_by"] == "IBM watsonx"

    # The OpenAI shape stays intact for every client that ignores the extras.
    for m in data:
        assert m["object"] == "model"
        assert isinstance(m["id"], str) and m["id"]
        assert m["owned_by"]
    assert "X-OllaBridge-Warning" not in r.headers


def test_ollama_down_leaves_zero_ollama_models_and_no_orphans(app_and_client):
    """The observed failure: Ollama unreachable, an Open WebUI source with a
    large catalog and a BYOK runtime connected. Nothing may be attributed to
    Ollama, and nothing may be left without a source for the UI to guess at."""
    app, client = app_and_client
    _register(app, _node(settings.LOCAL_NODE_ID, "local_ollama", "http://localhost:11434"))
    catalog = [_open_webui_entry(f"model-{i}") for i in range(54)]
    adapter = SimpleNamespace(list_models=AsyncMock(return_value=catalog))
    app.state.provider_registry = _Registry([OPEN_WEBUI_CFG, BYOK_CFG], {"openwebui": adapter})

    with patch(
        "ollabridge.providers.ollama_client.list_models",
        new=AsyncMock(return_value=[]),  # what a dead runtime yields
    ):
        r, data = _list(client)

    assert len(data) == 55
    assert [m for m in data if m["source"] == "ollama"] == []
    assert sum(1 for m in data if m["source"] == "open_webui") == 54
    assert [m["source"] for m in data if m["id"] == "ibm/granite-4-h-small"] == ["byok:watsonx"]
    assert all(m.get("source") and m.get("owned_by") for m in data)
    # The listing is not empty, so the "nothing available" warning is not raised.
    assert "X-OllaBridge-Warning" not in r.headers


def test_empty_inventory_still_warns(app_and_client):
    app, client = app_and_client
    _register(app, _node(settings.LOCAL_NODE_ID, "local_ollama", "http://localhost:11434"))
    app.state.provider_registry = _Registry([])

    with patch(
        "ollabridge.providers.ollama_client.list_models",
        new=AsyncMock(return_value=[]),
    ):
        r, data = _list(client)

    assert data == []
    assert r.headers["X-OllaBridge-Warning"] == "models_unavailable"
