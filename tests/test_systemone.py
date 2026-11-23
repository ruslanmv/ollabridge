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
    "model": "decider-8k",
    "state": {"text": "How do I reset my password?"},
    "questions": {
        "is_request": {"type": "noul", "instructions": "Is `text` a question?"},
        "topic": {
            "type": "choice",
            "instructions": "Which topic?",
            "criteria": {"account": "Sign-in and passwords", "orders": "Orders and delivery"},
        },
    },
}
ANSWER = {
    "answers": {
        "is_request": {"type": "noul", "noul": 0.97},
        "topic": {
            "type": "choice",
            "choice": "account",
            "probabilities": {"account": 0.91, "orders": 0.09},
        },
    }
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    monkeypatch.setattr(so, "_ollama_models_cache", {})
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

    async def post(url, payload, timeout_s, headers):
        calls.append({"url": url, "payload": payload, "timeout_s": timeout_s})
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(so, "_post", post)
    return calls


def _raising(monkeypatch, exc: Exception):
    async def post(url, payload, timeout_s, headers):
        raise exc

    monkeypatch.setattr(so, "_post", post)


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
    _ollama(monkeypatch, status=404, body={"error": "model 'decider-8k' not found"})
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 404
    assert r.json() == {"error": "model 'decider-8k' not found"}


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
        ({"model": "decider-8k", "state": {}}, "missing_questions"),
        ({"model": "decider-8k", "questions": {}}, "missing_questions"),
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


# --- sources with a decision endpoint ------------------------------------------

SOURCE_URL = "https://models.example.com/v1"


def _add_source(name="lab", decision="/classify", enabled=True, base_url=SOURCE_URL, headers=""):
    from ollabridge.providers_meta import ProviderRecord, upsert_record

    extra = {"decision_path": decision} if decision else {}
    if headers:
        extra["headers"] = headers
    upsert_record(ProviderRecord(name=name, kind="custom", base_url=base_url, enabled=enabled, extra=extra))


def _hosts(monkeypatch, installed=(), answers=None):
    """Replace both hosts: Ollama's installed models, and what each URL answers."""
    calls: list[dict] = []

    async def models(base):
        return frozenset(installed)

    async def post(url, payload, timeout_s, headers):
        calls.append({"url": url, "model": payload["model"], "headers": headers})
        status, body = (answers or {}).get(url, (200, ANSWER))
        return httpx.Response(status, json=body)

    monkeypatch.setattr(so, "_ollama_models", models)
    monkeypatch.setattr(so, "_post", post)
    monkeypatch.setattr(so, "_secret_for", lambda name: f"key-of-{name}")
    return calls


def test_a_model_ollama_does_not_have_goes_to_the_source(client, monkeypatch):
    _add_source()
    calls = _hosts(monkeypatch, installed={"small-chat:1b"})
    r = client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json() == ANSWER
    assert calls == [
        {
            "url": f"{SOURCE_URL}/classify",
            "model": "decider",
            "headers": {"Authorization": "Bearer key-of-lab"},
        }
    ]


def test_a_model_installed_in_ollama_stays_local(client, monkeypatch):
    _add_source()
    calls = _hosts(monkeypatch, installed={"decider-8k"})
    r = client.post("/v1/systemone", json=REQUEST, headers=AUTH)
    assert r.status_code == 200, r.text
    assert [c["url"] for c in calls] == [f"{URL}/v1/systemone"]
    assert calls[0]["headers"] == {}  # the source's key never goes to Ollama


def test_a_source_prefix_names_the_host_and_is_removed(client, monkeypatch):
    _add_source()
    # Installed locally too: the prefix still wins.
    calls = _hosts(monkeypatch, installed={"decider"})
    r = client.post("/v1/systemone", json={**REQUEST, "model": "lab/decider"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert calls == [
        {"url": f"{SOURCE_URL}/classify", "model": "decider", "headers": {"Authorization": "Bearer key-of-lab"}}
    ]


def test_a_slash_that_names_no_source_is_part_of_the_model(client, monkeypatch):
    _add_source()
    calls = _hosts(monkeypatch, installed={"hf.co/team/model"})
    client.post("/v1/systemone", json={**REQUEST, "model": "hf.co/team/model"}, headers=AUTH)
    assert calls[0]["url"] == f"{URL}/v1/systemone"
    assert calls[0]["model"] == "hf.co/team/model"


def test_the_next_source_is_asked_when_one_does_not_have_the_model(client, monkeypatch):
    _add_source(name="first", base_url="https://one.example.com/v1")
    _add_source(name="second", base_url="https://two.example.com/v1")
    calls = _hosts(
        monkeypatch,
        answers={"https://one.example.com/v1/classify": (404, {"error": {"code": "model_not_found"}})},
    )
    r = client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert [c["url"] for c in calls] == ["https://one.example.com/v1/classify", "https://two.example.com/v1/classify"]
    assert calls[1]["headers"] == {"Authorization": "Bearer key-of-second"}


def test_no_host_has_the_model_is_the_last_404(client, monkeypatch):
    _add_source()
    body = {"error": {"code": "model_not_found", "message": "no such model"}}
    _hosts(monkeypatch, answers={f"{SOURCE_URL}/classify": (404, body)})
    r = client.post("/v1/systemone", json={**REQUEST, "model": "nope"}, headers=AUTH)
    assert r.status_code == 404
    assert r.json() == body


def test_a_sources_error_other_than_404_is_returned_as_it_is(client, monkeypatch):
    _add_source(name="first", base_url="https://one.example.com/v1")
    _add_source(name="second", base_url="https://two.example.com/v1")
    body = {"error": {"code": "rate_limited"}}
    calls = _hosts(monkeypatch, answers={"https://one.example.com/v1/classify": (429, body)})
    r = client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert r.status_code == 429
    assert r.json() == body
    assert len(calls) == 1  # a busy source is not a reason to send the text elsewhere


@pytest.mark.parametrize("kwargs", [{"decision": ""}, {"enabled": False}])
def test_a_source_without_an_endpoint_or_disabled_is_never_asked(client, monkeypatch, kwargs):
    _add_source(**kwargs)
    calls = _hosts(monkeypatch)
    client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert [c["url"] for c in calls] == [f"{URL}/v1/systemone"]


def test_a_full_url_endpoint_and_custom_headers_are_used(client, monkeypatch):
    _add_source(decision="https://answers.example.com/v2/ask", headers="x-client: demo")
    calls = _hosts(monkeypatch)
    client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert calls[0]["url"] == "https://answers.example.com/v2/ask"
    assert calls[0]["headers"] == {"x-client": "demo", "Authorization": "Bearer key-of-lab"}


def test_an_unreachable_source_is_a_502_that_names_it_not_its_address(client, monkeypatch):
    _add_source()
    _hosts(monkeypatch)
    _raising(monkeypatch, httpx.ConnectError("Connection refused"))
    r = client.post("/v1/systemone", json={**REQUEST, "model": "decider"}, headers=AUTH)
    assert r.status_code == 502
    error = r.json()["detail"]["error"]
    assert error["code"] == "upstream_unreachable"
    assert error["source"] == "lab"
    assert "example.com" not in r.text and "key-of-lab" not in r.text


def test_the_decision_endpoint_is_a_field_of_the_generic_source():
    from ollabridge.providers_meta import DECISION_FIELD, ProviderRecord, decision_url, extra_fields_for

    fields = {f.name: f for f in extra_fields_for("custom")}
    assert DECISION_FIELD in fields and fields[DECISION_FIELD].advanced
    rec = ProviderRecord(name="lab", kind="custom", base_url=SOURCE_URL + "/", extra={DECISION_FIELD: "classify"})
    assert decision_url(rec) == f"{SOURCE_URL}/classify"
    assert decision_url(ProviderRecord(name="lab", kind="custom", base_url=SOURCE_URL)) is None
    assert decision_url(ProviderRecord(name="lab", kind="custom", extra={DECISION_FIELD: "/classify"})) is None


def test_the_field_is_offered_when_a_source_points_at_your_own_server():
    from ollabridge.providers_meta import PROVIDER_CATALOG, DECISION_FIELD, ProviderRecord, fields_for_record

    def offered(**kwargs) -> bool:
        return DECISION_FIELD in {f.name for f in fields_for_record(ProviderRecord(**kwargs))}

    usual = PROVIDER_CATALOG["openai"].base_url
    # A public provider at its usual address keeps its short form.
    assert not offered(name="openai", kind="openai", base_url=usual)
    assert not offered(name="openai", kind="openai", base_url=usual + "/")
    assert not offered(name="groq", kind="groq", base_url="")
    # The same kind pointed at a server of your own gets the field.
    assert offered(name="openai", kind="openai", base_url=SOURCE_URL)
    # A kind with its own protocol never does.
    assert not offered(name="anthropic", kind="anthropic", base_url=SOURCE_URL)
    assert not offered(name="watsonx", kind="watsonx", base_url=SOURCE_URL)


def test_the_field_can_be_saved_on_such_a_source():
    from ollabridge.providers_meta import PROVIDER_CATALOG, DECISION_FIELD, ProviderRecord, apply_extras

    own = ProviderRecord(name="openai", kind="openai", base_url=SOURCE_URL)
    assert apply_extras(own, {DECISION_FIELD: "/classify"}) == [DECISION_FIELD]
    assert own.extra == {DECISION_FIELD: "/classify"}
    public = ProviderRecord(name="openai", kind="openai", base_url=PROVIDER_CATALOG["openai"].base_url)
    assert apply_extras(public, {DECISION_FIELD: "/classify"}) == []
    assert public.extra == {}


def test_a_listing_that_states_each_models_kind_is_believed():
    from ollabridge.addons.providers.services import dynamic_source_sync as dss
    from ollabridge.providers_meta import ProviderRecord

    rec = ProviderRecord(name="lab", kind="custom", base_url=SOURCE_URL)
    listing = [
        {"id": "chat-model", "kind": "llm"},
        {"id": "decision-model", "kind": "classifier"},
        {"id": "embedding-model", "kind": "embedding"},
        {"id": "voice-model", "kind": "text_to_speech"},
        {"id": "plain-model"},
    ]
    normalized = dss.normalize_models(rec, listing)
    assert {m["id"]: m["category"] for m in normalized} == {
        "chat-model": "chat",
        "decision-model": "classifier",
        "embedding-model": "embedding",
        "voice-model": "audio",
        "plain-model": "chat",
    }
    chat = {m["id"]: m["capabilities"]["chat"] for m in normalized}
    assert chat["decision-model"] is False and chat["chat-model"] is True
