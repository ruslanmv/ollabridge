"""
Provider seeder — creates adapter instances and registers them into the registry.

This is the main initialization entry point called from app startup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.router import ProviderRouter
from ollabridge.addons.providers.services.provider_loader import (
    load_aliases,
    load_provider_seed,
)

# Adapter imports
from ollabridge.addons.providers.adapters.gemini import GeminiAdapter
from ollabridge.addons.providers.adapters.groq import GroqAdapter
from ollabridge.addons.providers.adapters.deepseek import DeepSeekAdapter
from ollabridge.addons.providers.adapters.openrouter import OpenRouterAdapter
from ollabridge.addons.providers.adapters.huggingface import HuggingFaceAdapter
from ollabridge.addons.providers.adapters.ollama_bridge import OllamaBridgeAdapter
from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter

logger = logging.getLogger(__name__)

# Map provider kind → adapter class
_ADAPTER_MAP: dict[str, type[BaseProviderAdapter]] = {
    "gemini": GeminiAdapter,
    "groq": GroqAdapter,
    "deepseek": DeepSeekAdapter,
    "openrouter": OpenRouterAdapter,
    "huggingface": HuggingFaceAdapter,
    "ollama_bridge": OllamaBridgeAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
}


def _create_adapter(config: ProviderConfig) -> BaseProviderAdapter | None:
    """Instantiate the right adapter for a provider config."""
    adapter_cls = _ADAPTER_MAP.get(config.kind)
    if not adapter_cls:
        logger.warning(
            "Unknown provider kind '%s' for %s — skipping", config.kind, config.id
        )
        return None

    # Resolve API key from environment variable
    api_key: str | None = None
    if config.credential_env:
        api_key = os.environ.get(config.credential_env, "")
        if not api_key:
            logger.info(
                "No API key found in env var %s for provider %s — "
                "provider will be registered but may fail requests",
                config.credential_env,
                config.id,
            )

    return adapter_cls(base_url=config.base_url, api_key=api_key)


async def seed_providers(
    seed_path: str | Path | None = None,
    aliases_path: str | Path | None = None,
) -> tuple[ProviderRegistry, ProviderRouter]:
    """
    Load provider catalog from YAML, create adapters, and build the registry + router.

    This is the main entry point called during app startup.

    Returns (registry, router) ready for use.
    """
    registry = ProviderRegistry()

    # Load provider configs
    configs = load_provider_seed(seed_path)
    enabled_count = 0
    for config in configs:
        if not config.enabled:
            logger.debug("Skipping disabled provider: %s", config.id)
            continue
        adapter = _create_adapter(config)
        if adapter:
            await registry.register(config, adapter)
            enabled_count += 1

    # Load aliases
    aliases = load_aliases(aliases_path)
    registry.set_aliases(aliases)

    # Create router
    router = ProviderRouter(registry)

    logger.info(
        "Provider system initialized: %d providers registered (%d enabled), %d aliases loaded",
        registry.provider_count,
        enabled_count,
        len(aliases),
    )
    return registry, router
