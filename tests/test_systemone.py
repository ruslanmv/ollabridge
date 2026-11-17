"""``POST /v1/systemone``: decision requests passed through to Ollama.

The route's promise is that a client written against Ollama works against the
gateway by changing the URL only: the body goes to Ollama unchanged, Ollama's
status and body come back unchanged, and the gateway's own failures (no key,
Ollama down, Ollama too slow) are told apart from Ollama's.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from ollabridge.api import systemone_routes as so
from ollabridge.core import runtime_settings as rts
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}
URL = "http://localhost:11434"
REQUEST = {
    "model": "clef-flash-8k",
    "state": {"conversation": "Customer: how do I reset my mailbox password?"},
    "questions": {
        "is_request": {"type": "noul", "instructions": "Is `conversation` a customer request?"},
        "category": {
            "type": "choice",
            "instructions": "Which topic?",
            "criteria": {"email": "Mailboxes", "domains": "Domain names"},
        },
    },
}
ANSWER = {
    "answers": {
        "is_request": {"type": "noul", "noul": 0.97},
        "category": {
            "type": "choice",
            "choice": "email",
            "probabilities": {"email": 0.91, "domains": 0.09},
        },
    }
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", URL)
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")
    monkeypatch.delenv("SYSTEMONE_TIMEOUT_S", raising=False)
    yield
    monkeypatch.setattr(rts, "_cache", None)


@pytest.fixture
def client():
    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _ollama(monkeypatch, status: int = 200, body=ANSWER, text: str | None = None):
    """Replace the call to Ollama; returns the list of calls it received."""
    calls: list[dict] = []

    async def post(url, payload, timeout_s):
        calls.append({"url": url, "payload": payload, "timeout_s": timeout_s})
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(so, "_post_to_ollama", post)
    return calls


def _raising(monkeypatch, exc: Exception):
    async def post(url, payload, timeout_s):
        raise exc

    monkeypatch.setattr(so, "_post_to_ollama", post)


def test_request_and_answer_pass_through_unchanged(client, monkeypatch):
    calls = _ollama(monkeypatch)
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == ANSWER
    assert calls == [
        {"url": f"{URL}/v1/systemone", "payload": REQUEST, "timeout_s": so.DEFAULT_TIMEOUT_S}
    ]


def test_the_api_key_is_required(client, monkeypatch):
    calls = _ollama(monkeypatch)
    assert client.post("/v1/systemone", json=REQUEST).status_code == 401
    wrong = {"Authorization": "Bearer not-the-key"}
    assert client.post("/v1/systemone", json=REQUEST, headers=wrong).status_code == 401
    assert calls == []


def test_x_api_key_header_is_accepted(client, monkeypatch):
    _ollama(monkeypatch)
    r = client.post("/v1/systemone", json=REQUEST, headers={"X-API-Key": "test-key-abc"})
    assert r.status_code == 200, r.text


def test_the_saved_ollama_address_is_used(client, monkeypatch):
    calls = _ollama(monkeypatch)
    rts.update({"ollama_base_url": "http://172.29.80.1:11434/"})
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 200, r.text
    assert calls[0]["url"] == "http://172.29.80.1:11434/v1/systemone"


def test_a_model_that_is_not_installed_stays_ollamas_404(client, monkeypatch):
    _ollama(monkeypatch, status=404, body={"error": "model 'clef-flash-8k' not found"})
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"error": "model 'clef-flash-8k' not found"}


def test_a_model_that_failed_to_load_stays_ollamas_500(client, monkeypatch):
    _ollama(monkeypatch, status=500, body={"error": "llama-server process has terminated"})
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 500
    assert r.json() == {"error": "llama-server process has terminated"}


def test_ollama_down_is_a_502_that_names_the_address(client, monkeypatch):
    _raising(monkeypatch, httpx.ConnectError("Connection refused"))
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 502
    error = r.json()["detail"]["error"]
    assert error["code"] == "ollama_unreachable"
    assert error["base_url"] == URL


def test_a_slow_ollama_is_a_504(client, monkeypatch):
    monkeypatch.setenv("SYSTEMONE_TIMEOUT_S", "7")
    _raising(monkeypatch, httpx.ReadTimeout("timed out"))
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 504
    error = r.json()["detail"]["error"]
    assert error["code"] == "ollama_timeout"
    assert "7 s" in error["message"]


def test_the_timeout_setting_reaches_the_call(client, monkeypatch):
    calls = _ollama(monkeypatch)
    monkeypatch.setenv("SYSTEMONE_TIMEOUT_S", "45")
    client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    monkeypatch.setenv("SYSTEMONE_TIMEOUT_S", "not a number")
    client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    monkeypatch.setenv("SYSTEMONE_TIMEOUT_S", "-3")
    client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert [c["timeout_s"] for c in calls] == [45.0, so.DEFAULT_TIMEOUT_S, so.DEFAULT_TIMEOUT_S]


def test_a_body_that_is_not_json_from_ollama_is_a_502(client, monkeypatch):
    _ollama(monkeypatch, status=502, text="<html>Bad Gateway</html>")
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 502
    assert r.json()["detail"]["error"]["code"] == "ollama_bad_response"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ([1, 2], "invalid_request"),
        ({"state": {}, "questions": {"q": {"type": "noul"}}}, "missing_model"),
        ({"model": "  ", "questions": {"q": {"type": "noul"}}}, "missing_model"),
        ({"model": "clef-flash-8k", "state": {}}, "missing_questions"),
        ({"model": "clef-flash-8k", "questions": {}}, "missing_questions"),
    ],
)
def test_a_malformed_request_never_reaches_ollama(client, monkeypatch, body, code):
    calls = _ollama(monkeypatch)
    r = client.post("/v1/systemone", json=body, headers=AUTH)
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == code
    assert calls == []


def test_unreadable_json_is_a_400(client, monkeypatch):
    calls = _ollama(monkeypatch)
    r = client.post(
        "/v1/systemone", content=b"{not json", headers={**AUTH, "Content-Type": "application/json"}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"]["code"] == "invalid_json"
    assert calls == []
