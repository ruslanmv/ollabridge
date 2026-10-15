"""The Ollama base URL saved on the Local Runtimes page must drive every
Ollama call, and an unreachable Ollama must say which address it tried.

Background: the server can run in WSL while Ollama runs on the Windows host.
The UI is pointed at the host address and "Test Connection" passes, but chat,
embeddings, /v1/models and Models & Access kept reading the env default
(localhost:11434), so every request failed with an opaque
RetryError[<Future ... raised ConnectError>].
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from tenacity import wait_none

from ollabridge.core import runtime_settings as rts
from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings
from ollabridge.providers import ollama_client

# What a WSL user saves: the Windows host as seen from the WSL VM.
SAVED = "http://172.29.80.1:11434"
ENV_DEFAULT = "http://localhost:11434"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """A private runtime-settings store per test, no retry back-off, and the
    env default pinned so the assertions do not depend on the machine's .env."""
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", ENV_DEFAULT)
    monkeypatch.setattr(ollama_client._post_json.retry, "wait", wait_none())
    yield
    monkeypatch.setattr(rts, "_cache", None)


class FakeOllama:
    """Stands in for an Ollama server behind httpx and records every URL hit."""

    def __init__(self, *, reachable: bool = True, models=("llama3:8b", "qwen2.5:0.5b")):
        self.reachable = reachable
        self.models = list(models)
        self.urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        if not self.reachable:
            raise httpx.ConnectError("All connection attempts failed", request=request)
        path = request.url.path
        if path.endswith("/api/chat"):
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": "hi from the host"}}
            )
        if path.endswith("/api/embeddings"):
            return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        if path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        return httpx.Response(404, json={"error": "unknown path"})

    def install(self, monkeypatch) -> "FakeOllama":
        monkeypatch.setattr(
            ollama_client,
            "_client",
            lambda timeout: httpx.AsyncClient(
                transport=httpx.MockTransport(self.handler), timeout=timeout
            ),
        )
        return self


# ── the resolver ──────────────────────────────────────────────────────────


def test_resolver_falls_back_to_the_env_setting_when_nothing_is_saved():
    assert not rts.has_saved_settings()
    assert rts.ollama_base_url() == ENV_DEFAULT


def test_resolver_follows_a_live_change_of_the_env_setting(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://env-host:11434/")
    assert rts.ollama_base_url() == "http://env-host:11434"


def test_resolver_prefers_the_saved_value_and_strips_the_trailing_slash():
    rts.update({"ollama_base_url": SAVED + "/"})
    assert rts.ollama_base_url() == SAVED


def test_resolver_treats_a_blank_saved_value_as_unset():
    rts.update({"ollama_base_url": "   "})
    assert rts.ollama_base_url() == ENV_DEFAULT


# ── the client honours the saved URL ─────────────────────────────────────


def test_chat_posts_to_the_saved_url(monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama().install(monkeypatch)
    out = asyncio.run(ollama_client.chat("llama3", [{"role": "user", "content": "hi"}]))
    assert out == "hi from the host"
    assert fake.urls == [f"{SAVED}/api/chat"]


def test_chat_uses_the_env_default_until_a_url_is_saved(monkeypatch):
    fake = FakeOllama().install(monkeypatch)
    asyncio.run(ollama_client.chat("llama3", [{"role": "user", "content": "hi"}]))
    assert fake.urls == [f"{ENV_DEFAULT}/api/chat"]


def test_embeddings_post_to_the_saved_url(monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama().install(monkeypatch)
    vec = asyncio.run(ollama_client.embeddings("nomic-embed-text", "hello"))
    assert vec == [0.1, 0.2, 0.3]
    assert fake.urls == [f"{SAVED}/api/embeddings"]


def test_list_models_reads_tags_from_the_saved_url(monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama().install(monkeypatch)
    assert asyncio.run(ollama_client.list_models()) == ["llama3:8b", "qwen2.5:0.5b"]
    assert fake.urls == [f"{SAVED}/api/tags"]


def test_list_models_failure_is_empty_but_names_the_address(monkeypatch, caplog):
    rts.update({"ollama_base_url": SAVED})
    FakeOllama(reachable=False).install(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="ollabridge"):
        assert asyncio.run(ollama_client.list_models()) == []
    assert SAVED in caplog.text


def test_model_access_inventory_reads_the_saved_url():
    from ollabridge.api import model_access_routes

    rts.update({"ollama_base_url": SAVED})
    seen: list[str] = []

    def fake_get(url, timeout=None):
        seen.append(url)
        return httpx.Response(
            200, json={"models": [{"name": "llama3:8b"}]}, request=httpx.Request("GET", url)
        )

    with patch("ollabridge.api.model_access_routes.httpx.get", fake_get):
        assert model_access_routes._local_ollama_models() == ["llama3:8b"]
    assert seen == [f"{SAVED}/api/tags"]


# ── an unreachable Ollama is a clear error, not RetryError[<Future ...>] ──


def test_unreachable_ollama_raises_a_clear_error_after_retrying(monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama(reachable=False).install(monkeypatch)
    with pytest.raises(ollama_client.OllamaUnreachable) as info:
        asyncio.run(ollama_client.chat("llama3", [{"role": "user", "content": "hi"}]))
    assert f"Ollama not reachable at {SAVED}" in str(info.value)
    assert "RetryError" not in str(info.value)
    assert info.value.base_url == SAVED
    assert isinstance(info.value.__cause__, httpx.ConnectError)
    # The retry is kept: three attempts before giving up.
    assert len(fake.urls) == 3


# ── through the API ──────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        # Deterministic routing: no provider addon, one local Ollama node.
        app.state.provider_router = None
        asyncio.run(
            app.state.obridge.registry.upsert(
                RuntimeNodeState(
                    node_id="local",
                    connector="local_ollama",
                    endpoint=ENV_DEFAULT,
                    tags=["local"],
                    models=[],
                    capacity=1,
                    meta={},
                )
            )
        )
        yield test_client


AUTH = {"Authorization": "Bearer test-key-abc"}
CHAT = {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]}


def test_chat_endpoint_talks_to_the_saved_url(client, monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama().install(monkeypatch)
    r = client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "hi from the host"
    assert fake.urls == [f"{SAVED}/api/chat"]


def test_chat_endpoint_reports_an_unreachable_ollama_as_502(client, monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    FakeOllama(reachable=False).install(monkeypatch)
    r = client.post("/v1/chat/completions", headers=AUTH, json=CHAT)
    assert r.status_code == 502, r.text
    err = r.json()["detail"]["error"]
    assert f"Ollama not reachable at {SAVED}" in err["message"]
    assert err["code"] == "ollama_unreachable"
    assert err["base_url"] == SAVED
    assert "RetryError" not in r.text
    assert "Future" not in r.text

    from ollabridge.tracing import get_trace_store

    trace = get_trace_store().get(r.headers["X-Request-ID"])
    assert trace is not None
    assert trace.ok is False
    assert trace.error_category == "OllamaUnreachable"


def test_embeddings_endpoint_reports_an_unreachable_ollama_as_502(client, monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    FakeOllama(reachable=False).install(monkeypatch)
    r = client.post(
        "/v1/embeddings", headers=AUTH, json={"model": "nomic-embed-text", "input": "hi"}
    )
    assert r.status_code == 502, r.text
    assert f"Ollama not reachable at {SAVED}" in r.json()["detail"]["error"]["message"]


def test_models_endpoint_lists_from_the_saved_url(client, monkeypatch):
    rts.update({"ollama_base_url": SAVED})
    fake = FakeOllama().install(monkeypatch)
    r = client.get("/v1/models", headers=AUTH)
    assert r.status_code == 200, r.text
    ids = {m["id"] for m in r.json()["data"]}
    assert {"llama3:8b", "qwen2.5:0.5b"} <= ids
    assert f"{SAVED}/api/tags" in fake.urls
