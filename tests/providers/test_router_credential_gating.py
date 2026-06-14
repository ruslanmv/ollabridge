"""Routing must never attempt a provider that can't serve the request.

Regression for the log noise where a local Ollama model (granite3.2:latest)
was fanned out to Gemini/Groq/OpenRouter/HF/DeepSeek — all keyless — each
failing 401/403 before the gateway fell back to local Ollama.
"""

from __future__ import annotations

import pytest

from ollabridge.addons.providers.adapters.gemini import GeminiAdapter
from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderCategory,
    ProviderConfig,
    ProviderTier,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter


async def _registry(api_key: str) -> ProviderRegistry:
    reg = ProviderRegistry()
    cfg = ProviderConfig(
        id="gemini-free",
        name="Gemini",
        kind="gemini",
        enabled=True,
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE,
        base_url="https://generativelanguage.googleapis.com",
        credential_env="GEMINI_API_KEY",
    )
    await reg.register(cfg, GeminiAdapter(base_url=cfg.base_url, api_key=api_key))
    await reg.update_health("gemini-free", HealthStatus.HEALTHY)
    return reg


@pytest.mark.asyncio
async def test_keyless_provider_is_never_a_candidate():
    reg = await _registry(api_key="")
    router = ProviderRouter(reg)
    # Even its own model id must not select it without a key.
    assert router.resolve("gemini-2.5-flash") == []
    assert router.resolve("granite3.2:latest") == []


@pytest.mark.asyncio
async def test_local_model_does_not_fan_out_to_providers():
    reg = await _registry(api_key="AIza-realkey")
    router = ProviderRouter(reg)
    # Ollama-style local model: Gemini has a key but does not serve it.
    assert router.resolve("granite3.2:latest") == []
    assert router.resolve("llama3:latest") == []


@pytest.mark.asyncio
async def test_keyed_provider_still_serves_its_own_model():
    reg = await _registry(api_key="AIza-realkey")
    router = ProviderRouter(reg)
    ids = [c.provider_id for c in router.resolve("gemini-2.5-flash")]
    assert ids == ["gemini-free"]


@pytest.mark.asyncio
async def test_base_adapter_has_credential_property():
    from ollabridge.addons.providers.adapters.ollama_bridge import OllamaBridgeAdapter

    assert GeminiAdapter(base_url="x", api_key="").has_credential is False
    assert GeminiAdapter(base_url="x", api_key="k").has_credential is True
    # Local relay adapter needs no credential.
    assert OllamaBridgeAdapter(base_url="ws://x").has_credential is True
