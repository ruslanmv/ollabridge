from __future__ import annotations

import json

import httpx
import pytest

from ollabridge.cloud import bridge_manager
from ollabridge.cloud import homepilot_image_relay as relay


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send(self, payload):
        self.messages.append(json.loads(payload))


def _mock_httpx(monkeypatch, handler):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(relay.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_relay_capability_uses_local_gateway_and_api_key(monkeypatch):
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "PORT", 11435)
    monkeypatch.setattr(settings, "API_KEYS", "local-key")

    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert (
            str(request.url) == "http://127.0.0.1:11435/v1/media/homepilot/capability"
        )
        assert request.headers["x-api-key"] == "local-key"
        return httpx.Response(200, json={"available": True, "reason": "ok"})

    _mock_httpx(monkeypatch, handler)
    result = await relay.capability()
    assert result == {"available": True, "reason": "ok"}


@pytest.mark.asyncio
async def test_relay_generation_returns_base64_image(monkeypatch):
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "PORT", 11435)
    monkeypatch.setattr(settings, "API_KEYS", "local-key")

    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert request.url.path == "/v1/media/homepilot/generate"
        assert request.headers["x-api-key"] == "local-key"
        assert json.loads(request.content.decode()) == {
            "prompt": "cat",
            "mode": "imagine",
        }
        return httpx.Response(
            200,
            content=b"\x89PNG\r\nrelay",
            headers={"content-type": "image/png", "x-content-sha256": "abc"},
        )

    _mock_httpx(monkeypatch, handler)
    result = await relay.generate({"prompt": "cat", "mode": "imagine"})
    assert result["mime_type"] == "image/png"
    assert result["size_bytes"] == len(b"\x89PNG\r\nrelay")
    assert result["sha256"] == "abc"
    assert result["content"]


@pytest.mark.asyncio
async def test_bridge_manager_dispatches_homepilot_image_ops(monkeypatch):
    manager = bridge_manager.CloudBridgeManager()
    ws = FakeWebSocket()

    async def capability():
        return {"available": True}

    async def generate(payload):
        return {"content": "aW1hZ2U=", "mime_type": "image/png", "payload": payload}

    monkeypatch.setattr(bridge_manager, "homepilot_image_capability", capability)
    monkeypatch.setattr(bridge_manager, "homepilot_image_generate", generate)

    await manager._handle_request(
        ws,
        {"id": "cap-1", "op": relay.CAPABILITY_OP, "payload": {}},
    )
    await manager._handle_request(
        ws,
        {"id": "gen-1", "op": relay.GENERATE_OP, "payload": {"prompt": "cat"}},
    )

    assert ws.messages[0] == {
        "type": "res",
        "id": "cap-1",
        "ok": True,
        "data": {"available": True},
    }
    assert ws.messages[1]["ok"] is True
    assert ws.messages[1]["data"]["payload"] == {"prompt": "cat"}


@pytest.mark.asyncio
async def test_model_refresh_advertises_homepilot_image_capability(monkeypatch):
    manager = bridge_manager.CloudBridgeManager()
    ws = FakeWebSocket()

    async def manifest():
        return []

    monkeypatch.setattr(manager, "_fetch_cloud_manifest", manifest)
    await manager._send_model_update(ws)

    assert relay.RELAY_CAPABILITY in ws.messages[0]["capabilities"]
    assert "chat" in ws.messages[0]["capabilities"]
    assert "media_fetch" in ws.messages[0]["capabilities"]
