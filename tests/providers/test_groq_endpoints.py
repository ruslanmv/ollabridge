"""Groq endpoint construction, error mapping, and the free-tier catalog.

Groq is reached at ``https://api.groq.com/openai/v1`` — the base URL the
OpenAI SDK is pointed at. Three parts of the codebase configure that URL and
they historically disagreed about how much of the path they carried, which
produced ``/openai/v1/openai/v1/chat/completions``. These tests pin the
normalization so any of the shapes works.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers import free_tier
from ollabridge.addons.providers.adapters.deepseek import DeepSeekAdapter
from ollabridge.addons.providers.adapters.groq import GROQ_BASE_URL, GroqAdapter
from ollabridge.addons.providers.adapters.openrouter import OpenRouterAdapter
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderQuotaExceeded,
)


@pytest.mark.parametrize(
    "base",
    [
        "https://api.groq.com",
        "https://api.groq.com/",
        "https://api.groq.com/openai",
        "https://api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1/",
    ],
)
def test_groq_urls_never_double_the_api_root(base):
    adapter = GroqAdapter(base_url=base, api_key="gsk_test")
    assert adapter._chat_url() == f"{GROQ_BASE_URL}/chat/completions"
    assert adapter._models_url() == f"{GROQ_BASE_URL}/models"


def test_generic_openai_compatible_root_is_v1():
    adapter = DeepSeekAdapter(base_url="https://api.deepseek.com", api_key="k")
    assert adapter._chat_url() == "https://api.deepseek.com/v1/chat/completions"
    # An already-versioned base URL is left alone.
    assert (
        DeepSeekAdapter(base_url="https://api.deepseek.com/v1")._chat_url()
        == "https://api.deepseek.com/v1/chat/completions"
    )


def test_openrouter_accepts_both_base_url_shapes():
    for base in ("https://openrouter.ai/api", "https://openrouter.ai/api/v1"):
        assert (
            OpenRouterAdapter(base_url=base)._models_url()
            == "https://openrouter.ai/api/v1/models"
        )


def _adapter_against(monkeypatch, handler):
    from ollabridge.addons.providers.adapters import openai_compatible as oc

    real = oc.httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    monkeypatch.setattr(oc.httpx, "AsyncClient", _patched)
    return GroqAdapter(base_url=GROQ_BASE_URL, api_key="gsk_test")


@pytest.mark.asyncio
async def test_chat_posts_to_the_groq_openai_path(monkeypatch):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    adapter = _adapter_against(monkeypatch, handler)
    out = await adapter.chat("openai/gpt-oss-20b", [{"role": "user", "content": "hi"}])
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["auth"] == "Bearer gsk_test"
    assert out["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ProviderAuthError),
        (429, ProviderQuotaExceeded),
        # A decommissioned model is a 400 — do not retry it, do fail over.
        (400, ProviderBadRequest),
    ],
)
async def test_upstream_errors_map_to_routing_aware_exceptions(
    monkeypatch, status, expected
):
    adapter = _adapter_against(
        monkeypatch, lambda _r: httpx.Response(status, text="model_decommissioned")
    )
    with pytest.raises(expected):
        await adapter.chat("openai/gpt-oss-20b", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_errors_never_leak_the_api_key(monkeypatch):
    adapter = _adapter_against(
        monkeypatch, lambda _r: httpx.Response(400, text="bad key gsk_test here")
    )
    with pytest.raises(ProviderBadRequest) as exc:
        await adapter.chat("openai/gpt-oss-20b", [{"role": "user", "content": "hi"}])
    assert "gsk_test" not in str(exc.value)


@pytest.mark.asyncio
async def test_list_models_returns_the_live_catalog(monkeypatch):
    adapter = _adapter_against(
        monkeypatch,
        lambda _r: httpx.Response(
            200, json={"data": [{"id": "openai/gpt-oss-20b"}, {"id": "whisper-large-v3"}]}
        ),
    )
    assert [m["id"] for m in await adapter.list_models()] == [
        "openai/gpt-oss-20b",
        "whisper-large-v3",
    ]


# ── Free-tier catalog ────────────────────────────────────────────────


def test_groq_free_tier_covers_the_gpt_oss_family():
    assert free_tier.is_free("groq", "openai/gpt-oss-20b")
    assert free_tier.is_free("groq", "openai/gpt-oss-120b")
    # Prefix rule: a newer gpt-oss size is free without editing the catalog.
    assert free_tier.is_free("groq", "openai/gpt-oss-40b")
    assert not free_tier.is_free("groq", "some-vendor/paid-model")


def test_openrouter_free_routes_are_recognised_by_suffix():
    assert free_tier.is_free("openrouter", "meta-llama/llama-3.3-70b-instruct:free")
    assert not free_tier.is_free("openrouter", "meta-llama/llama-3.3-70b-instruct")


def test_preferred_default_skips_models_the_provider_no_longer_serves():
    # gpt-oss-20b is first in the catalog but absent upstream, so the next
    # free model that is actually offered wins.
    assert (
        free_tier.preferred_default("groq", ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"])
        == "openai/gpt-oss-120b"
    )
    # Nothing free on offer: say so rather than saving a model that 400s.
    assert free_tier.preferred_default("groq", ["some-vendor/paid-model"]) == ""
    # No discovery at all: fall back to the catalog's first choice.
    assert free_tier.preferred_default("groq") == "openai/gpt-oss-20b"


def test_unknown_provider_kind_has_no_free_models():
    assert free_tier.free_models("not-a-provider") == []
    assert free_tier.preferred_default("not-a-provider") == ""
