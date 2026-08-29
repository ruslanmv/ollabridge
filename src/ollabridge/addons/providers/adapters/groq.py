"""
Groq API adapter.

Groq speaks OpenAI-compatible format under ``https://api.groq.com/openai/v1``
— the same base URL the official OpenAI SDK is pointed at:

    client = OpenAI(api_key=..., base_url="https://api.groq.com/openai/v1")

Only the API root differs from the generic OpenAI-compatible adapter, and
:meth:`OpenAICompatibleAdapter._api_base` will not append it twice when the
configured base URL already carries it.
"""

from __future__ import annotations

from ollabridge.addons.providers.adapters.openai_compatible import (
    OpenAICompatibleAdapter,
)

#: Canonical base URL. Accepted equally: ``https://api.groq.com``.
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqAdapter(OpenAICompatibleAdapter):
    """Adapter for the Groq inference API."""

    api_root = "openai/v1"
