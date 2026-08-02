"""The generic Open WebUI kind is wired into the provider seeder additively.

A ``kind: open_webui`` record builds an OpenWebUIAdapter carrying its per-source
endpoint/behavior options, while every existing adapter keeps its unchanged
2-arg construction.
"""

from __future__ import annotations

from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter
from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.addons.providers.services.provider_seeder import _ADAPTER_MAP, _create_adapter


def test_open_webui_kind_is_registered():
    assert _ADAPTER_MAP["open_webui"] is OpenWebUIAdapter


def test_seeder_builds_open_webui_adapter_with_options(monkeypatch):
    monkeypatch.setenv("OPEN_WEBUI_API_KEY", "sk-x")
    cfg = ProviderConfig(
        id="ow-team", name="ow", kind="open_webui",
        base_url="https://host.example/api", credential_env="OPEN_WEBUI_API_KEY",
        model_prefix="team-a", auth_header="x-api-key", fail_closed=True,
    )
    adapter = _create_adapter(cfg)
    assert isinstance(adapter, OpenWebUIAdapter)
    assert adapter.base_url == "https://host.example/api"
    assert adapter.model_prefix == "team-a"
    assert adapter.auth_header == "x-api-key"
    assert adapter.fail_closed is True
    # Sensible fallbacks default in.
    assert adapter.fallback_models_path == "/models"
    assert adapter.fallback_chat_path == "/chat/completions"


def test_existing_kind_construction_unchanged(monkeypatch):
    cfg = ProviderConfig(id="c", name="c", kind="openai_compatible", base_url="https://x/v1")
    adapter = _create_adapter(cfg)
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.base_url == "https://x/v1"


def test_provider_config_defaults_preserve_existing_behavior():
    # New optional fields default so any pre-existing provider config is unaffected.
    cfg = ProviderConfig(id="c", name="c", kind="groq")
    assert cfg.models_path == "/v1/models"
    assert cfg.model_prefix is None and cfg.dynamic_models is False
    assert cfg.fail_closed is False and cfg.auth_header == "authorization"
