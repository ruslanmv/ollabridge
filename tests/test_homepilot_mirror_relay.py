"""HomePilot Cloud Mirror relay (homepilot.mirror.*) — additive, off by default."""

from __future__ import annotations

import json

import httpx
import pytest

from ollabridge.cloud import bridge_manager
from ollabridge.cloud import homepilot_mirror_relay as mirror


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

    monkeypatch.setattr(mirror.httpx, "AsyncClient", factory)


@pytest.fixture
def relay_on(monkeypatch):
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "HOMEPILOT_MIRROR_RELAY_ENABLED", True)


# ── mapping ─────────────────────────────────────────────────────────


def test_ops_map_to_homepilot_node_endpoints():
    assert mirror.build_request(mirror.MANIFEST_OP, {}) == (
        "GET",
        "/v1/node/manifest",
        None,
        30.0,
    )
    assert mirror.build_request(mirror.RPC_OP, {"operation": "personas.list"}) == (
        "POST",
        "/v1/node/rpc",
        {"operation": "personas.list", "params": {}},
        30.0,
    )
    method, path, body, _ = mirror.build_request(
        mirror.JOB_CREATE_OP,
        {
            "operation": "agentic.invoke",
            "params": {"tool": "hp.smartmirror.style_suggest"},
            "resource_uri": "ollabridge-media://m_1",
        },
    )
    assert (method, path) == ("POST", "/v1/node/jobs")
    assert body == {
        "operation": "agentic.invoke",
        "params": {"tool": "hp.smartmirror.style_suggest"},
        "resource_uri": "ollabridge-media://m_1",
    }
    # resource_uri is only forwarded when present
    assert (
        "resource_uri"
        not in mirror.build_request(
            mirror.JOB_CREATE_OP,
            {"operation": "chat.completions", "resource_uri": None},
        )[2]
    )
    assert (
        mirror.build_request(mirror.JOB_GET_OP, {"job_id": "job_abc123"})[1]
        == "/v1/node/jobs/job_abc123"
    )
    assert (
        mirror.build_request(mirror.JOB_CANCEL_OP, {"job_id": "job_abc123"})[1]
        == "/v1/node/jobs/job_abc123/cancel"
    )


@pytest.mark.parametrize(
    "op,payload,reason",
    [
        (mirror.JOB_GET_OP, {"job_id": "../../admin"}, "invalid_job_id"),
        (mirror.JOB_CANCEL_OP, {}, "invalid_job_id"),
        (mirror.JOB_CREATE_OP, {"operation": "rm -rf /"}, "invalid_operation"),
        (
            mirror.RPC_OP,
            {"operation": "settings.get_safe", "params": ["x"]},
            "invalid_params",
        ),
        ("homepilot.mirror.shell", {}, "unknown_mirror_op"),
    ],
)
def test_rejects_malformed_or_unknown_requests(op, payload, reason):
    with pytest.raises(mirror.MirrorRelayError, match=reason):
        mirror.build_request(op, payload)


# ── HTTP dispatch ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_calls_local_homepilot_with_api_key(monkeypatch):
    def handler(request: httpx.Request):
        assert str(request.url) == "http://127.0.0.1:8000/v1/node/jobs"
        assert request.headers["x-api-key"] == "hp-key"
        assert request.headers["authorization"] == "Bearer hp-key"
        assert json.loads(request.content) == {
            "operation": "agentic.invoke",
            "params": {"tool": "t"},
        }
        return httpx.Response(202, json={"job_id": "job_1", "status": "queued"})

    _mock_httpx(monkeypatch, handler)
    result = await mirror.dispatch(
        mirror.JOB_CREATE_OP,
        {"operation": "agentic.invoke", "params": {"tool": "t"}},
        base_url="http://127.0.0.1:8000/",
        api_key="hp-key",
    )
    assert result == {"job_id": "job_1", "status": "queued"}


@pytest.mark.asyncio
async def test_dispatch_relays_homepilot_error_codes(monkeypatch):
    _mock_httpx(
        monkeypatch,
        lambda request: httpx.Response(404, json={"error": "node_jobs_disabled"}),
    )
    with pytest.raises(
        mirror.MirrorRelayError, match="homepilot_http_404: node_jobs_disabled"
    ):
        await mirror.dispatch(mirror.MANIFEST_OP, {}, base_url="http://127.0.0.1:8000")


@pytest.mark.asyncio
async def test_dispatch_reports_unreachable_homepilot(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    _mock_httpx(monkeypatch, handler)
    with pytest.raises(mirror.MirrorRelayError, match="homepilot_unreachable"):
        await mirror.dispatch(mirror.MANIFEST_OP, {}, base_url="http://127.0.0.1:8000")


# ── bridge integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_off_keeps_legacy_unsupported_operation(monkeypatch):
    called = []

    async def dispatch(*args, **kwargs):
        called.append(args)
        return {}

    monkeypatch.setattr(bridge_manager, "homepilot_mirror_dispatch", dispatch)
    manager = bridge_manager.CloudBridgeManager(homepilot_enabled=True)
    ws = FakeWebSocket()
    await manager._handle_request(
        ws, {"id": "m-1", "op": mirror.MANIFEST_OP, "payload": {}}
    )
    assert called == []
    assert ws.messages[0] == {
        "type": "res",
        "id": "m-1",
        "ok": False,
        "error": f"Unsupported operation: {mirror.MANIFEST_OP}",
    }


@pytest.mark.asyncio
async def test_requires_homepilot_enabled(monkeypatch, relay_on):
    manager = bridge_manager.CloudBridgeManager(homepilot_enabled=False)
    ws = FakeWebSocket()
    await manager._handle_request(
        ws, {"id": "m-2", "op": mirror.MANIFEST_OP, "payload": {}}
    )
    assert ws.messages[0]["ok"] is False
    assert "Unsupported operation" in ws.messages[0]["error"]


@pytest.mark.asyncio
async def test_bridge_dispatches_mirror_ops_when_enabled(monkeypatch, relay_on):
    seen = {}

    async def dispatch(op, payload, *, base_url, api_key):
        seen.update(op=op, payload=payload, base_url=base_url, api_key=api_key)
        return {"job_id": "job_9", "status": "queued"}

    monkeypatch.setattr(bridge_manager, "homepilot_mirror_dispatch", dispatch)
    manager = bridge_manager.CloudBridgeManager(
        homepilot_base_url="http://127.0.0.1:8000",
        homepilot_api_key="k",
        homepilot_enabled=True,
    )
    ws = FakeWebSocket()
    payload = {
        "operation": "agentic.invoke",
        "params": {"tool": "hp.smartmirror.wardrobe_list"},
    }
    await manager._handle_request(
        ws, {"id": "j-1", "op": mirror.JOB_CREATE_OP, "payload": payload}
    )
    assert ws.messages[0] == {
        "type": "res",
        "id": "j-1",
        "ok": True,
        "data": {"job_id": "job_9", "status": "queued"},
    }
    assert seen == {
        "op": mirror.JOB_CREATE_OP,
        "payload": payload,
        "base_url": "http://127.0.0.1:8000",
        "api_key": "k",
    }


@pytest.mark.asyncio
async def test_bridge_returns_relay_errors_without_params(
    monkeypatch, relay_on, caplog
):
    async def dispatch(op, payload, **kwargs):
        raise mirror.MirrorRelayError("homepilot_http_400: unknown_operation")

    monkeypatch.setattr(bridge_manager, "homepilot_mirror_dispatch", dispatch)
    manager = bridge_manager.CloudBridgeManager(homepilot_enabled=True)
    ws = FakeWebSocket()
    secret_prompt = "private prompt about my body"
    await manager._handle_request(
        ws,
        {
            "id": "j-2",
            "op": mirror.JOB_CREATE_OP,
            "payload": {"operation": "x", "params": {"prompt": secret_prompt}},
        },
    )
    assert ws.messages[0] == {
        "type": "res",
        "id": "j-2",
        "ok": False,
        "error": "homepilot_http_400: unknown_operation",
    }
    assert secret_prompt not in caplog.text


@pytest.mark.asyncio
async def test_capability_advertised_only_when_enabled(monkeypatch):
    from ollabridge.core.settings import settings

    manager = bridge_manager.CloudBridgeManager(homepilot_enabled=True)

    async def manifest():
        return []

    monkeypatch.setattr(manager, "_fetch_cloud_manifest", manifest)

    ws = FakeWebSocket()
    await manager._send_model_update(ws)
    assert mirror.RELAY_CAPABILITY not in ws.messages[0]["capabilities"]

    monkeypatch.setattr(settings, "HOMEPILOT_MIRROR_RELAY_ENABLED", True)
    ws = FakeWebSocket()
    await manager._send_model_update(ws)
    assert mirror.RELAY_CAPABILITY in ws.messages[0]["capabilities"]
    # Existing capabilities are unchanged.
    assert {"chat", "models", "media_fetch", "homepilot.image"} <= set(
        ws.messages[0]["capabilities"]
    )
