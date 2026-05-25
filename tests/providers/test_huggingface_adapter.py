"""Unit tests for the Hugging Face Inference Providers adapter (v2)."""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers.adapters import huggingface as hf_mod
from ollabridge.addons.providers.adapters.huggingface import (
    HF_ROUTER_BASE,
    HuggingFaceAdapter,
)
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)


@pytest.fixture
def mock_hf_transport(monkeypatch):
    """Patch httpx.AsyncClient inside the adapter module to use a MockTransport.

    Usage:
        def handler(request): return httpx.Response(200, json={...})
        adapter = mock_hf_transport(handler)
    """
    _real_client = hf_mod.httpx.AsyncClient

    def _factory_for(handler):
        transport = httpx.MockTransport(handler)

        def _patched_client(*args, **kwargs):
            kwargs["transport"] = transport
            return _real_client(*args, **kwargs)

        monkeypatch.setattr(hf_mod.httpx, "AsyncClient", _patched_client)
        return HuggingFaceAdapter(api_key="hf_test", bill_to="org-example")

    return _factory_for


@pytest.mark.asyncio
async def test_chat_targets_openai_compatible_router_with_auth_and_bill_to(mock_hf_transport):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["bill_to"] = request.headers.get("X-HF-Bill-To")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    adapter = mock_hf_transport(handler)
    result = await adapter.chat(
        "deepseek-ai/DeepSeek-V3:together",
        [{"role": "user", "content": "hello"}],
        temperature=0.2,
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
    )

    assert seen["url"] == f"{HF_ROUTER_BASE}/v1/chat/completions"
    assert seen["auth"] == "Bearer hf_test"
    assert seen["bill_to"] == "org-example"
    assert "deepseek-ai/DeepSeek-V3:together" in seen["body"]
    assert '"temperature":0.2' in seen["body"]
    assert '"tools"' in seen["body"]
    assert result["choices"][0]["message"]["content"] == "hi"


@pytest.mark.asyncio
async def test_chat_402_raises_quota_exceeded(mock_hf_transport):
    adapter = mock_hf_transport(lambda r: httpx.Response(402, text="monthly credits exhausted"))
    with pytest.raises(ProviderQuotaExceeded):
        await adapter.chat("any/model", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_429_also_raises_quota_exceeded(mock_hf_transport):
    adapter = mock_hf_transport(lambda r: httpx.Response(429, text="too many requests"))
    with pytest.raises(ProviderQuotaExceeded):
        await adapter.chat("any/model", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_401_raises_auth_error(mock_hf_transport):
    adapter = mock_hf_transport(lambda r: httpx.Response(401, text="invalid token"))
    with pytest.raises(ProviderAuthError):
        await adapter.chat("any/model", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_400_raises_bad_request(mock_hf_transport):
    adapter = mock_hf_transport(lambda r: httpx.Response(400, text="bad model id"))
    with pytest.raises(ProviderBadRequest):
        await adapter.chat("bogus", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_500_raises_provider_unavailable(mock_hf_transport):
    adapter = mock_hf_transport(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(ProviderUnavailable):
        await adapter.chat("any/model", [{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_list_models_extracts_data_array(mock_hf_transport):
    seen_url: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_url["v"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "deepseek-ai/DeepSeek-V3:together"},
                    {"id": "meta-llama/Llama-3.3-70B-Instruct:groq"},
                ],
            },
        )

    adapter = mock_hf_transport(handler)
    models = await adapter.list_models()
    assert seen_url["v"] == f"{HF_ROUTER_BASE}/v1/models"
    assert {m["id"] for m in models} == {
        "deepseek-ai/DeepSeek-V3:together",
        "meta-llama/Llama-3.3-70B-Instruct:groq",
    }


def test_api_base_handles_trailing_v1():
    adapter = HuggingFaceAdapter(base_url="https://router.huggingface.co/v1")
    assert adapter._api_base() == "https://router.huggingface.co/v1"

    adapter2 = HuggingFaceAdapter(base_url="https://router.huggingface.co")
    assert adapter2._api_base() == "https://router.huggingface.co/v1"
