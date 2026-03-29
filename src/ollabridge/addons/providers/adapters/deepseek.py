"""
DeepSeek API adapter.

DeepSeek speaks standard OpenAI-compatible format at api.deepseek.com.
"""

from __future__ import annotations

from ollabridge.addons.providers.adapters.openai_compatible import OpenAICompatibleAdapter


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """Adapter for the DeepSeek API."""

    # DeepSeek uses standard /v1/chat/completions — no overrides needed.
    pass
