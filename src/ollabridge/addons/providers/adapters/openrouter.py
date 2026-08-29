"""
OpenRouter API adapter.

OpenRouter is an aggregator that speaks OpenAI-compatible format.
Free models are suffixed with `:free` in their model IDs.

Base URL is https://openrouter.ai/api/v1 — it already includes /v1, and
``OpenAICompatibleAdapter._api_base`` leaves an already-versioned base URL
alone, so a bare https://openrouter.ai/api works too.
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
