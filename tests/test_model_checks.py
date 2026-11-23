"""Models → Testing: verdicts, the check route and the last-results store."""

from __future__ import annotations

import json

import pytest

from ollabridge import model_checks as mc
from ollabridge.api import model_checks_routes as routes


def _err(code, message="boom"):
    return {"detail": {"error": {"code": code, "message": message}}}


def _ok(content="OK"):
    return {"choices": [{"message": {"content": content}}]}


# ── verdicts ────────────────────────────────────────────────────────────

def test_a_quick_answer_is_working():
    v = mc.verdict(status=200, body=_ok(), latency_ms=1100)
    assert v["verdict"] == "working" and v["reason_code"] == "ok"
    assert v["plain"] == "Answered in 1.1 s."


def test_an_empty_answer_is_working_with_a_note():
    v = mc.verdict(status=200, body=_ok(""), latency_ms=900)
    assert v["verdict"] == "working" and v["reason_code"] == "empty_answer"


@pytest.mark.parametrize("ms,expected", [(15_000, "working"), (15_001, "slow"), (38_000, "slow")])
def test_slow_starts_after_fifteen_seconds(ms, expected):
    assert mc.verdict(status=200, body=_ok(), latency_ms=ms)["verdict"] == expected


def test_our_own_time_limit_is_a_timeout():
    v = mc.verdict(status=None, body=None, latency_ms=60_000, timed_out=True, source="Example Chat")
    assert v["verdict"] == "not_working" and v["reason_code"] == "check_timeout"
    assert "60 s" in v["plain"] and "Example Chat" in v["plain"]


@pytest.mark.parametrize("code,status,words", [
    ("rate_limited", 429, "limiting requests"),
    ("provider_timeout", 504, "No answer in time"),
    ("ollama_unreachable", 502, "Ollama isn't running"),
    ("network_offline", 503, "network or VPN"),
    ("connection_lost", 503, "network or VPN"),
    ("provider_auth", 502, "refused the key"),
    ("provider_unavailable", 502, "unavailable right now"),
    ("tools_unsupported", 400, "can't be used this way"),
    ("something_new", 502, "returned an error"),
])
def test_every_error_code_has_a_plain_sentence(code, status, words):
    v = mc.verdict(status=status, body=_err(code), latency_ms=10, source="Example Chat")
    assert v["verdict"] == "not_working"
    assert v["reason_code"] == code
    assert words in v["plain"]
    assert v["detail"].startswith(f"HTTP {status}:")


def test_no_healthy_deployments_means_retired_and_names_a_successor():
    body = _err("provider_bad_request", "litellm.BadRequestError: There are no healthy deployments for this model")
    v = mc.verdict(status=400, body=body, latency_ms=300, source="Example Chat", model="x/kimi-k3",
                   inventory_ids=["x/kimi-k3", "x/kimi-k3-1-pro", "x/glm-5.3"])
    assert v["verdict"] == "not_working"
    assert "no longer available from Example Chat" in v["plain"]
    assert v["plain"].endswith("Try x/kimi-k3-1-pro.")


def test_detail_is_redacted_and_bounded():
    secret = "sk-" + "a" * 40
    v = mc.verdict(status=502, body=_err("provider_error", f"bad key {secret} " + "x" * 600), latency_ms=5)
    assert secret not in v["detail"]
    assert len(v["detail"]) <= 300


def test_a_plain_fastapi_error_still_maps():
    v = mc.verdict(status=500, body={"detail": "Internal error"}, latency_ms=5)
    assert v["reason_code"] == "http_500"


# ── store ───────────────────────────────────────────────────────────────

def test_the_store_keeps_metadata_only(tmp_path):
    store = mc.CheckStore(tmp_path / "model_checks.json")
    store.save({"model": "m", "verdict": "working", "answer": "SECRET ANSWER", "checked_at": "t"})
    raw = (tmp_path / "model_checks.json").read_text(encoding="utf-8")
    assert "SECRET ANSWER" not in raw and "answer" not in json.loads(raw)["m"]
    store.save({"model": "m", "verdict": "slow"})
    assert store.all()["m"]["verdict"] == "slow"


# ── API ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from ollabridge.api.main import create_app
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "API_KEYS", "test-key")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setattr(routes, "_store", mc.CheckStore(tmp_path / "checks.json"))
    routes._inventory_cache.clear()
    with TestClient(create_app()) as c:
        async def inventory():
            return [{"id": "acme/m1", "source": "open_webui", "source_display_name": "Acme"}], []
        c.app.state.collect_models = inventory
        yield c


KEY = {"X-API-Key": "test-key"}


def test_an_unknown_model_is_refused(client):
    assert client.post("/v1/models/check", json={"model": "nope"}, headers=KEY).status_code == 404
    assert client.post("/v1/models/check", json={"model": "acme/m1"}).status_code == 401


def test_a_check_goes_through_the_chat_route_and_is_remembered(client, monkeypatch):
    seen = {}

    async def fake_chat(request, model):
        seen["model"] = model
        return 200, _ok("OK"), 1200, False

    monkeypatch.setattr(routes, "_ask", fake_chat)
    result = client.post("/v1/models/check", json={"model": "acme/m1"}, headers=KEY).json()
    assert seen == {"model": "acme/m1"}
    assert result["verdict"] == "working" and result["source"] == "Acme"
    assert client.get("/v1/models/checks", headers=KEY).json()["items"]["acme/m1"]["verdict"] == "working"


def test_the_in_process_call_uses_the_fixed_message_and_tags_the_source(client, monkeypatch):
    """The real _ask: posts to this app's own chat route."""
    import httpx

    captured = {}

    async def spy(self, url, json=None, headers=None, **_):
        captured.update(url=url, body=json, app=(headers or {}).get("X-OllaBridge-App"),
                        key=(headers or {}).get("x-api-key"))
        return httpx.Response(200, json=_ok("OK"))

    monkeypatch.setattr(routes.httpx.AsyncClient, "post", spy)
    result = client.post("/v1/models/check", json={"model": "acme/m1"}, headers=KEY).json()
    assert result["verdict"] == "working"
    assert captured["url"] == "/v1/chat/completions"
    assert captured["app"] == "model-check"
    assert captured["key"] == "test-key"  # the caller's own credentials, nothing more
    assert captured["body"]["messages"] == [{"role": "user", "content": mc.CHECK_MESSAGE}]
    assert captured["body"]["max_tokens"] == mc.CHECK_MAX_TOKENS
