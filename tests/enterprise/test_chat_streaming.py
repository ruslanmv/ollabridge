"""``stream: true`` on /v1/chat/completions answers in OpenAI's SSE format.

Before: ``ChatReq`` had no ``stream`` field, so pydantic dropped it and a streaming client got one plain
JSON object. Open WebUI's tool loop always streams, so every tool chat through OllaBridge waited forever
after the tools were listed (seen 2026-11-09 with Open WebUI 0.11.4). Now a streaming caller gets the
same answer as chunks: the assistant delta (content and/or tool_calls with their ``index``), a delta
with ``finish_reason``, then ``[DONE]``. Answers also carry ``model`` and ``created``.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}
TOOLS = [{"type": "function", "function": {"name": "kpi_snapshot", "parameters": {"type": "object", "properties": {}}}}]
MODEL = "openwebui/gemma-3-27b"


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


class Router:
    def __init__(self, message):
        self.message = message

    def resolve(self, model):
        return ["open-webui"]

    async def route_chat(self, model, messages, **kwargs):
        return {"choices": [{"message": self.message}]}


def _events(text: str) -> list:
    out = []
    for block in text.strip().split("\n\n"):
        assert block.startswith("data: "), block
        payload = block[len("data: "):]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


def test_a_streamed_tool_call_comes_back_as_chunks(app_client):
    app, client = app_client
    app.state.provider_router = Router({"content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "kpi_snapshot", "arguments": "{}"}}]})
    with patch("ollabridge.providers.ollama_client.chat_message", new=AsyncMock()):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": MODEL, "stream": True, "tools": TOOLS,
                              "messages": [{"role": "user", "content": "how are we doing?"}]})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    first, last, done = _events(r.text)
    assert done == "[DONE]"
    assert first["object"] == "chat.completion.chunk" and first["model"] == MODEL and "created" in first
    delta = first["choices"][0]["delta"]
    assert delta["role"] == "assistant" and "content" not in delta
    tc = delta["tool_calls"][0]
    assert tc["index"] == 0 and tc["id"] == "call_1" and tc["function"]["name"] == "kpi_snapshot"
    assert last["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "tool_calls"}


def test_a_streamed_text_answer_comes_back_as_chunks(app_client):
    app, client = app_client
    app.state.provider_router = Router({"content": "Usable answers: 30.7 %"})
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": MODEL, "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200, r.text
    first, last, done = _events(r.text)
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": "Usable answers: 30.7 %"}
    assert last["choices"][0]["finish_reason"] == "stop" and done == "[DONE]"


@pytest.mark.parametrize("stream", [None, False])
def test_without_stream_the_answer_is_one_object_and_carries_model(app_client, stream):
    app, client = app_client
    app.state.provider_router = Router({"content": "hello back"})
    body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}]}
    if stream is not None:
        body["stream"] = stream
    r = client.post("/v1/chat/completions", headers=AUTH, json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["object"] == "chat.completion" and d["model"] == MODEL and isinstance(d["created"], int)
    assert d["choices"][0]["message"]["content"] == "hello back"


def test_a_streamed_request_that_fails_still_answers_with_the_error(app_client):
    """Errors keep their status and JSON body: no stream is opened for a failure."""
    from ollabridge.addons.providers.errors import ProviderUnavailable

    class Failing(Router):
        async def route_chat(self, model, messages, **kwargs):
            raise ProviderUnavailable("upstream error (HTTP 503)")

    app, client = app_client
    app.state.provider_router = Failing({})
    with patch("ollabridge.providers.ollama_client.chat_message", new=AsyncMock()):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": MODEL, "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code >= 400
    assert not r.headers["content-type"].startswith("text/event-stream")
