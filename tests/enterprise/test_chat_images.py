"""Images in /v1/chat/completions reach the model — or the caller is told why not.

Before: every message was flattened to its text before routing, so an OpenAI ``image_url``
part was silently dropped. Asked for the colour of a red square, a vision model behind Open
WebUI answered "NO IMAGE". Now each route keeps what it can carry:

* provider add-ons (Open WebUI and the other OpenAI-compatible upstreams) get the content
  parts unchanged;
* local Ollama and paired devices get Ollama's shape — the text, plus base64 in ``images``;
* Gemini gets ``inline_data`` parts;
* routes that carry text only (direct endpoints, the HomePilot persona connector) refuse
  with ``501 unsupported_capability`` instead of answering blind.

Requests relayed by OllaBridge Cloud arrive in Ollama's shape (``images`` beside the text);
the gateway used to drop that field on arrival, so a picture sent through the Cloud never
reached the model. It is now folded into content parts and routed like any other.

Text-only messages are byte-for-byte what they were.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.core import message_content
from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings

PNG = "data:image/png;base64,iVBORw0KGgo="
IMAGE_MESSAGE = {
    "role": "user",
    "content": [
        {"type": "text", "text": "What colour is this?"},
        {"type": "image_url", "image_url": {"url": PNG}},
    ],
}
AUTH = {"Authorization": "Bearer test-key-abc"}


# ── the helpers ─────────────────────────────────────────────────────────────


class TestMessageContent:
    def test_plain_text_is_unchanged_everywhere(self):
        assert message_content.openai_content("hi") == "hi"
        assert message_content.ollama_images("hi") == []
        assert message_content.gemini_parts("hi") == [{"text": "hi"}]

    def test_text_only_parts_still_flatten_to_a_string(self):
        parts = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        assert message_content.openai_content(parts) == "ab"

    def test_images_are_kept_in_each_upstream_shape(self):
        content = IMAGE_MESSAGE["content"]
        assert message_content.has_images(content)
        assert message_content.openai_content(content) == content
        assert message_content.ollama_images(content) == ["iVBORw0KGgo="]
        assert message_content.gemini_parts(content) == [
            {"text": "What colour is this?"},
            {"inline_data": {"mime_type": "image/png", "data": "iVBORw0KGgo="}},
        ]

    def test_a_remote_url_is_not_base64(self):
        content = [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
        assert message_content.image_urls(content) == ["https://example.com/a.png"]
        assert message_content.ollama_images(content) == []  # Ollama takes no URLs


def test_gemini_receives_inline_data():
    from ollabridge.addons.providers.adapters.gemini import GeminiAdapter

    out = GeminiAdapter._to_gemini_messages([{"role": "user", "content": "hello"}, IMAGE_MESSAGE])
    assert out[0] == {"role": "user", "parts": [{"text": "hello"}]}
    assert out[1]["parts"][1]["inline_data"]["mime_type"] == "image/png"


# ── the route ───────────────────────────────────────────────────────────────


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


def test_local_ollama_gets_the_image_in_its_own_shape(app_client):
    _, client = app_client
    chat = AsyncMock(return_value="red")
    with patch("ollabridge.providers.ollama_client.chat", new=chat):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "llava", "messages": [IMAGE_MESSAGE]})
    assert r.status_code == 200, r.text
    sent = chat.call_args.kwargs["messages"]
    assert sent == [{"role": "user", "content": "What colour is this?", "images": ["iVBORw0KGgo="]}]


def test_text_only_traffic_is_exactly_what_it_was(app_client):
    _, client = app_client
    chat = AsyncMock(return_value="hello back")
    with patch("ollabridge.providers.ollama_client.chat", new=chat):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert chat.call_args.kwargs["messages"] == [{"role": "user", "content": "hi"}]


class FakeProviderRouter:
    def __init__(self):
        self.messages = None

    def resolve(self, model):
        return ["open-webui"]

    async def route_chat(self, model, messages, **kwargs):
        self.messages = messages
        return {"choices": [{"message": {"content": "red"}}]}


def test_open_webui_and_other_providers_get_the_content_parts(app_client):
    app, client = app_client
    router = FakeProviderRouter()
    app.state.provider_router = router
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "openwebui/internal-gemma4-31b", "messages": [IMAGE_MESSAGE]})
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "red"
    assert router.messages == [IMAGE_MESSAGE]


def _only_node(app, connector, model):
    registry = app.state.obridge.registry
    asyncio.run(registry.remove("local"))
    asyncio.run(registry.upsert(RuntimeNodeState(
        node_id="dev1", connector=connector, endpoint="http://homepilot.test", tags=[], models=[model],
        capacity=1, meta={},
    )))


def test_a_paired_device_gets_the_image_in_ollamas_shape(app_client):
    # A node hands `messages` straight to its own Ollama, so that is the shape it gets.
    app, client = app_client
    _only_node(app, "relay_link", "remote-llava")
    relay = AsyncMock(return_value={"ok": True, "data": {"content": "red"}})
    with patch.object(app.state.relay_hub, "request", new=relay):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "remote-llava", "messages": [IMAGE_MESSAGE]})
    assert r.status_code == 200, r.text
    sent = relay.call_args.args[2]["messages"]
    assert sent == [{"role": "user", "content": "What colour is this?", "images": ["iVBORw0KGgo="]}]


def test_a_text_only_route_refuses_images_instead_of_dropping_them(app_client):
    app, client = app_client
    _only_node(app, "homepilot", "persona:atlas")
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "persona:atlas", "messages": [IMAGE_MESSAGE]})
    assert r.status_code == 501, r.text
    assert "cannot carry images" in r.text


# ── requests relayed by OllaBridge Cloud ────────────────────────────────────

# The Cloud relays to this gateway in Ollama's shape: text in `content`, base64 in `images`.
CLOUD_SHAPED = {"role": "user", "content": "What colour is this?", "images": ["iVBORw0KGgo="]}


def test_cloud_shaped_images_are_folded_into_content_parts():
    content = message_content.with_images("What colour is this?", ["iVBORw0KGgo="])
    assert content == IMAGE_MESSAGE["content"]
    assert message_content.with_images("hi", []) == "hi"
    assert message_content.with_images("x", ["/9j/4AAQ"])[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_a_cloud_relayed_image_reaches_open_webui(app_client):
    # Before: the gateway's message model had no `images` field, so the picture was dropped
    # on arrival and a vision model behind Open WebUI answered without it.
    app, client = app_client
    router = FakeProviderRouter()
    app.state.provider_router = router
    r = client.post("/v1/chat/completions", headers={**AUTH, "X-OllaBridge-Relay": "1"},
                    json={"model": "openwebui/internal-gemma4-31b", "messages": [CLOUD_SHAPED]})
    assert r.status_code == 200, r.text
    assert router.messages == [IMAGE_MESSAGE]


def test_a_cloud_relayed_image_reaches_local_ollama(app_client):
    _, client = app_client
    chat = AsyncMock(return_value="red")
    with patch("ollabridge.providers.ollama_client.chat", new=chat):
        r = client.post("/v1/chat/completions", headers=AUTH,
                        json={"model": "llava", "messages": [CLOUD_SHAPED]})
    assert r.status_code == 200, r.text
    assert chat.call_args.kwargs["messages"] == [CLOUD_SHAPED]
