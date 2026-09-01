"""Capability-aware runtime routing tests."""

import asyncio

from ollabridge.core.registry import RuntimeNodeState, RuntimeRegistry
from ollabridge.core.router import Router


def test_tool_request_avoids_homepilot_even_when_round_robin_points_to_it():
    async def exercise():
        registry = RuntimeRegistry()
        await registry.upsert(
            RuntimeNodeState(node_id="a-homepilot", connector="homepilot")
        )
        await registry.upsert(
            RuntimeNodeState(node_id="z-ollama", connector="local_ollama")
        )
        return await Router(registry).choose_node(
            model="qwen3:8b", require_tools=True
        )

    decision = asyncio.run(exercise())

    assert decision.node.connector == "local_ollama"


def test_tool_request_uses_only_capable_relay_nodes():
    async def exercise():
        registry = RuntimeRegistry()
        await registry.upsert(
            RuntimeNodeState(
                node_id="old-node",
                connector="relay_link",
                meta={"capabilities": ["chat"]},
            )
        )
        await registry.upsert(
            RuntimeNodeState(
                node_id="tool-node",
                connector="relay_link",
                meta={"capabilities": ["chat", "tools"]},
            )
        )
        return await Router(registry).choose_node(
            model="qwen3:8b", require_tools=True
        )

    decision = asyncio.run(exercise())

    assert decision.node.node_id == "tool-node"


def test_plain_chat_keeps_existing_round_robin_behavior():
    async def exercise():
        registry = RuntimeRegistry()
        await registry.upsert(
            RuntimeNodeState(node_id="a-homepilot", connector="homepilot")
        )
        await registry.upsert(
            RuntimeNodeState(node_id="z-ollama", connector="local_ollama")
        )
        router = Router(registry)
        return (
            await router.choose_node(model="qwen3:8b"),
            await router.choose_node(model="qwen3:8b"),
        )

    first, second = asyncio.run(exercise())

    assert first.node.connector == "homepilot"
    assert second.node.connector == "local_ollama"
