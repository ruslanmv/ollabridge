"""Settings → Rate limits: OllaBridge's own inbound limit, outbound pacing per
provider, and the fail-fast / wait-and-retry choice on an upstream rate limit.

The defaults must change nothing: the inbound limit is off (a caller that makes
many calls is not newly throttled), and a provider with no settings is neither
paced nor retried, failing fast exactly as before. An Open WebUI server
answers its per-user limit with HTTP 400 ``{"detail": "Rate limit
exceeded..."}``; with limits set, calls wait their turn instead of failing.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from ollabridge.addons.providers import pacing
from ollabridge.addons.providers.errors import (
    ProviderBadRequest,
    ProviderRateLimited,
    is_rate_limit,
    parse_retry_after,
)
from ollabridge.addons.providers.models import HealthStatus
from ollabridge.core import rate_limits
from ollabridge.core import runtime_settings as rts
from ollabridge.core.rate_limits import InboundLimiter, ProviderLimit, RateLimitSettings
from ollabridge.core.settings import settings

KEY_A = "rl-key-a"
KEY_B = "rl-key-b"
AUTH_A = {"Authorization": f"Bearer {KEY_A}"}
AUTH_B = {"X-API-Key": KEY_B}
CHAT = {"model": "openwebui/gemma-3-27b", "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    rate_limits.reload()
    rate_limits.INBOUND.reset()
    pacing.reset()
    yield
    rate_limits.reload()
    rate_limits.INBOUND.reset()
    pacing.reset()


def _open_webui_rate_limit() -> ProviderRateLimited:
    # What the Open WebUI adapter now raises for an upstream HTTP 400 "Rate limit exceeded".
    return ProviderRateLimited(
        'rate limited (HTTP 400): {"detail":"Rate limit exceeded. Please try again later."}',
        upstream_status=400,
    )


class FlakyAdapter:
    """Rate-limited for the first ``failures`` calls, then answers."""

    def __init__(self, failures: int = 0, make_exc=_open_webui_rate_limit) -> None:
        self.failures = failures
        self.make_exc = make_exc
        self.calls = 0

    async def chat(self, model, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.make_exc()
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 3}}


class FakeRegistry:
    def __init__(self, adapter) -> None:
        self.adapter = adapter
        self.health: list[HealthStatus] = []

    def get_adapter(self, pid):
        return self.adapter

    def get_state(self, pid):
        return SimpleNamespace(request_count=self.adapter.calls)

    async def record_request(self, *a, **k):
        return None

    async def update_health(self, pid, health, error=None):
        self.health.append(health)

    def list_providers(self):
        return [SimpleNamespace(id="openwebui", name="Team chat", kind="open_webui", enabled=True)]


def make_router(adapter):
    from ollabridge.addons.providers.router import ProviderRouter

    registry = FakeRegistry(adapter)
    router = ProviderRouter(registry)
    route = SimpleNamespace(provider_id="openwebui", model=CHAT["model"], score=0.9)
    router.resolve = lambda model: [route]  # type: ignore[method-assign]
    return router, registry


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS", f"{KEY_A},{KEY_B}")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")

    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as client:
        # Let the provider add-on finish starting (it sets hf_catalog_sync last,
        # on success or failure), so it cannot replace the router set below.
        deadline = time.monotonic() + 10
        while not hasattr(app.state, "hf_catalog_sync") and time.monotonic() < deadline:
            time.sleep(0.02)
        yield app, client


def _use(app, adapter):
    router, registry = make_router(adapter)
    app.state.provider_router = router
    app.state.provider_registry = registry
    return registry


# ── Defaults change nothing ─────────────────────────────────────────────


def test_defaults_are_todays_behaviour():
    cfg = rate_limits.current()
    assert cfg.inbound.enabled is False
    assert cfg.providers == {}
    limit = rate_limits.provider_limit("openwebui")
    assert limit.requests_per_minute == 0 and limit.max_concurrent == 0
    assert limit.on_rate_limit == "fail_fast" and limit.cooldown_seconds == 0


@pytest.mark.parametrize("raw,rpm", [("60/minute", 60), ("2/second", 120), ("600/hour", 10), ("junk", 60), ("", 60)])
def test_inbound_default_follows_the_rate_limit_env_setting(raw, rpm):
    assert rate_limits.rpm_from_env(raw) == rpm


def test_inbound_limit_is_off_by_default_so_many_calls_pass(app_client):
    app, client = app_client
    adapter = FlakyAdapter()
    _use(app, adapter)
    statuses = {client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT).status_code for _ in range(70)}
    assert statuses == {200}                                    # 70 calls > the 60/minute default value
    assert adapter.calls == 70


# ── Inbound limit ───────────────────────────────────────────────────────


def test_inbound_limit_refuses_past_n_per_minute_per_client_and_key(app_client):
    app, client = app_client
    _use(app, FlakyAdapter())
    r = client.put("/admin/rate-limits", headers=AUTH_A, json={"inbound": {"enabled": True, "requests_per_minute": 3}})
    assert r.status_code == 200, r.text

    codes = [client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT).status_code for _ in range(3)]
    assert codes == [200, 200, 200]
    refused = client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT)
    assert refused.status_code == 429
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert refused.headers["X-RateLimit-Limit"] == "3"
    err = refused.json()["detail"]["error"]
    assert err["code"] == "rate_limited" and err["type"] == "rate_limit_error"
    assert "OllaBridge's own request limit" in err["message"]

    # Another API key from the same address has its own budget.
    assert client.post("/v1/chat/completions", headers=AUTH_B, json=CHAT).status_code == 200
    # Reads and the dashboard's admin API are never limited.
    assert client.get("/v1/models", headers=AUTH_A).status_code != 429
    view = client.get("/admin/rate-limits", headers=AUTH_A).json()
    assert view["inbound"]["refused_last_hour"] == 1
    client_label = view["inbound"]["recent"][0]["client"]
    assert "key #" in client_label and KEY_A not in client_label   # a fingerprint, never the key


def test_inbound_limiter_window_and_lowered_limit():
    now = [0.0]
    limiter = InboundLimiter(clock=lambda: now[0], wall=lambda: 1e9 + now[0])
    assert [limiter.hit("c", 2) for _ in range(2)] == [None, None]
    assert limiter.hit("c", 2) == pytest.approx(60.0)
    now[0] = 30.0
    assert limiter.hit("other", 2) is None                      # buckets are separate
    now[0] = 60.5
    assert limiter.hit("c", 2) is None                          # the old hits aged out
    assert limiter.hit("c", 1) == pytest.approx(60.0)           # limit lowered below the window's count


# ── Settings API and persistence ───────────────────────────────────────


def test_settings_persist_in_the_runtime_store_and_drop_default_entries(app_client):
    app, client = app_client
    _use(app, FlakyAdapter())
    body = {
        "inbound": {"enabled": False, "requests_per_minute": 90},
        "providers": {
            "openwebui": {"requests_per_minute": 12, "max_concurrent": 2, "on_rate_limit": "wait_retry",
                          "max_wait_seconds": 180, "cooldown_seconds": 60},
            "groq-free": ProviderLimit().model_dump(),          # equal to the defaults: not kept
        },
    }
    r = client.put("/admin/rate-limits", headers=AUTH_A, json=body)
    assert r.status_code == 200, r.text
    stored = json.loads(rts._STORE_FILE.read_text())["rate_limits"]
    assert stored["inbound"]["requests_per_minute"] == 90
    assert set(stored["providers"]) == {"openwebui"}
    assert stored["providers"]["openwebui"]["on_rate_limit"] == "wait_retry"

    rate_limits.reload()                                        # as after a restart
    assert rate_limits.provider_limit("openwebui").max_concurrent == 2

    view = client.get("/admin/rate-limits", headers=AUTH_A).json()
    row = next(p for p in view["providers"] if p["id"] == "openwebui")
    assert row["configured"] is True and row["name"] == "Team chat"
    assert view["defaults"]["suggested"]["on_rate_limit"] == "wait_retry"  # offered for every provider


@pytest.mark.parametrize("body", [
    {"providers": {"openwebui": {"on_rate_limit": "panic"}}},
    {"providers": {"openwebui": {"requests_per_minute": -1}}},
    {"providers": {"openwebui": {"max_wait_seconds": 0}}},
    {"inbound": {"enabled": True, "requests_per_minute": 0}},
    {"inbound": {"enabeld": True}},                             # a typo is refused, not ignored
    {"providers": {"bad id!": {}}},
])
def test_invalid_settings_are_refused(app_client, body):
    _, client = app_client
    r = client.put("/admin/rate-limits", headers=AUTH_A, json=body)
    assert r.status_code == 422, r.text
    assert rate_limits.current() == RateLimitSettings()


def test_the_rate_limits_api_needs_auth(app_client):
    _, client = app_client
    assert client.get("/admin/rate-limits").status_code == 401
    assert client.put("/admin/rate-limits", json={}).status_code == 401


# ── Upstream rate limit: fail fast (default) ───────────────────────────


def test_default_fails_fast_without_cooldown(app_client):
    app, client = app_client
    adapter = FlakyAdapter(failures=1)
    registry = _use(app, adapter)
    r = client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT)
    assert r.status_code == 429, r.text
    assert r.headers["Retry-After"] == "5"                      # what OllaBridge always sent
    assert "Rate limit exceeded" in r.json()["detail"]["error"]["message"]
    assert adapter.calls == 1                                   # not retried
    assert HealthStatus.QUOTA_EXHAUSTED not in registry.health  # still routable afterwards
    assert client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT).status_code == 200
    assert adapter.calls == 2                                   # no cooldown by default


def test_fail_fast_with_cooldown_answers_429_without_calling_the_provider(app_client):
    app, client = app_client
    adapter = FlakyAdapter(failures=1)
    _use(app, adapter)
    client.put("/admin/rate-limits", headers=AUTH_A,
               json={"providers": {"openwebui": {"cooldown_seconds": 30}}})

    first = client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT)
    assert first.status_code == 429 and 29 <= int(first.headers["Retry-After"]) <= 30
    second = client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT)
    assert second.status_code == 429
    assert "cooling down" in second.json()["detail"]["error"]["message"]
    assert adapter.calls == 1                                   # the provider was left alone

    row = next(p for p in client.get("/admin/rate-limits", headers=AUTH_A).json()["providers"]
               if p["id"] == "openwebui")
    state = row["state"]
    assert state["cooling_down_until"] and state["cooldown_remaining_s"] > 25
    assert state["rate_limited_last_hour"] == 1 and state["refused_in_cooldown"] == 1
    assert state["recent"][0]["outcome"] == "failed fast" and state["recent"][0]["status"] == 400


# ── Upstream rate limit: wait and retry ────────────────────────────────


def test_wait_and_retry_recovers_through_the_api(app_client, monkeypatch):
    monkeypatch.setattr(pacing, "BASE_BACKOFF_SECONDS", 0.01)
    app, client = app_client
    adapter = FlakyAdapter(failures=2)
    _use(app, adapter)
    client.put("/admin/rate-limits", headers=AUTH_A,
               json={"providers": {"openwebui": {"on_rate_limit": "wait_retry", "max_wait_seconds": 30}}})

    r = client.post("/v1/chat/completions", headers=AUTH_A, json=CHAT)
    assert r.status_code == 200, r.text
    assert r.json()["choices"][0]["message"]["content"] == "ok"
    assert adapter.calls == 3

    row = next(p for p in client.get("/admin/rate-limits", headers=AUTH_A).json()["providers"]
               if p["id"] == "openwebui")
    assert row["requests"] == 3                                 # listed because it is in use
    state = row["state"]
    assert state["retries"] == 2 and state["recovered"] == 1
    assert [e["outcome"].split(" (")[0] for e in state["recent"]] == ["retrying in 1s", "retrying in 1s"]


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def wall(self) -> float:
        return 1_700_000_000.0 + self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _gate(ft: FakeTime) -> pacing.ProviderGate:
    return pacing.ProviderGate("openwebui", clock=ft.clock, wall=ft.wall, sleep=ft.sleep)


def test_wait_and_retry_honours_retry_after_and_backs_off():
    ft = FakeTime()
    gate = _gate(ft)
    calls = []

    def limited():
        exc = _open_webui_rate_limit()
        exc.retry_after = 7.0
        return exc

    async def fn():
        calls.append(ft.now)
        if len(calls) <= 2:
            raise limited()
        return "ok"

    limit = ProviderLimit(on_rate_limit="wait_retry", max_wait_seconds=60)
    assert asyncio.run(gate.call(limit, fn)) == "ok"
    # Retry-After 7s beats the 5s first step; the second step (10s) beats 7s.
    assert [round(t - calls[0], 3) for t in calls] == [0, 7, 17]
    assert gate.retries == 2 and gate.recovered == 1


def test_wait_and_retry_gives_up_at_the_max_wait():
    ft = FakeTime()
    gate = _gate(ft)
    calls = []

    async def fn():
        calls.append(ft.now)
        raise _open_webui_rate_limit()

    limit = ProviderLimit(on_rate_limit="wait_retry", max_wait_seconds=20, cooldown_seconds=5)
    with pytest.raises(ProviderRateLimited) as ei:
        asyncio.run(gate.call(limit, fn))
    # Waits 5 then 10 (15s); the next step (20s) would pass the 20s budget.
    assert [round(t - calls[0], 3) for t in calls] == [0, 5, 15]
    assert ei.value.retry_after == pytest.approx(20.0)          # the client is told to back off
    assert gate.events[-1]["outcome"].startswith("gave up after 15s")


def test_a_cooldown_also_holds_back_other_requests_in_wait_mode():
    ft = FakeTime()
    gate = _gate(ft)
    gate.cooldown_until = ft.now + 40
    seen = []

    async def fn():
        seen.append(ft.now)
        return "ok"

    asyncio.run(gate.call(ProviderLimit(on_rate_limit="wait_retry", max_wait_seconds=60), fn))
    assert seen == [1040.0]
    gate.cooldown_until = ft.now + 90
    with pytest.raises(ProviderRateLimited) as ei:                # beyond this request's max wait
        asyncio.run(gate.call(ProviderLimit(on_rate_limit="wait_retry", max_wait_seconds=60), fn))
    assert ei.value.local is True and len(seen) == 1


def test_non_rate_limit_errors_are_not_retried():
    ft = FakeTime()
    gate = _gate(ft)
    calls = []

    async def fn():
        calls.append(1)
        raise ProviderBadRequest("bad request (HTTP 400): model not found")

    with pytest.raises(ProviderBadRequest):
        asyncio.run(gate.call(ProviderLimit(on_rate_limit="wait_retry"), fn))
    assert calls == [1] and not gate.events


# ── Pacing and concurrency ─────────────────────────────────────────────


def test_pacing_spaces_requests_evenly():
    ft = FakeTime()
    gate = _gate(ft)
    starts = []

    async def fn():
        starts.append(ft.now)
        return "ok"

    async def run():
        for _ in range(4):
            await gate.call(ProviderLimit(requests_per_minute=60), fn)

    asyncio.run(run())
    assert [t - starts[0] for t in starts] == [0, 1, 2, 3]      # one per 60/60 s


def test_pacing_with_concurrent_callers_in_real_time():
    gate = pacing.ProviderGate("openwebui")
    starts = []

    async def fn():
        starts.append(time.monotonic())
        return "ok"

    async def run():
        limit = ProviderLimit(requests_per_minute=1200)        # one per 50 ms
        await asyncio.gather(*(gate.call(limit, fn) for _ in range(4)))

    asyncio.run(run())
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert all(g >= 0.045 for g in gaps), gaps


def test_max_concurrent_caps_requests_in_flight():
    gate = pacing.ProviderGate("openwebui")
    running = 0
    peak = 0

    async def fn():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "ok"

    async def run():
        limit = ProviderLimit(max_concurrent=2)
        return await asyncio.gather(*(gate.call(limit, fn) for _ in range(6)))

    assert asyncio.run(run()) == ["ok"] * 6
    assert peak == 2 and gate.in_flight == 0 and not gate._waiters


def test_a_full_queue_answers_429_after_the_max_wait():
    gate = pacing.ProviderGate("openwebui")
    release = None

    async def slow():
        await release.wait()
        return "slow"

    async def fast():
        return "fast"

    async def run():
        nonlocal release
        release = asyncio.Event()
        limit = ProviderLimit(max_concurrent=1, max_wait_seconds=1)
        holder = asyncio.create_task(gate.call(limit, slow))
        await asyncio.sleep(0)                                  # the holder takes the only slot
        start = time.monotonic()
        with pytest.raises(ProviderRateLimited) as ei:
            await gate.call(limit, fast)
        waited = time.monotonic() - start
        release.set()
        assert await holder == "slow"
        return ei.value, waited

    exc, waited = asyncio.run(run())
    assert exc.local is True and "max wait" in str(exc) and 0.9 <= waited < 3
    assert gate.in_flight == 0 and not gate._waiters


def test_an_unconfigured_provider_passes_straight_through():
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    async def run():
        return await asyncio.gather(*(pacing.call("groq-free", fn) for _ in range(20)))

    assert asyncio.run(run()) == ["ok"] * 20 and len(calls) == 20


# ── Recognising a rate limit ───────────────────────────────────────────


def test_rate_limit_detection_and_retry_after_parsing():
    assert is_rate_limit(_open_webui_rate_limit())
    assert is_rate_limit(ProviderBadRequest('bad request (HTTP 400): {"detail":"Rate limit exceeded."}'))
    assert not is_rate_limit(ProviderBadRequest("bad request (HTTP 400): unknown model"))
    assert not is_rate_limit(RuntimeError("rate limit"))
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("") is None and parse_retry_after("soon") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0   # in the past


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,headers,retry_after", [
    (400, '{"detail":"Rate limit exceeded. Please try again later."}', {}, None),
    (429, "slow down", {"Retry-After": "12"}, 12.0),
])
async def test_open_webui_maps_rate_limits(monkeypatch, status, body, headers, retry_after):
    from ollabridge.addons.providers.adapters import open_webui as ow_mod

    real_client = ow_mod.httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(status, text=body, headers=headers))
    monkeypatch.setattr(ow_mod.httpx, "AsyncClient", lambda *a, **kw: real_client(*a, **{**kw, "transport": transport}))
    adapter = ow_mod.OpenWebUIAdapter(base_url="https://chat.example.test/api", api_key="sk-secret-123")
    with pytest.raises(ProviderRateLimited) as ei:
        await adapter.chat("openwebui/m", [{"role": "user", "content": "hi"}])
    assert ei.value.upstream_status == status and ei.value.retry_after == retry_after
    assert "sk-secret-123" not in str(ei.value)


@pytest.mark.asyncio
async def test_the_router_does_not_take_a_rate_limited_provider_out_of_routing():
    router, registry = make_router(FlakyAdapter(failures=1))
    with pytest.raises(RuntimeError) as ei:
        await router.route_chat(CHAT["model"], CHAT["messages"])
    assert isinstance(ei.value.last_error, ProviderRateLimited)
    assert HealthStatus.QUOTA_EXHAUSTED not in registry.health
    assert (await router.route_chat(CHAT["model"], CHAT["messages"]))["choices"][0]["message"]["content"] == "ok"
