"""API integration: request IDs, auth rejection, and metadata-only traces."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        # Deterministic routing: bypass the provider addon (its seeded catalog
        # can intercept common model names) and register the local node
        # ourselves instead of relying on the async startup task.
        app.state.provider_router = None
        asyncio.run(
            app.state.obridge.registry.upsert(
                RuntimeNodeState(
                    node_id="local",
                    connector="local_ollama",
                    endpoint="http://localhost:11434",
                    tags=["local"],
                    models=[],
                    capacity=1,
                    meta={},
                )
            )
        )
        yield test_client


AUTH = {"Authorization": "Bearer test-key-abc"}


def test_health_has_request_id_header(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID", "").startswith("req_")


def test_incoming_request_id_is_honored(client):
    r = client.get("/health", headers={"X-Request-ID": "req_custom123"})
    assert r.headers["X-Request-ID"] == "req_custom123"


def test_chat_requires_api_key(client):
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "llama3",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 401


def test_models_requires_api_key(client):
    assert client.get("/v1/models").status_code == 401


def test_wrong_key_rejected(client):
    r = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401


def test_chat_records_metadata_only_trace(client, ollabridge_home):
    secret_prompt = "this prompt is confidential ZX99"
    with patch(
        "ollabridge.providers.ollama_client.chat",
        new=AsyncMock(return_value="hello back"),
    ):
        r = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": secret_prompt}],
            },
        )
    assert r.status_code == 200
    rid = r.headers["X-Request-ID"]

    from ollabridge.tracing import get_trace_store

    trace = get_trace_store().get(rid)
    assert trace is not None
    assert trace.resolved_model == "llama3"
    assert trace.ok is True
    assert trace.cloud_relay is False
    assert trace.latency_ms is not None
    assert trace.tokens_in and trace.tokens_in > 0

    # The trace database must not contain the prompt or the response.
    blob = " ".join(
        str(v)
        for row in sqlite3.connect(ollabridge_home / "traces.db").execute(
            "SELECT * FROM traces"
        )
        for v in row
    )
    assert "confidential" not in blob
    assert "ZX99" not in blob
    assert "hello back" not in blob


def test_relay_header_marks_trace(client):
    with patch(
        "ollabridge.providers.ollama_client.chat", new=AsyncMock(return_value="ok")
    ):
        r = client.post(
            "/v1/chat/completions",
            headers={**AUTH, "X-OllaBridge-Relay": "1"},
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200

    from ollabridge.tracing import get_trace_store

    trace = get_trace_store().get(r.headers["X-Request-ID"])
    assert trace is not None
    assert trace.cloud_relay is True


def test_error_response_is_redacted(client):
    boom = RuntimeError("upstream rejected key sk-ant-secretsecret123456")
    with patch(
        "ollabridge.providers.ollama_client.chat", new=AsyncMock(side_effect=boom)
    ):
        r = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 500
    assert "secretsecret" not in r.text

    from ollabridge.tracing import get_trace_store

    trace = get_trace_store().get(r.headers["X-Request-ID"])
    assert trace is not None
    assert trace.ok is False
    assert trace.error_category == "RuntimeError"


def test_cors_defaults_are_not_wildcard():
    assert settings.CORS_ORIGINS
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    assert "*" not in origins


def test_oversized_request_rejected(client):
    r = client.post(
        "/v1/chat/completions",
        headers={**AUTH, "Content-Length": str(50 * 1024 * 1024)},
        content=b"{}",
    )
    assert r.status_code == 413


def test_root_redirects_to_dashboard_when_ui_built(client):
    # In the repo the frontend is built, so / should send users to the dashboard.
    from ollabridge.api import main as api_main
    from pathlib import Path

    ui_index = (
        Path(api_main.__file__).resolve().parent.parent.parent.parent
        / "frontend"
        / "dist"
        / "index.html"
    )
    r = client.get("/", follow_redirects=False)
    if ui_index.is_file():
        assert r.status_code in (302, 307)
        assert r.headers["location"].rstrip("/").endswith("/ui")
    else:
        assert r.status_code == 200
        assert r.json()["name"]


def test_favicon_never_404s(client):
    r = client.get("/favicon.ico")
    assert r.status_code in (200, 204)
