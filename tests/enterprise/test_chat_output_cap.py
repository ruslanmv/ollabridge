"""The output cap reaches the model, whichever name the client gives it and whichever route serves it.

Before: ``max_completion_tokens`` -- OpenAI's newer name for the cap, and the only one LangChain's
ChatOpenAI sends -- was dropped on arrival, so a LangChain client asking for 20 tokens through Open
WebUI got 300 numbers back in 52 s. Local Ollama and paired devices never received any cap at all,
not even ``max_tokens``. Now:

* ``max_completion_tokens`` is folded into ``max_tokens`` (the newer name wins when both are sent);
* provider add-ons (Open WebUI and the other OpenAI-compatible upstreams) and HomePilot get it as
  ``max_tokens``, as they did for clients that used that name;
* local Ollama gets it as ``options.num_predict``; a paired device gets ``options`` in its frame and
  hands them to its Ollama;
* a request without a cap is exactly what it was.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ollabridge.api.main import ChatReq
from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings
from ollabridge.node.agent import runtime_options
from ollabridge.node.runtime import LocalRuntime

AUTH = {"Authorization": "Bearer test-key-abc"}
HI = [{"role": "user", "content": "Count to 300."}]


def test_both_names_of_the_cap_end_in_max_tokens():
    assert ChatReq(messages=HI, max_completion_tokens=20).max_tokens == 20
    assert ChatReq(messages=HI, max_tokens=40).max_tokens == 40
    assert ChatReq(messages=HI, max_tokens=40, max_completion_tokens=20).max_tokens == 20
    assert ChatReq(messages=HI).max_tokens is None


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


class FakeProviderRouter:
    def __init__(self):
        self.kwargs: dict = {}

    def resolve(self, model):
        return ["open-webui"]

    async def route_chat(self, model, messages, **kwargs):
        self.kwargs = kwargs
        return {"choices": [{"message": {"content": "1 2 3"}}]}


def test_open_webui_gets_the_cap_a_langchain_client_sends(app_client):
    app, client = app_client
    router = FakeProviderRouter()
    app.state.provider_router = router
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "openwebui/internal-gemma4-31b", "messages": HI, "max_completion_tokens": 20})
    assert r.status_code == 200, r.text
    assert router.kwargs["max_tokens"] == 20


def test_an_uncapped_provider_request_is_unchanged(app_client):
    app, client = app_client
    router = FakeProviderRouter()
    app.state.provider_router = router
    r = client.post("/v1/chat/completions", headers=AUTH, json={"model": "openwebui/internal-gemma4-31b", "messages": HI})
    assert r.status_code == 200, r.text
    assert router.kwargs["max_tokens"] is None


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
def test_local_ollama_gets_the_cap_as_num_predict(app_client, field):
    _, client = app_client
    chat = AsyncMock(return_value="1 2 3")
    with patch("ollabridge.providers.ollama_client.chat", new=chat):
        r = client.post("/v1/chat/completions", headers=AUTH, json={"model": "llama3", "messages": HI, field: 20})
    assert r.status_code == 200, r.text
    assert chat.call_args.kwargs["options"] == {"num_predict": 20}


def test_local_ollama_without_a_cap_gets_no_options(app_client):
    _, client = app_client
    chat = AsyncMock(return_value="hello")
    with patch("ollabridge.providers.ollama_client.chat", new=chat):
        r = client.post("/v1/chat/completions", headers=AUTH, json={"model": "llama3", "messages": HI})
    assert r.status_code == 200, r.text
    assert chat.call_args.kwargs["options"] is None


def test_local_ollama_with_tools_gets_the_cap_too(app_client):
    _, client = app_client
    message = AsyncMock(return_value={"content": "ok"})
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object", "properties": {}}}}]
    with patch("ollabridge.providers.ollama_client.chat_message", new=message):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "qwen2.5", "messages": HI, "tools": tools, "max_completion_tokens": 64})
    assert r.status_code == 200, r.text
    assert message.call_args.kwargs["options"] == {"num_predict": 64}


def _only_node(app, connector, model):
    registry = app.state.obridge.registry
    asyncio.run(registry.remove("local"))
    asyncio.run(registry.upsert(RuntimeNodeState(
        node_id="dev1", connector=connector, endpoint="http://node.test", tags=[], models=[model], capacity=1, meta={},
    )))


def test_a_paired_device_gets_the_cap_in_its_frame_and_only_when_set(app_client):
    app, client = app_client
    _only_node(app, "relay_link", "remote-llama")
    relay = AsyncMock(return_value={"ok": True, "data": {"content": "1 2 3"}})
    with patch.object(app.state.relay_hub, "request", new=relay):
        capped = client.post("/v1/chat/completions", headers=AUTH,
                             json={"model": "remote-llama", "messages": HI, "max_completion_tokens": 20})
        plain = client.post("/v1/chat/completions", headers=AUTH, json={"model": "remote-llama", "messages": HI})
    assert capped.status_code == 200 and plain.status_code == 200
    assert relay.call_args_list[0].args[2]["options"] == {"num_predict": 20}
    assert "options" not in relay.call_args_list[1].args[2]


def test_homepilot_gets_the_cap_as_max_tokens(app_client):
    app, client = app_client
    _only_node(app, "homepilot", "persona:atlas")
    connector = AsyncMock()
    connector.chat = AsyncMock(return_value={"content": "hi", "raw": {}})
    app.state.homepilot_connector = connector
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "persona:atlas", "messages": HI, "max_completion_tokens": 20})
    assert r.status_code == 200, r.text
    assert connector.chat.call_args.kwargs["payload"]["max_tokens"] == 20


# ── the node ────────────────────────────────────────────────────────────────


def test_a_node_reads_the_cap_in_every_shape_it_may_get():
    assert runtime_options({"options": {"num_predict": 20}}) == {"num_predict": 20}
    assert runtime_options({"max_completion_tokens": 20}) == {"num_predict": 20}
    assert runtime_options({"max_tokens": 20, "options": {"temperature": 0.1}}) == {"temperature": 0.1, "num_predict": 20}
    assert runtime_options({"max_tokens": True}) is None
    assert runtime_options({"model": "m", "messages": []}) is None


def test_the_node_runtime_sends_options_to_ollama_only_when_given():
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}})

    runtime = LocalRuntime("http://ollama.test")
    runtime._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(runtime.chat(model="m", messages=HI, options={"num_predict": 20}))
    asyncio.run(runtime.chat(model="m", messages=HI))
    assert bodies[0]["options"] == {"num_predict": 20}
    assert "options" not in bodies[1]
