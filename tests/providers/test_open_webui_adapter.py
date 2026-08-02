"""Unit tests for the generic Open WebUI-compatible adapter.

Covers the behaviors that make it safe to point at any Open WebUI-style server:
preferred/legacy endpoint negotiation, Bearer + x-api-key transport, model
namespacing + prefix stripping, full-response preservation, honest error
mapping, credential redaction, and fail-closed-on-404.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers.adapters import open_webui as ow_mod
from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)

BASE = "https://host.example/api"


@pytest.fixture
def make_adapter(monkeypatch):
    """Return a factory that patches httpx.AsyncClient (inside the adapter
    module) to route through a MockTransport, then builds an adapter."""
    real_client = ow_mod.httpx.AsyncClient

    def _factory(handler, **kwargs):
        transport = httpx.MockTransport(handler)

        def _patched(*a, **kw):
            kw["transport"] = transport
            return real_client(*a, **kw)

        monkeypatch.setattr(ow_mod.httpx, "AsyncClient", _patched)
        kwargs.setdefault("base_url", BASE)
        kwargs.setdefault("api_key", "sk-secret-123")
        return OpenWebUIAdapter(**kwargs)

    return _factory


def _models_body(ids):
    return {"data": [{"id": i, "name": i.upper()} for i in ids]}


# --- discovery + namespacing -------------------------------------------------

@pytest.mark.asyncio
async def test_lists_models_from_preferred_path_namespaced(make_adapter):
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json=_models_body(["qwen3-coder", "gpt-4.1"]))

    adapter = make_adapter(handler)
    models = await adapter.list_models()
    assert seen["path"] == "/api/v1/models"  # preferred OpenAI-compat path
    assert seen["auth"] == "Bearer sk-secret-123"
    ids = [m["id"] for m in models]
    assert ids == ["openwebui/qwen3-coder", "openwebui/gpt-4.1"]
    m0 = models[0]
    assert m0["owned_by"] == "openwebui" and m0["upstream_model_id"] == "qwen3-coder"
    # A plain model entry (no pipe/preset) is chat-capable; the rest stay null —
    # never inferred from the name.
    assert m0["capabilities"]["chat"] is True
    assert m0["capabilities"]["tools"] is None and m0["capabilities"]["vision"] is None
    assert m0["category"] == "chat" and m0["persona_compatible"] is True


@pytest.mark.asyncio
async def test_falls_back_to_legacy_models_path_on_404(make_adapter):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/api/v1/models":
            return httpx.Response(404, text="not found")
        return httpx.Response(200, json=_models_body(["m1"]))

    adapter = make_adapter(handler)
    models = await adapter.list_models()
    assert seen == ["/api/v1/models", "/api/models"]  # negotiated to legacy
    assert models[0]["id"] == "openwebui/m1"


@pytest.mark.asyncio
async def test_x_api_key_transport(make_adapter):
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("Authorization")
        seen["xapi"] = req.headers.get("x-api-key")
        return httpx.Response(200, json=_models_body(["m1"]))

    adapter = make_adapter(handler, auth_header="x-api-key")
    await adapter.list_models()
    assert seen["auth"] is None and seen["xapi"] == "sk-secret-123"


@pytest.mark.asyncio
async def test_duplicate_upstream_ids_deduped_and_empty_is_valid(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(200, json=_models_body(["dup", "dup", "x"])))
    ids = [m["id"] for m in await adapter.list_models()]
    assert ids == ["openwebui/dup", "openwebui/x"]

    empty = make_adapter(lambda req: httpx.Response(200, json={"data": []}))
    assert await empty.list_models() == []


@pytest.mark.asyncio
async def test_custom_prefix_isolates_two_instances(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(200, json=_models_body(["m"])), model_prefix="team-a")
    assert (await adapter.list_models())[0]["id"] == "team-a/m"


# --- catalog metadata preservation + classification --------------------------

def _rich_catalog():
    return {"data": [
        {"id": "llama-local", "name": "Llama", "owned_by": "ollama",
         "connection_type": "local", "tags": [{"name": "internal"}],
         "info": {"meta": {"description": "A local model", "capabilities": {"vision": True}}}},
        {"id": "gpt-ext", "name": "GPT", "owned_by": "openai",
         "connection_type": "external", "tags": ["papaki-legal"]},
        {"id": "img-pipe", "name": "Image", "connection_type": "local",
         "tags": [{"name": "image"}], "pipe": {"type": "image"}},
        {"id": "preset-x", "name": "Preset", "preset": True, "tags": []},
    ]}


@pytest.mark.asyncio
async def test_preserves_catalog_metadata_and_normalizes_tags(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(200, json=_rich_catalog()))
    models = {m["upstream_model_id"]: m for m in await adapter.list_models()}

    local = models["llama-local"]
    assert local["connection_type"] == "local"
    assert local["tags"] == [{"name": "internal"}]
    assert local["description"] == "A local model"
    assert local["upstream_owned_by"] == "ollama"
    assert local["capabilities"]["vision"] is True and local["category"] == "vision"

    # Bare-string tags are normalized to {"name": ...} form.
    assert models["gpt-ext"]["tags"] == [{"name": "papaki-legal"}]
    assert models["gpt-ext"]["connection_type"] == "external"


@pytest.mark.asyncio
async def test_classifies_non_chat_entries_and_flags_persona_safety(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(200, json=_rich_catalog()))
    models = {m["upstream_model_id"]: m for m in await adapter.list_models()}
    # A pipe-backed and a preset entry are workflows, not auto-offered chat models.
    assert models["img-pipe"]["category"] == "preset_or_workflow"
    assert models["img-pipe"]["persona_compatible"] is False
    assert models["preset-x"]["category"] == "preset_or_workflow"
    assert models["preset-x"]["persona_compatible"] is False
    # A plain external model is chat-capable.
    assert models["gpt-ext"]["category"] == "chat" and models["gpt-ext"]["persona_compatible"] is True


@pytest.mark.asyncio
async def test_filter_reproduces_openwebui_views(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(200, json=_rich_catalog()))
    models = await adapter.list_models()
    f = OpenWebUIAdapter.filter_models
    assert {m["upstream_model_id"] for m in f(models, connection_type="local")} == {"llama-local", "img-pipe"}
    assert {m["upstream_model_id"] for m in f(models, connection_type="external")} == {"gpt-ext"}
    assert {m["upstream_model_id"] for m in f(models, tag="papaki-legal")} == {"gpt-ext"}
    assert {m["upstream_model_id"] for m in f(models, tag="image")} == {"img-pipe"}
    # Persona-compatible view excludes the pipe + preset workflows.
    assert {m["upstream_model_id"] for m in f(models, persona_compatible=True)} == {"llama-local", "gpt-ext"}


# --- chat: prefix strip + full response --------------------------------------

@pytest.mark.asyncio
async def test_chat_strips_prefix_upstream_and_preserves_full_response(make_adapter):
    seen = {}

    def handler(req):
        import json as _json
        seen["path"] = req.url.path
        seen["body"] = _json.loads(req.read().decode())
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1,
            "model": "qwen3-coder",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "f", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        })

    adapter = make_adapter(handler)
    out = await adapter.chat("openwebui/qwen3-coder", [{"role": "user", "content": "hi"}], temperature=0.2)
    assert seen["path"] == "/api/v1/chat/completions"
    assert seen["body"]["model"] == "qwen3-coder"  # namespace stripped upstream
    assert seen["body"]["temperature"] == 0.2
    # Full OpenAI object preserved; only the public model id is re-labelled.
    assert out["model"] == "openwebui/qwen3-coder"
    assert out["choices"][0]["finish_reason"] == "tool_calls"
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "f"
    assert out["usage"]["total_tokens"] == 7


@pytest.mark.asyncio
async def test_chat_drops_unknown_fields(make_adapter):
    seen = {}

    def handler(req):
        import json as _json
        seen["body"] = _json.loads(req.read().decode())
        return httpx.Response(200, json={"id": "x", "choices": []})

    adapter = make_adapter(handler)
    await adapter.chat("openwebui/m", [{"role": "user", "content": "hi"}], top_p=0.9, evil_param="x")
    assert seen["body"]["top_p"] == 0.9 and "evil_param" not in seen["body"]


# --- error mapping + redaction + fail-closed ---------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status,exc", [
    (401, ProviderAuthError), (403, ProviderAuthError),
    (429, ProviderQuotaExceeded), (402, ProviderQuotaExceeded),
    (400, ProviderBadRequest), (422, ProviderBadRequest),
    (500, ProviderUnavailable), (503, ProviderUnavailable),
])
async def test_chat_error_mapping(make_adapter, status, exc):
    adapter = make_adapter(lambda req: httpx.Response(status, text="boom"))
    with pytest.raises(exc):
        await adapter.chat("openwebui/m", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_auth_failure_on_models_does_not_return_stale(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(401, text="sk-secret-123 rejected"))
    with pytest.raises(ProviderAuthError):
        await adapter.list_models()


@pytest.mark.asyncio
async def test_error_text_redacts_key(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(400, text="bad key sk-secret-123 here"))
    with pytest.raises(ProviderBadRequest) as ei:
        await adapter.chat("openwebui/m", [{"role": "user", "content": "x"}])
    assert "sk-secret-123" not in str(ei.value) and "***" in str(ei.value)


@pytest.mark.asyncio
async def test_chat_fails_closed_when_all_paths_404(make_adapter):
    adapter = make_adapter(lambda req: httpx.Response(404, text="nope"))
    with pytest.raises(ProviderBadRequest):
        await adapter.chat("openwebui/m", [{"role": "user", "content": "x"}])
