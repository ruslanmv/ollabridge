"""Telling "this machine is offline" from "the provider is slow".

Observed 2026-11-12 on a laptop on the move: two requests for an Open WebUI
model each hung for 120 s and came back as HTTP 504 ``provider_timeout``,
the same answer a merely slow model gets, and the access line named
``route=ollama/local`` although local Ollama was never involved. Pinned here:

* a transport failure is classified (DNS, unreachable, connect timeout,
  dropped connection) and checked with a probe of the configured providers;
* while offline, requests for remote models fail fast with a 503
  ``network_offline`` and a Retry-After, local providers are still tried,
  and the outage is not counted against the provider's health;
* a request in flight whose provider stops answering probes (or whose
  machine changes network address) is aborted with ``connection_lost``;
* a provider that stays reachable while slow keeps its ``provider_timeout``,
  now saying the network was fine;
* one WARNING per outage, one INFO on recovery.

No test touches the network: the probe is a fake.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from ollabridge.addons.providers.errors import (
    ProviderNetworkError,
    ProviderTimeout,
    ProviderUnavailable,
)
from ollabridge.addons.providers.router import ProviderRouter, ProvidersExhausted
from ollabridge.core.connectivity import (
    OFFLINE,
    ONLINE,
    UNKNOWN,
    NetworkLost,
    NetworkMonitor,
    classify,
    is_remote,
    probe_target,
)

REMOTE = "https://chat.provider.example/api"
OTHER = "https://llm.other.example"
LOCAL = "http://127.0.0.1:4000"


class Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProber:
    """Answers probes from a table: ``True`` reachable, an exception otherwise."""

    def __init__(self, up: bool = True) -> None:
        self.up = up
        self.by_host: dict[str, bool] = {}
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int, timeout: float) -> None:
        self.calls.append((host, port))
        await asyncio.sleep(0)
        if not self.by_host.get(host, self.up):
            raise socket.gaierror(-3, "Temporary failure in name resolution")


async def _never_sleep(_s: float) -> None:
    # The recovery loop waits here; parking it keeps tests deterministic.
    await asyncio.Event().wait()


def _monitor(prober: FakeProber, *, targets=(REMOTE,), clock=None, **kw) -> NetworkMonitor:
    mon = NetworkMonitor(
        enabled=True,
        prober=prober,
        address=kw.pop("address", lambda: "10.0.0.5"),
        clock=clock or Clock(),
        sleep=kw.pop("sleep", _never_sleep),
        **kw,
    )
    mon.set_targets(lambda: list(targets))
    return mon


def _dns_failure() -> ProviderUnavailable:
    """What an adapter raises when the provider's name does not resolve."""
    try:
        try:
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        except socket.gaierror as inner:
            raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution") from inner
    except httpx.ConnectError as exc:
        err = ProviderUnavailable(str(exc))
        err.__cause__ = exc
        return err


# ── classification ────────────────────────────────────────────────────────


def test_classify_names_the_transport_fault():
    assert classify(_dns_failure()).kind == "dns"
    assert classify(httpx.ConnectError("[Errno 11001] getaddrinfo failed")).kind == "dns"
    assert classify(OSError(101, "Network is unreachable")).kind == "unreachable"
    assert classify(httpx.ConnectTimeout("")).kind == "connect_timeout"
    assert classify(httpx.RemoteProtocolError("Server disconnected without sending a response")).kind == (
        "connection_lost"
    )
    wrapped = ProviderTimeout("chat timeout while waiting for the answer (limit 120 s)")
    wrapped.__cause__ = httpx.ReadTimeout("")
    assert classify(wrapped).kind == "read_timeout"
    assert classify(ProviderTimeout("timeout")).kind == "read_timeout"


def test_a_refusal_means_the_network_is_up():
    fault = classify(httpx.ConnectError("[Errno 111] Connection refused"))
    assert fault.kind == "refused" and not fault.suspects_network


def test_an_http_answer_is_never_a_network_fault():
    exc = ProviderUnavailable("upstream error (HTTP 504)")
    exc.upstream_status = 504
    assert classify(exc) is None
    assert classify(ValueError("bad json")) is None
    assert classify(RuntimeError("provider said no: request timeout in body")) is None


def test_local_addresses_are_not_remote_and_proxies_are_probed(monkeypatch):
    assert not is_remote("http://localhost:11434") and not is_remote(LOCAL)
    assert is_remote(REMOTE)
    assert probe_target(LOCAL) is None
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "")
    assert probe_target(REMOTE) == ("chat.provider.example", 443)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp.example:3128")
    monkeypatch.setenv("https_proxy", "http://proxy.corp.example:3128")
    assert probe_target(REMOTE) == ("proxy.corp.example", 3128)


# ── the monitor ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_offline_when_no_provider_answers_logged_once(caplog):
    prober = FakeProber(up=False)
    clock = Clock()
    mon = _monitor(prober, targets=(REMOTE, OTHER), clock=clock)
    with caplog.at_level(logging.DEBUG, logger="ollabridge.network"):
        assert await mon.check() == OFFLINE
        clock.advance(10)
        assert await mon.check() == OFFLINE
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Network connection lost" in warnings[0].getMessage()
    assert "DNS lookup for chat.provider.example failed" in warnings[0].getMessage()
    snap = mon.snapshot()
    assert snap["state"] == "offline" and snap["outages"] == 1 and snap["retry_after_s"] >= 1


@pytest.mark.asyncio
async def test_one_reachable_provider_means_online():
    prober = FakeProber()
    prober.by_host = {"chat.provider.example": False, "llm.other.example": True}
    mon = _monitor(prober, targets=(REMOTE, OTHER))
    assert await mon.check() == ONLINE


@pytest.mark.asyncio
async def test_recovery_is_logged_with_the_outage_length(caplog):
    prober = FakeProber(up=False)
    clock = Clock()
    mon = _monitor(prober, clock=clock)
    await mon.check()
    mon.note_failed_fast()
    mon.note_failed_fast()
    prober.up = True
    clock.advance(192)
    with caplog.at_level(logging.INFO, logger="ollabridge.network"):
        assert await mon.check() == ONLINE
    (line,) = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert "restored after 3 min 12 s" in line and "2 request(s) failed fast" in line


@pytest.mark.asyncio
async def test_background_probe_closes_the_circuit():
    prober = FakeProber(up=False)
    ticks: list[float] = []

    async def sleep(seconds: float) -> None:
        ticks.append(seconds)
        if len(ticks) >= 2:
            prober.up = True  # back out of the tunnel
        await asyncio.sleep(0)

    mon = _monitor(prober, sleep=sleep)
    assert await mon.check() == OFFLINE
    for _ in range(50):
        if mon.state == ONLINE:
            break
        await asyncio.sleep(0)
    assert mon.state == ONLINE
    assert ticks[:2] == [2.0, 4.0]  # exponential backoff


@pytest.mark.asyncio
async def test_concurrent_checks_share_one_probe_round():
    prober = FakeProber(up=False)
    mon = _monitor(prober)
    results = await asyncio.gather(*(mon.check() for _ in range(10)))
    assert set(results) == {OFFLINE}
    assert len(prober.calls) == 1


@pytest.mark.asyncio
async def test_a_recent_check_is_reused():
    prober = FakeProber()
    clock = Clock()
    mon = _monitor(prober, clock=clock)
    await mon.check()
    clock.advance(1)
    await mon.check()
    assert len(prober.calls) == 1
    clock.advance(5)
    await mon.check()
    assert len(prober.calls) == 2


@pytest.mark.asyncio
async def test_nothing_remote_or_disabled_stays_unknown():
    prober = FakeProber(up=False)
    assert await _monitor(prober, targets=()).check() == UNKNOWN
    off = NetworkMonitor(enabled=False, prober=prober)
    off.set_targets(lambda: [REMOTE])
    assert await off.check() == UNKNOWN and not off.offline
    assert prober.calls == []


@pytest.mark.asyncio
async def test_no_route_at_all_says_so():
    mon = _monitor(FakeProber(up=False), address=lambda: None)
    await mon.check()
    assert "no network route" in mon.reason


# ── the stall watchdog ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_quick_answer_is_never_probed():
    prober = FakeProber(up=False)
    mon = _monitor(prober, stall_after_s=5)
    assert await mon.guard(AsyncMock(return_value={"ok": 1}), url=REMOTE, label="p") == {"ok": 1}
    assert prober.calls == []


@pytest.mark.asyncio
async def test_a_dead_link_aborts_the_request_instead_of_waiting():
    prober = FakeProber(up=False)
    mon = _monitor(prober, stall_after_s=0.01, stall_every_s=0.01)
    cancelled = asyncio.Event()

    async def hangs():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(NetworkLost, match="lost the connection to p"):
        await asyncio.wait_for(mon.guard(hangs, url=REMOTE, label="p"), timeout=5)
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert mon.state == OFFLINE  # and the next request fails fast


@pytest.mark.asyncio
async def test_a_network_switch_aborts_the_request():
    addresses = iter(["10.0.0.5", "172.20.10.3"])
    mon = _monitor(FakeProber(), stall_after_s=0.01, stall_every_s=0.01, address=lambda: next(addresses, "172.20.10.3"))

    async def hangs():
        await asyncio.sleep(3600)

    with pytest.raises(NetworkLost, match="network changed"):
        await asyncio.wait_for(mon.guard(hangs, url=REMOTE, label="p"), timeout=5)


@pytest.mark.asyncio
async def test_a_slow_but_reachable_provider_keeps_waiting():
    mon = _monitor(FakeProber(), stall_after_s=0.01, stall_every_s=0.01)

    async def slow_then_timeout():
        await asyncio.sleep(0.08)
        raise ProviderTimeout("chat timeout while waiting for the answer (limit 120 s)")

    with pytest.raises(ProviderTimeout) as info:
        await mon.guard(slow_then_timeout, url=REMOTE, label="p")
    assert info.value.network_reachable is True
    assert mon.state == UNKNOWN  # nothing suggested an outage


# ── the router ────────────────────────────────────────────────────────────


class _Adapter:
    def __init__(self, base_url: str, behaviour) -> None:
        self.base_url = base_url
        self.behaviour = behaviour
        self.calls = 0

    async def chat(self, model, messages, **kwargs):
        self.calls += 1
        return await self.behaviour()


class _Registry:
    def __init__(self, adapters: dict[str, _Adapter]) -> None:
        self.adapters = adapters
        self.failures: list[str] = []

    def get_adapter(self, pid):
        return self.adapters.get(pid)

    def list_enabled(self):
        return []  # probe targets come from the monitor's own list here

    async def record_request(self, pid, *a, success=True, **k):
        if not success:
            self.failures.append(pid)

    async def update_health(self, *a, **k):
        return None


def _router(adapters: dict[str, _Adapter], mon: NetworkMonitor) -> tuple[ProviderRouter, _Registry]:
    registry = _Registry(adapters)
    router = ProviderRouter(registry, network=mon)
    mon.set_targets(lambda: [a.base_url for a in adapters.values()])
    routes = [SimpleNamespace(provider_id=pid, model="m", score=1.0) for pid in adapters]
    router.resolve = lambda model: routes  # type: ignore[method-assign]
    return router, registry


async def _raise_dns():
    raise _dns_failure()


@pytest.mark.asyncio
async def test_offline_is_reported_as_such_and_not_held_against_the_provider():
    prober = FakeProber(up=False)
    mon = _monitor(prober)
    remote = _Adapter(REMOTE, _raise_dns)
    router, registry = _router({"openwebui": remote}, mon)

    with pytest.raises(ProvidersExhausted) as info:
        await router.route_chat("openwebui/m", [{"role": "user", "content": "hi"}])
    err = info.value.last_error
    assert isinstance(err, ProviderNetworkError) and err.kind == "network_offline"
    assert "DNS lookup for chat.provider.example failed" in str(err)
    assert registry.failures == []  # provider health untouched
    assert mon.state == OFFLINE


@pytest.mark.asyncio
async def test_while_offline_remote_requests_fail_fast_and_local_ones_still_run():
    prober = FakeProber(up=False)
    clock = Clock()
    mon = _monitor(prober, clock=clock)
    remote = _Adapter(REMOTE, AsyncMock(return_value={"choices": [], "usage": {}}))
    local = _Adapter(LOCAL, AsyncMock(return_value={"choices": [{"message": {"content": "local"}}], "usage": {}}))
    router, _ = _router({"openwebui": remote, "litellm-local": local}, mon)
    mon.set_targets(lambda: [REMOTE])
    await mon.check()

    result = await router.route_chat("m", [])
    assert result["choices"][0]["message"]["content"] == "local"
    assert remote.calls == 0  # never waited on
    assert mon.failed_fast == 1


@pytest.mark.asyncio
async def test_first_request_after_the_tunnel_goes_through():
    prober = FakeProber(up=False)
    clock = Clock()
    mon = _monitor(prober, clock=clock)
    remote = _Adapter(REMOTE, AsyncMock(return_value={"choices": [{"message": {"content": "hi"}}], "usage": {}}))
    router, _ = _router({"openwebui": remote}, mon)
    await mon.check()
    assert mon.offline

    prober.up = True
    clock.advance(3)  # older than recheck_s: the request re-checks first
    result = await router.route_chat("openwebui/m", [])
    assert result["choices"][0]["message"]["content"] == "hi"
    assert mon.state == ONLINE


@pytest.mark.asyncio
async def test_a_provider_down_while_the_network_is_up_is_still_its_own_failure():
    prober = FakeProber()
    prober.by_host = {"chat.provider.example": False, "llm.other.example": True}
    mon = _monitor(prober)
    remote = _Adapter(REMOTE, _raise_dns)
    other = _Adapter(OTHER, AsyncMock(side_effect=ProviderUnavailable("upstream error (HTTP 503)")))
    router, registry = _router({"openwebui": remote, "other": other}, mon)

    with pytest.raises(ProvidersExhausted) as info:
        await router.route_chat("m", [])
    assert not isinstance(info.value.last_error, ProviderNetworkError)
    assert registry.failures == ["openwebui", "other"]
    assert mon.state == ONLINE


@pytest.mark.asyncio
async def test_a_dropped_link_mid_request_is_connection_lost():
    prober = FakeProber()
    mon = _monitor(prober, stall_after_s=0.01, stall_every_s=0.01)

    async def hangs():
        prober.up = False  # the train enters the tunnel after the request left
        await asyncio.sleep(3600)

    router, registry = _router({"openwebui": _Adapter(REMOTE, hangs)}, mon)
    with pytest.raises(ProvidersExhausted) as info:
        await asyncio.wait_for(router.route_chat("openwebui/m", []), timeout=5)
    err = info.value.last_error
    assert isinstance(err, ProviderNetworkError) and err.kind == "connection_lost"
    assert registry.failures == []


@pytest.mark.asyncio
async def test_the_access_line_names_the_provider_that_failed():
    from ollabridge.core.logsetup import request_facts

    facts, token = request_facts.begin()
    try:
        mon = _monitor(FakeProber(up=False))
        router, _ = _router({"openwebui": _Adapter(REMOTE, _raise_dns)}, mon)
        with pytest.raises(ProvidersExhausted):
            await router.route_chat("openwebui/m", [])
    finally:
        request_facts.end(token)
    assert facts["route"] == "openwebui"  # not "ollama/local"


# ── what the client sees ──────────────────────────────────────────────────


def test_offline_maps_to_503_network_offline():
    from ollabridge.api.main import _provider_failure

    exc = ProvidersExhausted(
        "All providers failed",
        last_error=ProviderNetworkError("DNS lookup for chat.provider.example failed", retry_after=4),
    )
    failure = _provider_failure(exc, "openwebui/m", has_tools=False)
    assert failure["status"] == 503 and failure["code"] == "network_offline"
    assert failure["type"] == "api_connection_error" and failure["retry_after"] == 4
    assert "offline" in failure["message"] and "Local models still work" in failure["message"]

    lost = _provider_failure(
        ProviderNetworkError("network changed", kind="connection_lost"), "openwebui/m", has_tools=False
    )
    assert lost["status"] == 503 and lost["code"] == "connection_lost" and "safe" in lost["message"]


def test_a_slow_reachable_provider_says_the_network_was_fine():
    from ollabridge.api.main import _provider_failure

    exc = ProviderTimeout("chat timeout while waiting for the answer (limit 120 s)")
    exc.network_reachable = True
    failure = _provider_failure(exc, "openwebui/m", has_tools=False)
    assert failure["code"] == "provider_timeout" and "network is fine" in failure["message"]


@pytest.fixture
def app_client(monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from ollabridge.core.registry import RuntimeNodeState
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")
    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        # Let the provider add-on finish starting so it cannot replace the
        # router a test sets (it sets hf_catalog_sync last).
        deadline = time.monotonic() + 10
        while not hasattr(app.state, "hf_catalog_sync") and time.monotonic() < deadline:
            time.sleep(0.02)
        asyncio.run(
            app.state.obridge.registry.upsert(
                RuntimeNodeState(
                    node_id="local", connector="local_ollama", endpoint="http://localhost:11434",
                    tags=["local"], models=[], capacity=1, meta={},
                )
            )
        )
        yield app, client


class _OfflineRouter:
    def resolve(self, model):
        return [SimpleNamespace(provider_id="openwebui")]

    async def route_chat(self, model, messages, **kwargs):
        raise ProvidersExhausted(
            "All providers failed",
            last_error=ProviderNetworkError("DNS lookup for chat.provider.example failed", retry_after=7),
        )


def test_the_api_answers_503_with_retry_after_and_health_shows_it(app_client, monkeypatch):
    from ollabridge.core import connectivity

    app, client = app_client
    app.state.provider_router = _OfflineRouter()
    local = AsyncMock()
    with patch("ollabridge.providers.ollama_client.chat_message", new=local):
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key-abc"},
            json={"model": "openwebui/m", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 503, r.text
    assert r.headers["Retry-After"] == "7"
    assert r.headers["X-OllaBridge-Network"] == "offline"
    err = r.json()["detail"]["error"]
    assert err["code"] == "network_offline" and err["type"] == "api_connection_error"
    local.assert_not_called()

    monkeypatch.setenv("OLLABRIDGE_NETWORK_CHECK", "on")
    connectivity.NETWORK._mark_offline("DNS lookup for chat.provider.example failed")
    net = client.get("/health").json()["network"]
    assert net["state"] == "offline" and net["reason"].startswith("DNS lookup")
    assert net["outages"] == 1 and net["since"]
