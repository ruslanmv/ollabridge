"""Routing and credential plumbing for Groq's current model ids.

Groq's chat models are now namespaced under vendors it does not own
(``openai/gpt-oss-20b``, ``qwen/qwen3.6-27b``). The name heuristic reads that
namespace as "OpenAI", so without the declared-model list a Groq request would
either go nowhere or be offered to an OpenAI source that cannot serve it.

Second half: a key saved in the Sources UI lives in the encrypted SecretStore,
not the environment, and must reach the already-seeded Groq adapter — otherwise
the UI says "connected" while every chat request goes out unauthenticated.
"""

from __future__ import annotations

import pytest

from ollabridge.addons.providers.adapters.groq import GROQ_BASE_URL, GroqAdapter
from ollabridge.addons.providers.adapters.openai_compatible import (
    OpenAICompatibleAdapter,
)
from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderCategory,
    ProviderConfig,
    ProviderTier,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter
from ollabridge.addons.providers.services import dynamic_source_sync as dss
from ollabridge.addons.providers.services.provider_loader import load_provider_seed
from ollabridge.providers_meta import ProviderRecord


GROQ_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"]


async def _registry_with_groq_and_openai() -> ProviderRegistry:
    reg = ProviderRegistry()
    groq = ProviderConfig(
        id="groq-free",
        name="Groq API",
        kind="groq",
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE,
        base_url=GROQ_BASE_URL,
        credential_env="GROQ_API_KEY",
        models=GROQ_MODELS,
    )
    openai = ProviderConfig(
        id="openai-paid",
        name="OpenAI",
        kind="openai_compatible",
        tier=ProviderTier.SECONDARY,
        category=ProviderCategory.PAID,
        base_url="https://api.openai.com/v1",
        credential_env="OPENAI_API_KEY",
    )
    await reg.register(groq, GroqAdapter(base_url=groq.base_url, api_key="gsk_x"))
    await reg.register(
        openai, OpenAICompatibleAdapter(base_url=openai.base_url, api_key="sk-x")
    )
    for pid in ("groq-free", "openai-paid"):
        await reg.update_health(pid, HealthStatus.HEALTHY)
    return reg


@pytest.mark.asyncio
async def test_declared_model_routes_to_groq_not_the_openai_namespace():
    router = ProviderRouter(await _registry_with_groq_and_openai())
    routes = router.resolve("openai/gpt-oss-20b")
    assert [r.provider_id for r in routes] == ["groq-free"]
    assert routes[0].model == "openai/gpt-oss-20b"


@pytest.mark.asyncio
async def test_undeclared_model_still_uses_the_name_heuristic():
    router = ProviderRouter(await _registry_with_groq_and_openai())
    # Not in Groq's declared list, so the vendor-namespace heuristic applies
    # and the generic OpenAI-compatible source is offered it.
    assert [r.provider_id for r in router.resolve("acme/some-model")] == ["openai-paid"]


@pytest.mark.asyncio
async def test_local_model_names_still_reach_no_external_provider():
    router = ProviderRouter(await _registry_with_groq_and_openai())
    assert router.resolve("granite3.2:latest") == []


def test_seed_catalog_declares_groq_models_and_the_openai_v1_base_url():
    groq = next(c for c in load_provider_seed() if c.id == "groq-free")
    assert groq.base_url == GROQ_BASE_URL
    assert "openai/gpt-oss-20b" in groq.models


# ── BYOK key reaches the seeded adapter ──────────────────────────────


@pytest.mark.asyncio
async def test_rekey_pushes_a_ui_saved_key_onto_the_seeded_adapter(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    reg = await _registry_with_groq_and_openai()
    adapter = reg.get_adapter("groq-free")
    assert adapter.api_key == "gsk_x"

    assert dss.rekey_registered(reg, "groq", "gsk_from_ui") is True
    assert adapter.api_key == "gsk_from_ui"
    # An unrelated kind is untouched.
    assert reg.get_adapter("openai-paid").api_key == "sk-x"

    # Removing the source clears the credential again.
    assert dss.rekey_registered(reg, "groq", None) is True
    assert adapter.api_key is None
    assert adapter.has_credential is False


@pytest.mark.asyncio
async def test_an_explicit_env_var_outranks_the_ui_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_from_env")
    reg = await _registry_with_groq_and_openai()
    assert dss.rekey_registered(reg, "groq", "gsk_from_ui") is False
    assert reg.get_adapter("groq-free").api_key == "gsk_x"


# ── Discovery + defaults ─────────────────────────────────────────────


def test_groq_is_discoverable_and_anthropic_is_not():
    assert dss.is_discoverable("groq") is True
    assert dss.is_discoverable("openrouter") is True
    assert dss.is_discoverable("open_webui") is True
    # watsonx is not OpenAI-compatible but has its own catalog adapter.
    assert dss.is_discoverable("watsonx") is True
    assert dss.is_discoverable("anthropic") is False
    assert dss.is_discoverable("bedrock") is False


def test_discovery_builds_the_groq_adapter_even_without_a_saved_base_url():
    rec = ProviderRecord(name="groq", kind="groq", base_url="")
    adapter = dss.build_adapter(rec, "gsk_x")
    assert isinstance(adapter, GroqAdapter)
    assert adapter._models_url() == f"{GROQ_BASE_URL}/models"


def test_normalize_classifies_and_flags_a_groq_listing():
    rec = ProviderRecord(name="groq", kind="groq")
    models = dss.normalize_models(
        rec,
        [
            {"id": "openai/gpt-oss-20b", "owned_by": "OpenAI"},
            {"id": "whisper-large-v3", "owned_by": "OpenAI"},
            {"id": "meta-llama/llama-guard-4-12b"},
            {"id": "openai/gpt-oss-20b"},  # duplicate, dropped
        ],
    )
    by_id = {m["id"]: m for m in models}
    assert len(models) == 3
    assert by_id["openai/gpt-oss-20b"]["category"] == "chat"
    assert by_id["openai/gpt-oss-20b"]["free"] is True
    assert by_id["whisper-large-v3"]["category"] == "audio"
    assert by_id["meta-llama/llama-guard-4-12b"]["category"] == "guard"
    # Only chat models are eligible as a default.
    assert dss.default_model_for(rec, models) == "openai/gpt-oss-20b"


def test_default_model_ignores_non_chat_models():
    rec = ProviderRecord(name="groq", kind="groq")
    models = dss.normalize_models(rec, [{"id": "whisper-large-v3"}])
    assert dss.default_model_for(rec, models) == ""


def test_discovery_summary_counts_free_models():
    rec = ProviderRecord(name="groq", kind="groq")
    models = dss.normalize_models(
        rec, [{"id": "openai/gpt-oss-20b"}, {"id": "some-vendor/paid-model"}]
    )
    summary = dss.discovery_summary(models)
    assert summary["count"] == 2
    assert summary["free"] == 1
    assert summary["connection_types"] == {"external": 2}
