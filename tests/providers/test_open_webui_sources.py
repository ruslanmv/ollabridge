"""Dynamic Open WebUI source: registry sync, discovery, and model filtering.

These prove the "surfacing" contract the UI depends on: a saved source is
registered into the live registry (so it is servable, not just displayed), its
models are discovered live from the upstream with normalized metadata, and the
All / Local / External / tag / persona-compatible filters return real data.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers.adapters import open_webui as ow_mod
from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter
from ollabridge.addons.providers.services import dynamic_source_sync as dss
from ollabridge.providers_meta import ProviderRecord


def _catalog():
    return {"data": [
        {"id": "llama-local", "name": "Llama", "connection_type": "local",
         "tags": [{"name": "internal"}]},
        {"id": "gpt-ext", "name": "GPT", "connection_type": "external",
         "tags": ["legal"]},
        {"id": "img", "name": "Image", "connection_type": "external",
         "tags": [{"name": "image"}], "pipe": {"type": "image"}},
    ]}


@pytest.fixture
def patch_upstream(monkeypatch):
    real = ow_mod.httpx.AsyncClient

    def _apply(handler):
        transport = httpx.MockTransport(handler)

        def _patched(*a, **kw):
            kw.setdefault("transport", transport)
            return real(*a, **kw)

        monkeypatch.setattr(ow_mod.httpx, "AsyncClient", _patched)

    return _apply


class _App:
    """Minimal app stand-in carrying a real ProviderRegistry."""

    def __init__(self):
        self.state = type("S", (), {})()
        self.state.provider_registry = ProviderRegistry()


def _rec(**kw):
    base = dict(name="open_webui", kind="open_webui", base_url="https://h.example/api", enabled=True)
    base.update(kw)
    return ProviderRecord(**base)


# --- discovery summary + normalization ---------------------------------------

def test_discovery_summary_counts(patch_upstream):
    patch_upstream(lambda req: httpx.Response(200, json=_catalog()))
    import asyncio
    adapter = dss.build_adapter(_rec(), "sk-x")
    models = asyncio.run(adapter.list_models())
    summary = dss.discovery_summary(models)
    assert summary["count"] == 3
    assert summary["connection_types"] == {"local": 1, "external": 2}
    assert summary["persona_compatible"] == 2  # the image pipe is excluded
    assert summary["tags"] == {"internal": 1, "legal": 1, "image": 1}


# --- registry sync makes the source servable ---------------------------------

@pytest.mark.asyncio
async def test_sync_registers_and_routes_namespaced_model(monkeypatch, patch_upstream):
    patch_upstream(lambda req: httpx.Response(200, json=_catalog()))
    app = _App()
    monkeypatch.setattr(dss, "get_record", lambda name: _rec())

    ok = await dss.sync_source(app, "open_webui", "sk-x")
    assert ok is True
    reg = app.state.provider_registry
    assert reg.get_adapter("openwebui") is not None

    # A namespaced model resolves to this provider (servable, not just listed).
    router = ProviderRouter(reg)
    routes = router.resolve("openwebui/gpt-ext")
    assert routes and routes[0].provider_id == "openwebui"


@pytest.mark.asyncio
async def test_disable_then_unsync_removes_from_registry(monkeypatch):
    app = _App()
    # Pre-register, then a disabled record must unregister it.
    await app.state.provider_registry.register(
        ProviderConfig(id="openwebui", name="x", kind="open_webui", model_prefix="openwebui",
                       dynamic_models=True),
        object(),  # adapter placeholder; unregister doesn't use it
    )
    monkeypatch.setattr(dss, "get_record", lambda name: _rec(enabled=False))
    await dss.sync_source(app, "open_webui", "sk-x")
    assert app.state.provider_registry.get_adapter("openwebui") is None

    # Explicit unsync (delete) also clears a registered provider.
    await app.state.provider_registry.register(
        ProviderConfig(id="openwebui", name="x", kind="open_webui", model_prefix="openwebui",
                       dynamic_models=True),
        object(),
    )
    await dss.unsync_source(app, "open_webui")
    assert app.state.provider_registry.get_adapter("openwebui") is None


@pytest.mark.asyncio
async def test_non_dynamic_source_is_ignored(monkeypatch):
    app = _App()
    monkeypatch.setattr(dss, "get_record", lambda name: _rec(name="groq", kind="groq"))
    assert await dss.sync_source(app, "groq", "gsk_x") is False
    assert app.state.provider_registry.provider_count == 0
