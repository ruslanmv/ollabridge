"""Custom request headers on a Generic OpenAI-compatible source.

Some gateways ask every caller to identify itself with headers of their own
(a user id, a client app id) next to the API key. The source stores them as
one ``Name: value`` per line and sends them on discovery, on the key probe
and on chat — never in place of the credential OllaBridge sets itself.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ollabridge.addons.providers.adapters.openai_compatible import (
    OpenAICompatibleAdapter,
)
from ollabridge.addons.providers.services import dynamic_source_sync as dss
from ollabridge.core.settings import settings
from ollabridge.provider_ops import set_secret
from ollabridge.provider_ops import test_provider as probe_provider
from ollabridge.providers_meta import (
    HEADERS_FIELD,
    ProviderRecord,
    extra_fields_for,
    format_header_lines,
    get_record,
    parse_header_lines,
    upsert_record,
)

BASE = "https://llm.example.com/v1"
HEADERS = "x-client-app-id: ollabridge\nx-user: someone@example.com"


def _custom_record(headers: str = HEADERS) -> ProviderRecord:
    return ProviderRecord(
        name="custom", kind="custom", base_url=BASE, extra={HEADERS_FIELD: headers}
    )


# ── Parsing ─────────────────────────────────────────────────


def test_custom_source_declares_an_optional_advanced_headers_field():
    fields = {f.name: f for f in extra_fields_for("custom")}
    assert fields[HEADERS_FIELD].widget == "headers"
    assert fields[HEADERS_FIELD].advanced is True
    assert fields[HEADERS_FIELD].required is False


def test_header_lines_parse_into_a_dict():
    text = "# who is calling\nx-client-app-id: ollabridge\n\nx-user:  a@b.example \n"
    assert parse_header_lines(text) == {
        "x-client-app-id": "ollabridge",
        "x-user": "a@b.example",
    }


def test_a_later_line_replaces_an_earlier_one_case_insensitively():
    assert parse_header_lines("X-User: old\nx-user: new") == {"x-user": "new"}


def test_a_value_may_contain_colons():
    assert parse_header_lines("x-trace: a:b:c") == {"x-trace": "a:b:c"}


@pytest.mark.parametrize("line", ["no colon here", ": value", "bad name: v"])
def test_a_malformed_line_is_refused(line):
    with pytest.raises(ValueError, match="Name: value"):
        parse_header_lines(line)


@pytest.mark.parametrize("name", ["Authorization", "x-api-key", "Content-Type", "Host"])
def test_headers_ollabridge_sets_itself_are_refused(name):
    with pytest.raises(ValueError, match="cannot be set here"):
        parse_header_lines(f"{name}: anything")


def test_quoted_lines_pasted_from_provider_docs_parse():
    """Docs print headers as JSON pairs, often indented, with trailing commas."""
    text = (
        '  "x-team-user": "someone@example.com"\n'
        "  'x-other-user': 'someone@example.com',\n"
        '  "x-client-app-id": "my-app",\n'
    )
    assert parse_header_lines(text) == {
        "x-team-user": "someone@example.com",
        "x-other-user": "someone@example.com",
        "x-client-app-id": "my-app",
    }


def test_a_whole_json_object_parses():
    one_line = '{"x-user": "a@b.example", "x-client-app-id": "my-app"}'
    multi_line = '{\n  "x-user": "a@b.example",\n  "x-client-app-id": "my-app"\n}'
    expected = {"x-user": "a@b.example", "x-client-app-id": "my-app"}
    assert parse_header_lines(one_line) == expected
    assert parse_header_lines(multi_line) == expected


def test_a_quoted_value_keeps_its_inner_commas():
    assert parse_header_lines('"x-tags": "a, b",') == {"x-tags": "a, b"}


def test_json_cannot_smuggle_a_reserved_header_or_line_break():
    with pytest.raises(ValueError, match="cannot be set here"):
        parse_header_lines('{"Authorization": "Bearer x"}')
    with pytest.raises(ValueError, match="line break"):
        parse_header_lines('{"x-user": "a\\nb"}')


def test_canonical_text_round_trips():
    headers = parse_header_lines('"x-user": "a@b.example",\n"x-client-app-id": "my-app"')
    text = format_header_lines(headers)
    assert text == "x-user: a@b.example\nx-client-app-id: my-app"
    assert parse_header_lines(text) == headers


def test_no_headers_configured_is_an_empty_dict():
    assert parse_header_lines(None) == {}
    assert parse_header_lines("") == {}


# ── Adapter ─────────────────────────────────────────────────


def _capture(monkeypatch, status=200, payload=None):
    """Route the OpenAI-compatible client at a mock that records requests."""
    from ollabridge.addons.providers.adapters import openai_compatible as oc

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {"data": []})

    real = oc.httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(oc.httpx, "AsyncClient", _patched)
    return seen


@pytest.mark.asyncio
async def test_build_adapter_sends_the_headers_with_discovery(monkeypatch):
    seen = _capture(monkeypatch, payload={"data": [{"id": "some-model"}]})
    adapter = dss.build_adapter(_custom_record(), "sk-secret")
    assert [m["id"] for m in await adapter.list_models()] == ["some-model"]
    sent = seen[0].headers
    assert sent["x-client-app-id"] == "ollabridge"
    assert sent["x-user"] == "someone@example.com"
    assert sent["authorization"] == "Bearer sk-secret"


@pytest.mark.asyncio
async def test_chat_carries_the_headers_too(monkeypatch):
    seen = _capture(monkeypatch, payload={"choices": []})
    adapter = dss.build_adapter(_custom_record(), "sk-secret")
    await adapter.chat("some-model", [{"role": "user", "content": "hi"}])
    assert seen[0].headers["x-client-app-id"] == "ollabridge"


def test_extra_headers_never_displace_the_credential():
    adapter = OpenAICompatibleAdapter(
        base_url=BASE,
        api_key="sk-secret",
        extra_headers={"Authorization": "Bearer other", "Content-Type": "text/plain"},
    )
    headers = adapter._headers()
    assert headers["Authorization"] == "Bearer sk-secret"
    assert headers["Content-Type"] == "application/json"


def test_a_hand_edited_bad_value_is_ignored_not_fatal():
    adapter = dss.build_adapter(_custom_record("not a header"), "sk-secret")
    assert adapter is not None
    assert adapter.extra_headers == {}


# ── Key probe ───────────────────────────────────────────────


def test_probe_sends_the_headers():
    set_secret("custom", "sk-secret")
    upsert_record(_custom_record())

    def ok(url, headers=None, timeout=None):
        return httpx.Response(200, text="{}", request=httpx.Request("GET", url))

    with patch("httpx.get", side_effect=ok) as get:
        ok_, detail = probe_provider("custom")

    assert ok_ is True, detail
    sent = get.call_args.kwargs["headers"]
    assert sent["x-client-app-id"] == "ollabridge"
    assert sent["Authorization"] == "Bearer sk-secret"


# ── Sources API ─────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")

    from ollabridge.api.sources_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer test-key-abc"}


def _ok_get(url, headers=None, timeout=None):
    return httpx.Response(200, text="{}", request=httpx.Request("GET", url))


def test_upsert_saves_the_headers_and_discovery_sends_them(client, monkeypatch):
    seen = _capture(monkeypatch, payload={"data": [{"id": "some-model"}]})
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/custom",
            headers=AUTH,
            json={"api_key": "sk-secret", "base_url": BASE, "extra": {HEADERS_FIELD: HEADERS}},
        )
    assert r.status_code == 200, r.text
    assert get_record("custom").extra[HEADERS_FIELD] == HEADERS

    fields = {f["name"]: f for f in r.json()["source"]["extra_fields"]}
    assert fields[HEADERS_FIELD]["value"] == HEADERS
    assert fields[HEADERS_FIELD]["widget"] == "headers"
    assert fields[HEADERS_FIELD]["advanced"] is True

    listing = client.get("/admin/sources/custom/models", headers=AUTH)
    assert listing.status_code == 200, listing.text
    assert seen[-1].headers["x-user"] == "someone@example.com"


def test_pasted_json_headers_are_stored_as_plain_lines(client, monkeypatch):
    seen = _capture(monkeypatch, payload={"data": [{"id": "some-model"}]})
    pasted = '  "x-user": "someone@example.com"\n  "x-client-app-id": "my-app"\n'
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/custom",
            headers=AUTH,
            json={"api_key": "sk-secret", "base_url": BASE, "extra": {HEADERS_FIELD: pasted}},
        )
    assert r.status_code == 200, r.text
    stored = "x-user: someone@example.com\nx-client-app-id: my-app"
    assert get_record("custom").extra[HEADERS_FIELD] == stored
    fields = {f["name"]: f for f in r.json()["source"]["extra_fields"]}
    assert fields[HEADERS_FIELD]["value"] == stored

    client.get("/admin/sources/custom/models", headers=AUTH)
    assert seen[-1].headers["x-client-app-id"] == "my-app"


@pytest.mark.parametrize(
    "value,message",
    [
        ("Authorization: Bearer sneaky", "cannot be set here"),
        ("just some words", "Name: value"),
    ],
)
def test_upsert_refuses_bad_headers_and_saves_nothing(client, value, message):
    with patch("ollabridge.provider_ops.httpx.get", _ok_get):
        r = client.post(
            "/admin/sources/custom",
            headers=AUTH,
            json={"api_key": "sk-secret", "base_url": BASE, "extra": {HEADERS_FIELD: value}},
        )
    assert r.status_code == 422
    assert message in r.json()["detail"]
    assert get_record("custom") is None
