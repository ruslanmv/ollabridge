"""
Groq API adapter.

Groq speaks OpenAI-compatible format at api.groq.com/openai/v1/.
"""

from __future__ import annotations

from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter


class GroqAdapter(OpenAICompatibleAdapter):
    """Adapter for the Groq inference API."""

    def _chat_url(self) -> str:
        return f"{self.base_url}/openai/v1/chat/completions"

    def _models_url(self) -> str:
        return f"{self.base_url}/openai/v1/models"
