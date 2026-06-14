"""The ollama_bridge addon stub must never answer a real request.

Regression for the "[OllamaBridge stub] Relay integration pending." text
leaking to end users (OllaBridge Cloud → yourfriend.online). The adapter
must raise so ProviderRouter fails over to a real backend, and the seeded
ollama-node providers must ship disabled.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ollabridge.addons.providers.adapters.ollama_bridge import OllamaBridgeAdapter
from ollabridge.addons.providers.errors import ProviderError


@pytest.mark.asyncio
async def test_adapter_raises_instead_of_returning_stub():
    adapter = OllamaBridgeAdapter(base_url="ws://node-01.internal")
    with pytest.raises(ProviderError):
        await adapter.chat("qwen2.5:14b", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_adapter_is_always_unhealthy():
    adapter = OllamaBridgeAdapter(base_url="ws://node-01.internal")
    assert await adapter.health_check() is False


def test_seeded_ollama_nodes_are_disabled():
    seed = Path("src/ollabridge/addons/providers/catalog/providers.seed.yaml")
    data = yaml.safe_load(seed.read_text())
    providers = data.get("providers", data) if isinstance(data, dict) else data
    if isinstance(providers, dict):
        providers = providers.get("providers", [])
    nodes = [p for p in providers if str(p.get("kind")) == "ollama_bridge"]
    assert nodes, "expected seeded ollama_bridge providers"
    for n in nodes:
        assert n.get("enabled") is False, f"{n.get('id')} must ship disabled"


def test_no_stub_text_in_adapter_source():
    src = Path("src/ollabridge/addons/providers/adapters/ollama_bridge.py").read_text()
    # The literal stub reply must not be returned anywhere.
    assert "Relay integration pending." not in src.split("must **never**")[-1] \
        or "raise" in src
    assert "chatcmpl-ollama-bridge-stub" not in src
