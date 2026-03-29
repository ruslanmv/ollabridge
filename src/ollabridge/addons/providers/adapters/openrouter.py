"""
OpenRouter API adapter.

OpenRouter is an aggregator that speaks OpenAI-compatible format.
Free models are suffixed with `:free` in their model IDs.

Base URL is https://openrouter.ai/api/v1 — already includes /v1,
so we override _chat_url and _models_url to avoid doubling it.
"""

from __future__ import annotations

from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """Adapter for the OpenRouter aggregator API."""

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        # OpenRouter recommends setting HTTP-Referer and X-Title
        headers["HTTP-Referer"] = "https://ollabridge.app"
        headers["X-Title"] = "OllaBridge Cloud"
        return headers

    def _chat_url(self) -> str:
        # base_url already ends with /v1
        return f"{self.base_url}/chat/completions"

    def _models_url(self) -> str:
        return f"{self.base_url}/models"
