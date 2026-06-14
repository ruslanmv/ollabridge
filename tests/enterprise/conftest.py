"""Shared fixtures: every test gets an isolated ~/.ollabridge replacement."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def ollabridge_home(tmp_path, monkeypatch):
    """Isolate all config/state files and reset process-wide singletons."""
    home = tmp_path / "obhome"
    home.mkdir()
    monkeypatch.setenv("OLLABRIDGE_HOME", str(home))
    # Encrypted secret store by default in tests.
    monkeypatch.setenv("OLLA_SECRET", "test-secret")
    # Never let host env leak provider credentials into tests.
    for var in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "HUGGINGFACE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "CUSTOM_LLM_API_KEY",
        "OLLABRIDGE_CLOUD_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Reset the trace store singleton so it binds to the isolated home.
    import ollabridge.tracing.store as trace_store

    monkeypatch.setattr(trace_store, "_store", None)
    yield home
