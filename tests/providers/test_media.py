"""Unit tests for the HF media service (image + video generation)."""

from __future__ import annotations

import base64

import httpx
import pytest

from ollabridge.addons.providers import media as media_mod
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
)
from ollabridge.addons.providers.media import HFMediaService


@pytest.fixture
def mock_transport(monkeypatch):
    _real = media_mod.httpx.AsyncClient

    def _factory_for(handler):
        transport = httpx.MockTransport(handler)

        def _patched(*args, **kwargs):
            kwargs["transport"] = transport
            return _real(*args, **kwargs)

        monkeypatch.setattr(media_mod.httpx, "AsyncClient", _patched)
        return HFMediaService(api_key="hf_x", bill_to="org-y")

    return _factory_for


@pytest.mark.asyncio
async def test_generate_image_passes_through_json_response(mock_transport):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["bill_to"] = request.headers.get("X-HF-Bill-To")
        return httpx.Response(
            200,
            json={"created": 1, "data": [{"b64_json": "AAA"}], "model": "x/img"},
        )

    svc = mock_transport(handler)
    out = await svc.generate_image(model="x/img:fal", prompt="cat")
    assert seen["url"] == "https://router.huggingface.co/v1/images/generations"
    assert seen["auth"] == "Bearer hf_x"
    assert seen["bill_to"] == "org-y"
    assert out["data"][0]["b64_json"] == "AAA"


@pytest.mark.asyncio
async def test_generate_image_wraps_raw_bytes(mock_transport):
    raw = b"\x89PNG\r\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, headers={"content-type": "image/png"})

    svc = mock_transport(handler)
    out = await svc.generate_image(model="x/img:fal", prompt="cat")
    assert out["data"][0]["b64_json"] == base64.b64encode(raw).decode("ascii")
    assert out["_content_type"] == "image/png"


@pytest.mark.asyncio
async def test_generate_image_402_raises_quota(mock_transport):
    svc = mock_transport(lambda r: httpx.Response(402, text="credits"))
    with pytest.raises(ProviderQuotaExceeded):
        await svc.generate_image(model="x/img:fal", prompt="cat")


@pytest.mark.asyncio
async def test_generate_image_401_raises_auth(mock_transport):
    svc = mock_transport(lambda r: httpx.Response(401, text="bad token"))
    with pytest.raises(ProviderAuthError):
        await svc.generate_image(model="x/img:fal", prompt="cat")


@pytest.mark.asyncio
async def test_generate_image_400_raises_bad_request(mock_transport):
    svc = mock_transport(lambda r: httpx.Response(400, text="bad model"))
    with pytest.raises(ProviderBadRequest):
        await svc.generate_image(model="x/img:fal", prompt="cat")


@pytest.mark.asyncio
async def test_generate_video_routes_through_upstream_provider(mock_transport):
    raw = b"\x00\x00\x00\x18ftyp"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=raw, headers={"content-type": "video/mp4"})

    svc = mock_transport(handler)
    out = await svc.generate_video(model="tencent/HunyuanVideo:fal", prompt="bridge")
    assert seen["url"] == "https://router.huggingface.co/fal/v1/video/generations"
    assert out["data"][0]["b64_video"] == base64.b64encode(raw).decode("ascii")
    assert out["data"][0]["content_type"] == "video/mp4"


@pytest.mark.asyncio
async def test_generate_video_uses_router_when_no_provider_pin(mock_transport):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"data": [{"b64_video": "AAA"}]})

    svc = mock_transport(handler)
    await svc.generate_video(model="tencent/HunyuanVideo", prompt="bridge")
    assert seen["url"] == "https://router.huggingface.co/v1/video/generations"
