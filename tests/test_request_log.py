"""Request-log persistence must never fail a request.

Regression for a bare ``500 Internal Server Error`` on every
``/v1/chat/completions`` call under SQLModel >= 0.0.48 (Python 3.14 venv):
its ``UTCDateTime`` column type rejects naive datetimes at bind time, the
``RequestLog`` row used ``datetime.utcnow`` (naive), so the success path
crashed on ``commit()``, and the error handler crashed again on its own
``commit()`` -- turning a perfectly good upstream answer into a 500 with no
JSON body. Two guarantees are pinned here: timestamps are timezone-aware, and
a broken request-log write is logged, not raised.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from ollabridge.core.registry import RuntimeNodeState
from ollabridge.core.settings import settings
from ollabridge.db.models import RequestLog, RuntimeNode


def test_model_timestamps_are_timezone_aware():
    assert RequestLog(path="/v1/chat/completions").ts.tzinfo is not None
    assert RequestLog(path="/x").ts.utcoffset() is not None
    assert RuntimeNode(node_id="n1", connector="local_ollama").last_seen.tzinfo is timezone.utc


def test_request_log_row_round_trips_with_installed_sqlmodel(tmp_path):
    """Insert through the real SQLModel column type of whatever version is
    installed. On 0.0.48+ a naive default raises ValueError here."""
    engine = create_engine(f"sqlite:///{tmp_path / 'req.sqlite'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(RequestLog(path="/v1/chat/completions", model="openwebui/x", latency_ms=7, ok=True))
        s.commit()
    with Session(engine) as s:
        rows = s.exec(select(RequestLog).order_by(RequestLog.ts.desc())).all()
    assert len(rows) == 1
    assert rows[0].model == "openwebui/x"
    assert rows[0].ts is not None


def _fake_request(path: str = "/v1/chat/completions"):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_log_request_swallows_database_errors(monkeypatch, caplog):
    from ollabridge.api import main as api_main

    def broken_session():
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(api_main, "session", broken_session)
    with caplog.at_level(logging.WARNING, logger="ollabridge"):
        # Must not raise.
        api_main._log_request(_fake_request(), model="m", latency_ms=1, ok=True)
    assert any("request log write failed" in r.getMessage() for r in caplog.records)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
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


def test_chat_answer_survives_broken_request_log(client, monkeypatch):
    """The upstream answered; a failing telemetry write must not hide it."""
    from ollabridge.api import main as api_main

    def broken_session():
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(api_main, "session", broken_session)
    with patch(
        "ollabridge.providers.ollama_client.chat",
        new=AsyncMock(return_value="pong"),
    ):
        r = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "llama3", "messages": [{"role": "user", "content": "ping"}]},
        )
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "pong"


def test_upstream_error_is_reported_even_when_request_log_is_broken(client, monkeypatch):
    """The real upstream error must reach the client as a JSON 500, not be
    replaced by a second exception from the error handler's own logging."""
    from ollabridge.api import main as api_main

    def broken_session():
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(api_main, "session", broken_session)
    with patch(
        "ollabridge.providers.ollama_client.chat",
        new=AsyncMock(side_effect=RuntimeError("upstream exploded")),
    ):
        r = client.post(
            "/v1/chat/completions",
            headers=AUTH,
            json={"model": "llama3", "messages": [{"role": "user", "content": "ping"}]},
        )
    assert r.status_code == 500
    assert r.json()["detail"] == "upstream exploded"
