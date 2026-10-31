"""Access logging: one line per request, at the level the request deserves.

Observed 2026-10-29 on a gateway with Open WebUI attached: 53 lines in 14
minutes. 50 were health checks, model-list refreshes, a client retrying
without an API key every minute, and a catalog sync reporting "promoted=3" on
every unchanged run; the one chat completion took three lines. Pinned here:

- successful reads are DEBUG; writes and inference are one INFO line carrying
  model, route and tokens; 5xx is ERROR;
- a repeated 4xx is WARN once per client (with the reason), then DEBUG, with
  a count once per window while it keeps happening;
- the provider router's per-attempt lines are DEBUG and its answer reaches
  the request line;
- the local catalog sync is INFO only when the catalog changed.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from ollabridge.api.request_log import RepeatTracker, RequestLogMiddleware
from ollabridge.core.logsetup import uvicorn_logs
from ollabridge.core.logsetup.formatters import JsonFormatter, PlainFormatter
from ollabridge.core.logsetup.request_facts import begin, end, note
from ollabridge.core.logsetup.uvicorn_logs import UvicornFilter

ACCESS = "ollabridge.api.requests"


def _records(caplog):
    return [r for r in caplog.records if r.name == ACCESS]


def _app(tracker: RepeatTracker | None = None) -> FastAPI:
    app = FastAPI()

    @app.api_route("/ping", methods=["GET", "HEAD"])
    async def ping():
        return {"ok": True}

    @app.post("/work")
    async def work():
        note(model="qwen3-8b", route="openwebui", tokens=42)
        return JSONResponse({"ok": True}, headers={"X-Request-ID": "req_40c4fb35aa001122"})

    @app.get("/secret")
    async def secret():
        note(reason="no API key sent")
        raise HTTPException(status_code=401)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaput")

    app.add_middleware(RequestLogMiddleware, tracker=tracker or RepeatTracker())
    return app


@pytest.fixture
def capture(caplog):
    caplog.set_level(logging.DEBUG, logger=ACCESS)
    return caplog


# --- levels ------------------------------------------------------------------------


def test_successful_reads_are_debug(capture):
    with TestClient(_app()) as client:
        client.get("/ping")
        client.head("/ping")
    levels = [(r.levelno, r.getMessage().split(" ")[:3]) for r in _records(capture)]
    assert levels == [
        (logging.DEBUG, ["GET", "/ping", "200"]),
        (logging.DEBUG, ["HEAD", "/ping", "200"]),
    ]


def test_inference_is_one_info_line_with_what_the_handlers_noted(capture):
    with TestClient(_app()) as client:
        client.post("/work")
    (record,) = _records(capture)
    assert record.levelno == logging.INFO
    assert record.getMessage().startswith("POST /work 200 ")
    assert (record.model, record.route, record.tokens) == ("qwen3-8b", "openwebui", "42")
    assert record.request_id == "req_40c4fb35aa001122"
    line = PlainFormatter(utc=True).format(record)
    assert line.endswith("req=40c4fb35 model=qwen3-8b route=openwebui tokens=42 client=testclient")
    assert "method=" not in line and "latency_ms=" not in line  # JSON-only fields
    import json

    obj = json.loads(JsonFormatter().format(record))
    assert (obj["method"], obj["path"], obj["status"]) == ("POST", "/work", 200)
    assert isinstance(obj["latency_ms"], int)


def test_server_errors_are_error(capture):
    with TestClient(_app(), raise_server_exceptions=False) as client:
        assert client.get("/boom").status_code == 500
    (record,) = _records(capture)
    assert record.levelno == logging.ERROR
    assert record.getMessage().startswith("GET /boom 500 ")


# --- repeated client errors ------------------------------------------------------


def test_a_repeated_client_error_is_loud_once_then_counted(capture):
    now = [1000.0]
    tracker = RepeatTracker(window_s=600, clock=lambda: now[0], wall=lambda: 1_793_259_860.0)
    with TestClient(_app(tracker)) as client:
        for _ in range(3):
            client.get("/secret")
        now[0] += 601  # the window passes while the client keeps failing
        client.get("/secret")
    records = _records(capture)
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG, logging.DEBUG, logging.WARNING]
    first, last = records[0].getMessage(), records[-1].getMessage()
    assert first.startswith("GET /secret 401 ")
    assert "no API key sent" in first and "summarised every 10m" in first
    assert "no API key sent (2 more since " in last


def test_404s_from_one_client_share_one_warning(capture):
    with TestClient(_app()) as client:
        for path in ("/a", "/b", "/wp-login.php"):
            client.get(path)
    assert [r.levelno for r in _records(capture)] == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_uvicorn_access_lines_are_dropped_once_the_app_logs_requests(monkeypatch):
    monkeypatch.setattr(uvicorn_logs, "APP_LOGS_REQUESTS", True)
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/health", "1.1", 200), None,
    )
    assert UvicornFilter(started=0.0).filter(record) is False


# --- the real app ----------------------------------------------------------------


@pytest.fixture
def gateway(monkeypatch):
    from ollabridge.core.registry import RuntimeNodeState
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        app.state.provider_router = None
        asyncio.run(
            app.state.obridge.registry.upsert(
                RuntimeNodeState(
                    node_id="local", connector="local_ollama", endpoint="http://localhost:11434",
                    tags=["local"], models=[], capacity=1, meta={},
                )
            )
        )
        yield client


def test_auth_failures_name_the_reason_and_health_checks_stay_quiet(gateway, capture):
    gateway.get("/health")
    gateway.get("/v1/models")
    gateway.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
    records = _records(capture)
    assert [r.levelno for r in records] == [logging.DEBUG, logging.WARNING, logging.WARNING]
    assert "no API key sent" in records[1].getMessage()
    assert "API key not accepted" in records[2].getMessage()
    assert "wrong-key" not in " ".join(r.getMessage() for r in records)


class _NoCandidates:
    """A loaded provider add-on that serves none of the requested models."""

    def resolve(self, model):
        return []


class _FailingProvider:
    def resolve(self, model):
        return ["groq-free"]

    async def route_chat(self, model, messages, **kwargs):
        raise RuntimeError("provider down")


@pytest.mark.parametrize(("router", "fallback"), [(_NoCandidates(), None), (_FailingProvider(), True)])
def test_fallback_is_shown_only_when_a_provider_was_tried(gateway, capture, router, fallback):
    gateway.app.state.provider_router = router
    with patch("ollabridge.providers.ollama_client.chat", new=AsyncMock(return_value="ok")):
        r = gateway.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key-abc"},
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200
    (record,) = [rec for rec in _records(capture) if rec.levelno >= logging.INFO]
    assert getattr(record, "fallback", None) is fallback


def test_a_chat_completion_is_one_line_with_model_route_and_tokens(gateway, capture):
    with patch("ollabridge.providers.ollama_client.chat", new=AsyncMock(return_value="hello back")):
        r = gateway.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key-abc"},
            json={"model": "llama3", "messages": [{"role": "user", "content": "hi there"}]},
        )
    assert r.status_code == 200
    info = [rec for rec in _records(capture) if rec.levelno >= logging.INFO]
    assert len(info) == 1
    (record,) = info
    assert record.getMessage().startswith("POST /v1/chat/completions 200 ")
    assert (record.model, record.route) == ("llama3", "ollama/local")
    assert record.tokens.startswith("~")  # Ollama's path reports an estimate
    assert record.request_id == r.headers["X-Request-ID"]


# --- provider router ---------------------------------------------------------------


def test_router_attempts_are_debug_and_the_answer_reaches_the_request_line(caplog):
    from ollabridge.addons.providers.adapters.gemini import GeminiAdapter
    from ollabridge.addons.providers.models import (
        HealthStatus,
        ProviderCategory,
        ProviderConfig,
        ProviderTier,
    )
    from ollabridge.addons.providers.registry import ProviderRegistry
    from ollabridge.addons.providers.router import ProviderRouter

    caplog.set_level(logging.DEBUG, logger="ollabridge.addons.providers.router")

    async def run() -> dict:
        reg = ProviderRegistry()
        cfg = ProviderConfig(
            id="gemini-free", name="Gemini", kind="gemini", enabled=True,
            tier=ProviderTier.MAIN, category=ProviderCategory.FREE,
            base_url="https://generativelanguage.googleapis.com", credential_env="GEMINI_API_KEY",
        )
        adapter = GeminiAdapter(base_url=cfg.base_url, api_key="AIza-test-only")
        adapter.chat = AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}], "usage": {"total_tokens": 42}})
        await reg.register(cfg, adapter)
        await reg.update_health("gemini-free", HealthStatus.HEALTHY)
        facts, token = begin()
        try:
            await ProviderRouter(reg).route_chat("gemini-2.5-flash", [{"role": "user", "content": "hi"}])
        finally:
            end(token)
        return facts

    facts = asyncio.run(run())
    assert (facts["route"], facts["tokens"]) == ("gemini-free", 42)
    router_records = [r for r in caplog.records if r.name == "ollabridge.addons.providers.router"]
    assert router_records and all(r.levelno == logging.DEBUG for r in router_records)


# --- local catalog sync ------------------------------------------------------------


def test_catalog_sync_is_info_only_when_the_catalog_changed(tmp_path, caplog):
    from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
    from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService
    from test_local_catalog import _StubClient, _tag

    caplog.set_level(logging.DEBUG, logger="ollabridge.addons.local_catalog")
    repo = LocalCatalogRepository(path=tmp_path / "cat.yaml")
    svc = LocalCatalogSyncService(repository=repo, alias_path=tmp_path / "aliases.yaml", enrich_with_show=False)
    tags = [_tag("qwen2.5:14b"), _tag("llama3.1:8b")]

    def sync() -> list[logging.LogRecord]:
        caplog.clear()
        result = asyncio.run(svc.sync_node(node_id="n", client=_StubClient(tags), auto_enable_top=2))
        assert result.ok is True
        return [
            r for r in caplog.records
            if r.name == "ollabridge.addons.local_catalog.sync_service" and r.levelno >= logging.INFO
        ]

    (first,) = sync()
    assert first.getMessage().startswith("Local catalog changed on node n: 2 added, 2 promoted to top (2 models, ")
    assert sync() == []  # unchanged: DEBUG only
    assert repo.last_sync("n").promoted_to_top == 0  # and nothing "promoted" again
    tags.append(_tag("phi3:mini"))
    (added,) = sync()
    assert added.getMessage().startswith("Local catalog changed on node n: 1 added")
