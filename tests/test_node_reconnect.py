"""Production hardening — Cloud device auto-reconnect with backoff."""

from __future__ import annotations

import asyncio

import pytest

from ollabridge.node import agent


@pytest.mark.asyncio
async def test_forever_stops_on_cancel(monkeypatch):
    async def fake(_config):
        raise asyncio.CancelledError()

    monkeypatch.setattr(agent, "run_cloud_device", fake)
    with pytest.raises(asyncio.CancelledError):
        await agent.run_cloud_device_forever(None, base_backoff=0, max_backoff=0)


@pytest.mark.asyncio
async def test_forever_retries_then_stops(monkeypatch):
    calls = {"n": 0}

    async def fake(_config):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("connection dropped")
        raise asyncio.CancelledError()  # third attempt = clean shutdown

    monkeypatch.setattr(agent, "run_cloud_device", fake)
    with pytest.raises(asyncio.CancelledError):
        await agent.run_cloud_device_forever(None, base_backoff=0, max_backoff=0)
    assert calls["n"] == 3  # retried after each drop, then stopped on cancel


@pytest.mark.asyncio
async def test_forever_reconnects_after_normal_close(monkeypatch):
    calls = {"n": 0}

    async def fake(_config):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise asyncio.CancelledError()
        return  # normal ws close → should reconnect

    monkeypatch.setattr(agent, "run_cloud_device", fake)
    with pytest.raises(asyncio.CancelledError):
        await agent.run_cloud_device_forever(None, base_backoff=0, max_backoff=0)
    assert calls["n"] == 2
