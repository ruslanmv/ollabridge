"""Tool-bearing /v1/chat/completions requests reach provider models.

Before: a request that carried ``tools`` skipped the provider router and went to local
Ollama, which cannot serve a provider-namespaced model (``openwebui/...``) — the client got
an HTTP 500 wrapping a 404 from ``/api/chat`` every time it offered tools, and HomePilot's
Expert mode read that as "this model is broken". Now the provider gets ``tools`` and
``tool_choice`` and its ``tool_calls`` come back; a provider that rejects the field answers
with a 400 ``tools_unsupported`` the client can act on. Text-only traffic is unchanged.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}
TOOLS = [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}]
BODY = {"model": "openwebui/internal-gemma4-31b", "messages": [{"role": "user", "content": "call ping"}], "tools": TOOLS,
        "tool_choice": "auto"}


@pytest.fixture
def app_client(monkeypatch, ollabridge_home):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        app.state.provider_router = None
        asyncio.run(app.state.obridge.registry.upsert(RuntimeNodeState(
            node_id="local", connector="local_ollama", endpoint="http://localhost:11434",
            tags=["local"], models=[], capacity=1, meta={},
        )))
        yield app, client


class ToolCallingRouter:
    def __init__(self):
        self.kwargs = None

    def resolve(self, model):
        return ["open-webui"]

    async def route_chat(self, model, messages, **kwargs):
        self.kwargs = kwargs
        return {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "ping", "arguments": "{}"}},
        ]}}]}


class RefusingRouter:
    def resolve(self, model):
        return ["open-webui"]

    async def route_chat(self, model, messages, **kwargs):
        from ollabridge.addons.providers.errors import ProviderBadRequest

        exc = ProviderBadRequest("HTTP 400: tools are not supported for this model")
        exc.upstream_status = 400
        raise exc


def test_tools_reach_the_provider_and_its_tool_calls_come_back(app_client):
    app, client = app_client
    router = ToolCallingRouter()
    app.state.provider_router = router
    local = AsyncMock()
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH, json=BODY)
    assert r.status_code == 200, r.text
    assert router.kwargs["tools"] == TOOLS and router.kwargs["tool_choice"] == "auto"
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == "ping"
    local.assert_not_called()                                   # never rerouted to local Ollama


def test_a_provider_that_rejects_tools_answers_400_not_a_local_500(app_client):
    app, client = app_client
    app.state.provider_router = RefusingRouter()
    local = AsyncMock()
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH, json=BODY)
    assert r.status_code == 400, r.text
    err = r.json()["detail"]["error"]
    assert err["code"] == "tools_unsupported" and err["param"] == "tools"
    assert "does not support tools" in err["message"]
    local.assert_not_called()


def FailingRouter(make_exc, provider_id="openwebui"):
    """The real ``ProviderRouter`` over one adapter that fails in a given way — so the test sees
    exactly what the API sees: the router's own wrapping of the provider's error."""
    from types import SimpleNamespace

    from ollabridge.addons.providers.router import ProviderRouter

    class _Adapter:
        async def chat(self, model, messages, **kwargs):
            raise make_exc()

    class _Registry:
        def get_adapter(self, pid):
            return _Adapter()

        async def record_request(self, *a, **k):
            return None

        async def update_health(self, *a, **k):
            return None

    router = ProviderRouter(_Registry())
    route = SimpleNamespace(provider_id=provider_id, model="openwebui/internal-gemma4-31b", score=0.9)
    router.resolve = lambda model: [route]  # type: ignore[method-assign]
    return router


def _open_webui_rate_limit():
    # What the Open WebUI adapter raises for upstream HTTP 400 {"detail": "Rate limit exceeded..."}.
    from ollabridge.addons.providers.errors import ProviderBadRequest

    return ProviderBadRequest('bad request (HTTP 400): {"detail":"Rate limit exceeded. Please try again later."}')


@pytest.mark.parametrize("with_tools", [True, False])
def test_a_rate_limited_provider_model_answers_429_not_a_local_500(app_client, with_tools):
    app, client = app_client
    app.state.provider_router = FailingRouter(_open_webui_rate_limit)
    body = dict(BODY) if with_tools else {k: v for k, v in BODY.items() if k not in ("tools", "tool_choice")}
    local = AsyncMock()
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH, json=body)
    assert r.status_code == 429, r.text
    err = r.json()["detail"]["error"]
    assert err["code"] == "rate_limited" and err["type"] == "rate_limit_error"
    assert "rate limiting" in err["message"] and "Rate limit exceeded" in err["message"]
    local.assert_not_called()                                   # never a 404 from /api/chat


def test_an_unavailable_provider_for_a_namespaced_model_answers_502(app_client):
    from ollabridge.addons.providers.errors import ProviderUnavailable

    app, client = app_client
    app.state.provider_router = FailingRouter(lambda: ProviderUnavailable("upstream error (HTTP 503)"))
    local = AsyncMock()
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "openwebui/internal-gemma4-31b", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["error"]["code"] == "provider_unavailable"
    local.assert_not_called()


def test_a_plain_model_name_still_falls_back_to_local_ollama(app_client):
    """An alias such as ``llama3`` may exist locally too: a provider outage falls through as before."""
    from ollabridge.addons.providers.errors import ProviderUnavailable

    app, client = app_client
    app.state.provider_router = FailingRouter(lambda: ProviderUnavailable("upstream error (HTTP 503)"))
    local = AsyncMock(return_value={"content": "local says hi", "tool_calls": []})
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH, json={**BODY, "model": "llama3"})
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "local says hi"
    local.assert_called_once()


def test_text_only_requests_to_a_provider_are_unchanged(app_client):
    app, client = app_client
    router = ToolCallingRouter()

    async def plain(model, messages, **kwargs):
        router.kwargs = kwargs
        return {"choices": [{"message": {"content": "hello back"}}]}

    router.route_chat = plain  # type: ignore[method-assign]
    app.state.provider_router = router
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "openwebui/internal-gemma4-31b", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "hello back"
    assert "tools" not in router.kwargs and "tool_choice" not in router.kwargs


def _ollama_http_error(status, body):
    import httpx

    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError(f"Client error '{status}' for url 'http://localhost:11434/api/chat'",
                                 request=request, response=response)


@pytest.mark.parametrize("status, body, code", [
    (400, {"error": "registry.ollama.ai/library/llama3:8b does not support tools"}, "tools_unsupported"),
    (404, {"error": "model 'nope:1b' not found"}, "model_not_found"),
])
def test_local_ollama_refusals_keep_their_meaning(app_client, status, body, code):
    """A local model without tool support answers 400 tools_unsupported (the client retries
    without tools), a missing model 404 — never a bare 500 wrapping Ollama's error."""
    app, client = app_client
    local = AsyncMock(side_effect=_ollama_http_error(status, body))
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post("/v1/chat/completions", headers=AUTH, json={**BODY, "model": "llama3:8b"})
    assert r.status_code == status, r.text
    err = r.json()["detail"]["error"]
    assert err["code"] == code and body["error"] in err["message"]
