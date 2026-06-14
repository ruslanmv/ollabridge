"""Doctor checks against a mocked OllaBridge Cloud (no real network)."""

from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import patch

import httpx
import pytest

from ollabridge.cloud.device_config import (
    CloudDeviceCredentials,
    save_cloud_device_credentials,
)
from ollabridge.doctor import checks
from ollabridge.doctor.models import CheckStatus

GOOD_TOKEN = "dvt_goodtoken12345678901234567890"


@pytest.fixture
def mock_cloud_ws():
    """A WebSocket server speaking the cloud relay protocol (hello/ping/pong)."""
    started = threading.Event()
    stop_holder: dict = {}

    async def handler(ws):
        auth = ws.request.headers.get("Authorization", "")
        if auth != f"Bearer {GOOD_TOKEN}":
            await ws.close(code=4401, reason="Invalid token")
            return
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong"}))

    def run() -> None:
        async def main() -> None:
            from websockets.asyncio.server import serve

            async with serve(handler, "127.0.0.1", 0) as server:
                stop_holder["port"] = server.sockets[0].getsockname()[1]
                stop_holder["stop"] = asyncio.Event()
                stop_holder["loop"] = asyncio.get_running_loop()
                started.set()
                await stop_holder["stop"].wait()

        asyncio.run(main())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    assert started.wait(timeout=10), "mock cloud did not start"
    yield f"ws://127.0.0.1:{stop_holder['port']}"
    stop_holder["loop"].call_soon_threadsafe(stop_holder["stop"].set)
    t.join(timeout=5)


def _pair(cloud_url: str, token: str = GOOD_TOKEN) -> None:
    save_cloud_device_credentials(
        CloudDeviceCredentials(
            cloud_url=cloud_url,
            device_id="dev_test",
            device_token=token,
        )
    )


def _no_local_models():
    return patch.object(checks, "_local_models", lambda: ["llama3.1:8b"])


def test_relay_check_happy_path(mock_cloud_ws):
    _pair(mock_cloud_ws)
    with _no_local_models():
        sec = checks.check_relay(timeout=5)
    by_name = {c.name: c for c in sec.checks}
    assert by_name["WSS connection established"].status == CheckStatus.OK
    assert by_name["Device registered"].status == CheckStatus.OK
    assert by_name["Model list sent"].status == CheckStatus.OK
    assert by_name["Ping/pong"].status == CheckStatus.OK
    assert by_name["Reconnect test"].status == CheckStatus.OK
    # Without a cloud API key, the cloud-side model check is skipped honestly.
    assert by_name["Cloud /v1/models includes local models"].status == CheckStatus.SKIP


def test_relay_check_rejected_token(mock_cloud_ws):
    _pair(mock_cloud_ws, token="dvt_expiredtoken1234567890123456")
    with _no_local_models():
        sec = checks.check_relay(timeout=5)
    failed = [c for c in sec.checks if c.status == CheckStatus.FAIL]
    assert failed, sec
    assert "login" in failed[0].hint


def test_relay_check_cloud_unreachable():
    _pair("ws://127.0.0.1:1")  # nothing listens on port 1
    with _no_local_models():
        sec = checks.check_relay(timeout=3)
    assert any(c.status == CheckStatus.FAIL for c in sec.checks)


def test_relay_check_without_credentials():
    sec = checks.check_relay()
    assert sec.checks[0].status == CheckStatus.FAIL
    assert "login" in sec.checks[0].hint


def test_cloud_check_without_credentials():
    sec = checks.check_cloud()
    assert sec.checks[0].status == CheckStatus.FAIL
    assert any("optional" in n for n in sec.notes)


def test_relay_ws_url_normalization():
    f = checks._relay_ws_url
    assert f("https://api.example.com") == "wss://api.example.com/relay/connect"
    assert f("http://localhost:8000") == "ws://localhost:8000/relay/connect"
    assert f("wss://x.io/relay/connect") == "wss://x.io/relay/connect"
    assert f("api.example.com") == "wss://api.example.com/relay/connect"


# ── e2e (mocked HTTP) ───────────────────────────────────────────────────


def _fake_chat_response(latency_marker: str):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 1},
            "id": latency_marker,
        },
        request=httpx.Request("POST", "http://x/v1/chat/completions"),
    )


def test_e2e_local_path_with_mock(monkeypatch):
    from ollabridge.doctor import e2e

    monkeypatch.setenv("API_KEYS", "test-key-123456")
    monkeypatch.setattr(checks, "_local_models", lambda: ["llama3.1:8b"])
    monkeypatch.setattr(e2e, "_local_models", lambda: ["llama3.1:8b"], raising=False)

    with patch(
        "httpx.post",
        lambda url, json=None, headers=None, timeout=None: _fake_chat_response("local"),
    ):
        sec = e2e.check_e2e(port=11435)
    by_name = {c.name: c for c in sec.checks}
    assert by_name["Local request path"].status == CheckStatus.OK
    assert by_name["Local request path"].data.get("tokens_in") == 7
    # Not paired → cloud leg is skipped with an explanation.
    assert by_name["Cloud relay path"].status == CheckStatus.SKIP


def test_e2e_fails_without_local_models(monkeypatch):
    from ollabridge.doctor import e2e

    monkeypatch.setattr(checks, "_local_models", lambda: [])
    monkeypatch.setattr(e2e, "_local_models", lambda: [], raising=False)
    sec = e2e.check_e2e(port=11435)
    assert sec.checks[0].status == CheckStatus.FAIL
    assert "ollama pull" in sec.checks[0].hint
