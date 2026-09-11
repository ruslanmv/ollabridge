from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from ollabridge.connectors import media_proxy


def _configure(monkeypatch, *, enabled=True, base="http://homepilot:8000", api_key="hp-secret"):
    monkeypatch.setattr(
        media_proxy.rts,
        "get_all",
        lambda: {
            "homepilot_enabled": enabled,
            "homepilot_base_url": base,
            "homepilot_api_key": api_key,
        },
    )


def _mock_httpx(monkeypatch, handler):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(media_proxy.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_homepilot_capability_is_disabled_without_upstream_call(monkeypatch):
    _configure(monkeypatch, enabled=False)

    def should_not_run(_request):
        raise AssertionError("disabled HomePilot must not be probed")

    _mock_httpx(monkeypatch, should_not_run)

    result = await media_proxy.homepilot_image_capability()

    assert result == {
        "ok": True,
        "available": False,
        "enabled": False,
        "ready": False,
        "reason": "disabled",
        "device": "HomePilot",
    }


@pytest.mark.asyncio
async def test_homepilot_capability_probes_health_with_server_side_auth(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request):
        assert request.method == "GET"
        assert str(request.url) == "http://homepilot:8000/health"
        assert request.headers["authorization"] == "Bearer hp-secret"
        assert request.headers["x-api-key"] == "hp-secret"
        return httpx.Response(200, json={"ok": True})

    _mock_httpx(monkeypatch, handler)

    result = await media_proxy.homepilot_image_capability()

    assert result["available"] is True
    assert result["enabled"] is True
    assert result["ready"] is True
    assert result["reason"] == "ok"


@pytest.mark.asyncio
async def test_homepilot_generate_forwards_imagine_contract_and_returns_image_bytes(monkeypatch):
    _configure(monkeypatch)
    seen = {}

    def handler(request: httpx.Request):
        if request.method == "POST" and request.url.path == "/chat":
            seen["body"] = json.loads(request.content.decode("utf-8"))
            seen["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={
                    "text": "Generated",
                    "media": {"images": ["/files/generated/avatar.png"]},
                },
            )

        if request.method == "GET" and request.url.path == "/files/generated/avatar.png":
            assert request.headers["authorization"] == "Bearer hp-secret"
            return httpx.Response(200, content=b"\x89PNG\r\nimage", headers={"content-type": "image/png"})

        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _mock_httpx(monkeypatch, handler)

    body = media_proxy.HomePilotGenerateRequest(
        prompt="a friendly robot in Milan",
        width=1280,
        height=720,
        aspectRatio="16:9",
        seed=42,
        count=1,
    )
    response = await media_proxy.homepilot_generate_image(body)

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.body == b"\x89PNG\r\nimage"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    assert seen["body"] == {
        "message": "imagine a friendly robot in Milan",
        "mode": "imagine",
        "imgBatchSize": 1,
        "imgAspectRatio": "16:9",
        "imgWidth": 1280,
        "imgHeight": 720,
        "promptRefinement": True,
        "imgSeed": 42,
    }
    assert seen["headers"]["authorization"] == "Bearer hp-secret"
    assert seen["headers"]["x-api-key"] == "hp-secret"
    assert seen["headers"]["x-client-type"] == "vr-chatbot"


@pytest.mark.asyncio
async def test_homepilot_generate_accepts_absolute_image_url_from_homepilot(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request):
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "media": {
                        "images": ["http://127.0.0.1:8188/view?filename=generated.webp"]
                    }
                },
            )
        if request.method == "GET" and request.url.host == "127.0.0.1":
            return httpx.Response(200, content=b"RIFFimage", headers={"content-type": "image/webp"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    _mock_httpx(monkeypatch, handler)

    response = await media_proxy.homepilot_generate_image(
        media_proxy.HomePilotGenerateRequest(prompt="remote render")
    )

    assert response.media_type == "image/webp"
    assert response.body == b"RIFFimage"


@pytest.mark.asyncio
async def test_homepilot_generate_fails_cleanly_when_no_image_is_returned(monkeypatch):
    _configure(monkeypatch)

    def handler(request: httpx.Request):
        assert request.method == "POST"
        return httpx.Response(200, json={"text": "No image", "media": {"images": []}})

    _mock_httpx(monkeypatch, handler)

    with pytest.raises(HTTPException) as exc_info:
        await media_proxy.homepilot_generate_image(
            media_proxy.HomePilotGenerateRequest(prompt="missing image")
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "HomePilot returned no generated image"
