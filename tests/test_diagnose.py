"""`ollabridge diagnose`: measuring one endpoint without hurting it.

Two incidents on 2026-11-12 set the requirements. An MCP server's HTTP edge
limited a key to 60 requests a minute; a client that opened a session per
tool call spent four requests on each, so 15 calls in a minute were enough
for a 429 that the client did not retry. And a chat model needed longer than
the caller's 60 s per try for a large prompt, which became four timeouts in
a row. Pinned here:

* the diagnosis reads a published limit from headers, or finds it by
  counting what the endpoint accepted before its first refusal;
* the concurrency sweep finds the level past which more calls stop helping,
  and stops there: it never runs a higher level against a saturated or
  refusing endpoint;
* the budget of HTTP requests is a hard cap, an unusable endpoint gets one
  request, ``--plan`` and a declined ``--find-limit`` send none;
* an MCP call with a session of its own is counted as the four requests it
  is, no tool runs unless named, and the session is always ended;
* the recommendations follow from the numbers (80% of the limit, the
  caller's timeout, Retry-After);
* the settings audit flags a provider in use that fails fast, and
  ``--apply`` changes that one provider's limits and nothing else.

No test touches the network: the endpoints are ``httpx.MockTransport``
handlers.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import httpx
import pytest
from typer.testing import CliRunner

from ollabridge.core import rate_limits
from ollabridge.core.rate_limits import ProviderLimit, RateLimitSettings
from ollabridge.diagnose import audit, recommend, targets
from ollabridge.diagnose.engine import plan_levels
from ollabridge.diagnose.models import LevelResult, Sample
from ollabridge.diagnose.ratelimit import is_rate_limit, parse_duration, rate_headers
from ollabridge.diagnose.runner import (
    ChatOptions,
    McpOptions,
    chat_plan,
    diagnose_chat,
    diagnose_mcp,
)
from ollabridge.diagnose.targets import ChatTarget, McpTarget

BASE = "https://models.example.test/v1"
MCP_URL = "https://tools.example.test/mcp"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class Window:
    """A sliding-window request limit, as an HTTP edge enforces it."""

    def __init__(self, limit: int | None, seconds: float = 60.0, clock=time.monotonic) -> None:
        self.limit, self.seconds, self.clock = limit, seconds, clock
        self.hits: deque[float] = deque()

    def allow(self) -> bool:
        if self.limit is None:
            return True
        now = self.clock()
        while self.hits and self.hits[0] <= now - self.seconds:
            self.hits.popleft()
        if len(self.hits) >= self.limit:
            return False
        self.hits.append(now)
        return True


class FakeChat:
    """An OpenAI-compatible endpoint with a capacity and, optionally, a limit.

    Up to ``capacity`` requests are served in ``service`` seconds each; every
    request beyond that slows all of them down, as an overloaded model does.
    """

    def __init__(
        self,
        *,
        limit: int | None = None,
        window: float = 60.0,
        capacity: int = 64,
        service: float = 0.002,
        retry_after: int | None = None,
        limit_status: int = 429,
        headers: dict[str, str] | None = None,
        status: int = 200,
        clock=time.monotonic,
    ) -> None:
        self.window = Window(limit, window, clock)
        self.capacity, self.service = capacity, service
        self.retry_after, self.limit_status = retry_after, limit_status
        self.headers = headers or {}
        self.status = status
        self.requests = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.bodies: list[dict] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Incorrect API key provided"}})
        if not self.window.allow():
            extra = {"Retry-After": str(self.retry_after)} if self.retry_after is not None else {}
            return httpx.Response(
                self.limit_status, headers=extra, json={"detail": "Rate limit exceeded. Please try again later."}
            )
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.service * (1 + 2 * max(0, self.in_flight - self.capacity)))
        finally:
            self.in_flight -= 1
        if body.get("stream"):
            chunks = [{"choices": [{"delta": {"content": "pong "}}]} for _ in range(20)]
            chunks.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 20}})
            text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream", **self.headers}, content=text)
        prompt = body["messages"][0]["content"]
        return httpx.Response(
            200,
            headers=self.headers,
            json={
                "choices": [{"message": {"role": "assistant", "content": "pong"}}],
                "usage": {"prompt_tokens": max(1, len(prompt) // 4), "completion_tokens": 1},
            },
        )


class FakeMcp:
    """A Streamable HTTP MCP server behind an edge that counts every request."""

    def __init__(
        self,
        *,
        limit: int | None = None,
        sessions: bool = True,
        ping: bool = True,
        retry_after: int | None = None,
        tool_seconds: float = 0.01,
        clock=time.monotonic,
    ) -> None:
        self.window = Window(limit, 60.0, clock)
        self.sessions, self.ping, self.retry_after, self.tool_seconds = sessions, ping, retry_after, tool_seconds
        self.calls: list[str] = []
        self.tool_calls: list[dict] = []
        self.open: set[str] = set()
        self.requests = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if not self.window.allow():
            extra = {"Retry-After": str(self.retry_after)} if self.retry_after is not None else {}
            return httpx.Response(429, headers=extra, json={"error": "rate limit exceeded"})
        if request.method == "DELETE":
            self.calls.append("DELETE")
            self.open.discard(request.headers.get("mcp-session-id", ""))
            return httpx.Response(204)
        body = json.loads(request.content)
        method = body["method"]
        self.calls.append(method)

        def result(value: dict, **headers: str) -> httpx.Response:
            return httpx.Response(200, headers=headers, json={"jsonrpc": "2.0", "id": body["id"], "result": value})

        if method == "initialize":
            session = f"session-{len(self.calls)}"
            if self.sessions:
                self.open.add(session)
            return result(
                {"protocolVersion": "2025-06-18", "serverInfo": {"name": "fake-tools", "version": "1.0"}, "capabilities": {}},
                **({"mcp-session-id": session} if self.sessions else {}),
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "ping":
            if not self.ping:
                return httpx.Response(
                    200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "Method not found"}}
                )
            return result({})
        if method == "tools/list":
            # As an SSE stream, the other shape the transport allows.
            message = {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "zone_check"}, {"name": "whois"}]}}
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=f"event: message\ndata: {json.dumps(message)}\n\n"
            )
        if method == "tools/call":
            self.tool_calls.append(body["params"])
            await asyncio.sleep(self.tool_seconds)
            return result({"content": [{"type": "text", "text": "ok"}], "isError": False})
        return httpx.Response(400, json={"error": "unknown method"})


async def _chat(server: FakeChat, opts: ChatOptions, **kw) -> dict:
    async with ChatTarget(BASE, "some-model", api_key="sk-test-secret", transport=httpx.MockTransport(server)) as target:
        return await diagnose_chat(target, opts, **kw)


async def _mcp(server: FakeMcp, opts: McpOptions, **kw) -> dict:
    headers = {"Authorization": "Bearer mcp-test-secret"}
    async with McpTarget(MCP_URL, headers=headers, transport=httpx.MockTransport(server)) as target:
        return await diagnose_mcp(target, opts, **kw)


# ── reading limits ────────────────────────────────────────────────────────


def test_published_limits_are_read_from_every_header_family():
    ietf = rate_headers({"RateLimit-Limit": "60", "RateLimit-Remaining": "41", "RateLimit-Reset": "30", "RateLimit-Policy": "60;w=60"})
    assert (ietf.limit, ietf.remaining, ietf.reset_seconds, ietf.window_seconds) == (60, 41, 30, 60)
    assert ietf.per_minute == 60

    newer = rate_headers({"RateLimit": '"default";r=50;t=30', "RateLimit-Policy": '"default";q=100;w=120'})
    assert (newer.limit, newer.remaining, newer.window_seconds, newer.per_minute) == (100, 50, 120, 50)

    openai = rate_headers({"x-ratelimit-limit-requests": "500", "x-ratelimit-remaining-requests": "499", "x-ratelimit-reset-requests": "6m0s"})
    assert (openai.limit, openai.remaining, openai.reset_seconds, openai.window_seconds) == (500, 499, 360, None)

    plain = rate_headers({"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "12"})
    assert (plain.limit, plain.remaining, plain.reset_seconds) == (60, 0, 12)
    assert rate_headers({"content-type": "application/json"}) is None
    assert parse_duration("250ms") == 0.25 and parse_duration("1h2m3s") == 3723 and parse_duration("soon") is None


def test_a_rate_limit_is_recognised_whatever_its_status():
    assert is_rate_limit(429, "")
    assert is_rate_limit(400, '{"detail":"Rate limit exceeded. Please try again later."}')
    assert not is_rate_limit(400, '{"detail":"model not found"}')
    assert not is_rate_limit(500, "rate limit")


# ── the sweep ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_sweep_finds_the_knee_and_stops_past_it():
    server = FakeChat(capacity=2, service=0.05)
    report = await _chat(server, ChatOptions(levels=[1, 2, 4, 8], per_level=6))

    assert [lv["concurrency"] for lv in report["levels"]] == [1, 2, 4]  # 8 never ran
    assert "throughput fell" in report["sweep_ended"]
    assert server.max_in_flight <= 4
    advice = report["recommendations"]
    assert advice["concurrency"] == 2 and advice["provider_limit"]["max_concurrent"] == 2
    assert advice["provider_limit"]["on_rate_limit"] == "wait_retry"
    assert report["limits"]["upper"]["max_clean_concurrency"] == 4
    assert report["baseline"]["first_token_s"] is not None and report["baseline"]["speed_tokens_out"] == 20
    assert report["safety"]["http_requests"] == server.requests


@pytest.mark.asyncio
async def test_the_sweep_stops_at_the_first_refusal_and_counts_the_window():
    server = FakeChat(limit=12)
    report = await _chat(server, ChatOptions(levels=[1, 2, 4, 8], per_level=6))

    last = report["levels"][-1]
    assert last["concurrency"] == 2 and last["errors"] == {"rate_limited": last["requests"] - last["ok"]}
    assert len(report["levels"]) == 2  # 4 and 8 never ran against a refusing endpoint
    rate = report["rate_limit"]
    assert rate["source"] == "observed" and rate["per_minute"] == 12
    assert rate["signalled_as"] == "HTTP 429" and rate["retry_after_sent"] is False
    assert server.requests <= 12 + 2  # the refused ones, at most one per worker


@pytest.mark.asyncio
async def test_an_open_webui_style_400_is_a_rate_limit_and_retry_after_is_reported():
    server = FakeChat(limit=8, limit_status=400, retry_after=30)
    report = await _chat(server, ChatOptions(levels=[1, 2], per_level=6, stream=False))
    rate = report["rate_limit"]
    assert rate["signalled_as"] == "HTTP 400 with a rate-limit message in its body"
    assert rate["retry_after_sent"] is True and rate["retry_after_s"] == 30
    assert report["recommendations"]["provider_limit"]["cooldown_seconds"] == 30


@pytest.mark.asyncio
async def test_a_published_limit_is_used_without_ever_reaching_it():
    server = FakeChat(headers={"RateLimit-Limit": "60", "RateLimit-Remaining": "40", "RateLimit-Policy": "60;w=60"})
    report = await _chat(server, ChatOptions(levels=[1, 2], per_level=4))
    rate = report["rate_limit"]
    assert (rate["source"], rate["per_minute"], rate["exact"]) == ("header", 60, True)
    assert rate["signalled_as"] is None  # never refused
    assert report["recommendations"]["requests_per_minute"] == 48  # 80% of 60


# ── safety ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_request_budget_is_a_hard_cap():
    server = FakeChat()
    report = await _chat(server, ChatOptions(levels=[1, 2, 4, 8, 16], per_level=20, max_requests=25))
    assert server.requests <= 25
    assert report["safety"]["http_requests"] == server.requests


@pytest.mark.asyncio
async def test_an_endpoint_that_refuses_the_key_gets_one_request():
    server = FakeChat(status=401)
    report = await _chat(server, ChatOptions())
    assert server.requests == 1
    assert report["baseline"] == {} and report["levels"] == []
    assert "API key" in report["safety"]["stopped"]
    assert "sk-test-secret" not in json.dumps(report)


@pytest.mark.asyncio
async def test_the_probe_is_a_small_harmless_prompt():
    server = FakeChat()
    await _chat(server, ChatOptions(levels=[1], per_level=2, prompt_tokens=[500]))
    sizes = sorted(len(b["messages"][0]["content"]) for b in server.bodies)
    assert sizes[0] < 40  # "Reply with the single word: pong"
    assert 2_000 <= sizes[-1] <= 2_300  # one padded prompt of ~500 tokens
    assert all(b.get("max_tokens", 0) <= 128 for b in server.bodies)


def test_the_plan_states_the_load_before_anything_is_sent():
    plan = chat_plan(ChatOptions(levels=[1, 2, 4, 8], per_level=6, max_requests=60))
    assert plan["levels"] == [
        {"concurrency": 1, "requests": 6},
        {"concurrency": 2, "requests": 6},
        {"concurrency": 4, "requests": 8},
        {"concurrency": 8, "requests": 16},
    ]
    assert plan["at_most_http_requests"] == 3 + 1 + 36
    # A level that does not fit in the budget is dropped, not shortened.
    assert plan_levels([1, 2, 4, 8], 6, 20) == [(1, 6), (2, 6), (4, 8)]


# ── finding the limit on purpose ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_limit_stops_at_the_first_refusal_and_times_recovery():
    clock = Clock()
    server = FakeChat(limit=25, window=5.0, retry_after=5, clock=clock)
    report = await _chat(
        server,
        ChatOptions(quick=True, stream=False, find_limit=True, max_requests=200, limit_concurrency=2),
        sleep=clock.sleep,
        clock=clock,
    )
    probe, rate = report["limit_probe"], report["rate_limit"]
    assert probe["found"] and probe["accepted_in_window"] == 25
    assert (rate["source"], rate["per_minute"]) == ("observed", 25)
    assert rate["retry_after_sent"] is True and rate["recovers_after_s"] == 5.5
    # 25 accepted, at most one refusal per worker, one recovery request. Not 200.
    assert server.requests <= 25 + 2 + 1


@pytest.mark.asyncio
async def test_find_limit_without_a_limit_ends_on_its_budget():
    server = FakeChat()
    report = await _chat(server, ChatOptions(quick=True, stream=False, find_limit=True, max_requests=30, limit_concurrency=3))
    assert server.requests == 30
    assert report["limit_probe"]["found"] is False
    assert report["rate_limit"]["source"] == "none" and "no rate limit met" in report["rate_limit"]["note"]


# ── MCP ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_counts_what_a_call_costs_and_runs_no_tool():
    server = FakeMcp()
    report = await _mcp(server, McpOptions(levels=[1, 2], per_level=4))

    assert report["recommendations"]["requests_per_call"] == {"new_session_each_call": 4, "reused_session": 1}
    assert report["baseline"]["own_session_requests"] == 4 and report["baseline"]["tools"] == 2
    assert "tools/call" not in server.calls and report["safety"]["tools_run"] == []
    assert server.calls[-1] == "DELETE" and not server.open  # no session left behind
    assert report["target"]["server"] == "fake-tools"
    assert report["safety"]["http_requests"] == server.requests
    assert "mcp-test-secret" not in json.dumps(report)


@pytest.mark.asyncio
async def test_mcp_arithmetic_for_a_60_a_minute_edge():
    """The 2026-11-12 numbers: 60 requests a minute, four per call."""
    server = FakeMcp()
    report = await _mcp(
        server,
        McpOptions(quick=True, assume_limit=60, call_seconds=11, calls_per_task=18, task_seconds=150),
    )
    advice = report["recommendations"]
    assert advice["tool_calls_per_minute"] == {
        "new_session_each_call": 12,  # 80% of 60, four requests each
        "reused_session": 48,
        "at_the_limit_new_session": 15,  # "15 calls in the same minute are enough for a 429"
    }
    assert advice["parallel_calls"]["new_session_each_call"] == 2
    assert advice["parallel_calls"]["reused_session"] == 8
    assert advice["parallel_tasks"]["new_session_each_call"] == 1
    assert advice["parallel_tasks"]["reused_session"] == 6
    assert advice["client"]["reuse_session"] is True


@pytest.mark.asyncio
async def test_mcp_edge_limit_is_found_by_the_sweep_and_has_no_retry_after():
    server = FakeMcp(limit=20)
    report = await _mcp(server, McpOptions(levels=[1, 2, 4], per_level=6))
    rate = report["rate_limit"]
    assert rate["source"] == "observed" and rate["per_minute"] == 20
    assert rate["retry_after_sent"] is False
    assert "sends no Retry-After" in report["recommendations"]["client"]["retry"]
    assert report["levels"][-1]["errors"].get("rate_limited")
    assert server.requests <= 20 + 2 + 1  # refusals, and the attempt to end the session


@pytest.mark.asyncio
async def test_mcp_tool_runs_only_when_named_and_listed():
    server = FakeMcp(tool_seconds=0.05)
    report = await _mcp(server, McpOptions(quick=True, tool="zone_check", tool_args={"domain": "example.test"}, tool_calls=2))
    assert server.tool_calls == [{"name": "zone_check", "arguments": {"domain": "example.test"}}] * 2
    assert report["baseline"]["tool_call_s"] >= 0.04 and report["safety"]["tools_run"] == ["zone_check"]

    other = FakeMcp()
    report = await _mcp(other, McpOptions(quick=True, tool="delete_everything"))
    assert other.tool_calls == [] and report["safety"]["tools_run"] == []
    assert any("delete_everything" in note for note in report["notes"])


@pytest.mark.asyncio
async def test_mcp_server_without_sessions_or_ping():
    server = FakeMcp(sessions=False, ping=False)
    report = await _mcp(server, McpOptions(levels=[1], per_level=3))
    assert report["recommendations"]["requests_per_call"]["new_session_each_call"] == 3
    assert report["baseline"]["probe_method"] == "tools/list"
    assert "DELETE" not in server.calls  # there is no session to end
    assert report["levels"][0]["ok"] == 3


# ── recommendations ───────────────────────────────────────────────────────


def _level(concurrency: int, seconds: float, n: int = 8, wall: float | None = None) -> LevelResult:
    samples = [Sample("ok", seconds, status=200, accepted_requests=1) for _ in range(n)]
    return LevelResult(concurrency, n, samples, wall_seconds=wall if wall is not None else n * seconds / concurrency)


def test_best_concurrency_is_the_lowest_level_near_the_peak():
    # 1 → 60/min, 2 → 120/min, 4 → 228/min, 8 → 240/min: 4 is within 10% of the peak.
    levels = [_level(1, 1.0), _level(2, 1.0), _level(4, 1.05), _level(8, 2.0)]
    pick = recommend.pick_concurrency(levels)
    assert (pick["best"], pick["max_clean"], pick["first_failing"]) == (4, 8, None)


def test_the_provider_limit_follows_the_numbers():
    rate = {"per_minute": 60.0, "retry_after_s": 12.0, "recovers_after_s": None, "signalled_as": "HTTP 429"}
    limit = recommend.provider_limit(concurrency=4, rate=rate, p95=10.0, client_timeout=60)
    assert limit == {
        "requests_per_minute": 48,
        "max_concurrent": 4,
        "on_rate_limit": "wait_retry",
        "max_wait_seconds": 45,  # the caller's 60 s, less the answer time and a margin
        "cooldown_seconds": 12,  # what the endpoint asked for
    }
    unknown = recommend.provider_limit(
        concurrency=4, rate={"per_minute": None, "retry_after_s": None, "recovers_after_s": None, "signalled_as": None},
        p95=2.0, client_timeout=None,
    )
    assert unknown["requests_per_minute"] == 0 and unknown["max_wait_seconds"] == 120  # no pace is invented
    ProviderLimit(**limit)  # what Settings → Rate limits accepts


@pytest.mark.asyncio
async def test_a_prompt_that_outlasts_the_callers_timeout_is_called_out():
    server = FakeChat(service=0.02)
    report = await _chat(
        server,
        ChatOptions(quick=True, prompt_tokens=[400], client_timeout=0.001, output_tokens=5_000),
    )
    row = report["prompt_sizes"][0]
    assert row["outcome"] == "ok" and row["fits_client_timeout"] is False
    assert any("per try is shorter" in line for line in report["recommendations"]["why"])


# ── the settings audit and --apply ────────────────────────────────────────


def _row(pid: str, *, requests: int = 0, limited: int = 0, limits: dict | None = None) -> dict:
    return {
        "id": pid, "name": pid, "kind": "open_webui", "enabled": True, "registered": True,
        "requests": requests, "configured": limits is not None,
        "limits": (ProviderLimit(**limits) if limits else ProviderLimit()).model_dump(),
        "state": {"rate_limited_last_hour": limited},
    }


def test_the_audit_flags_a_provider_in_use_that_fails_fast():
    view = {
        "inbound": {"enabled": False, "requests_per_minute": 60, "refused_last_hour": 0},
        "providers": [
            _row("openwebui", requests=412, limited=3),
            _row("paced", requests=9, limits={"requests_per_minute": 48, "max_concurrent": 4, "on_rate_limit": "wait_retry"}),
            _row("unused"),
        ],
    }
    findings = {f["subject"]: f for f in audit.audit_settings(view=view, env={})}
    assert findings["openwebui"]["level"] == "warn"
    assert "3 rate-limited in the last hour" in findings["openwebui"]["detail"]
    assert "--apply openwebui" in findings["openwebui"]["fix"]
    assert findings["paced"]["level"] == "ok"
    assert "unused" not in findings and findings["other providers"]["level"] == "info"
    assert findings["inbound limit"]["level"] == "ok"

    view["inbound"] = {"enabled": True, "requests_per_minute": 60, "refused_last_hour": 4}
    assert {f["subject"]: f for f in audit.audit_settings(view=view, env={})}["inbound limit"]["level"] == "warn"


def test_the_audit_reads_saved_settings_when_the_gateway_is_down():
    cfg = RateLimitSettings(providers={"byok-acme": ProviderLimit(max_concurrent=4, on_rate_limit="wait_retry")})
    findings = {
        f["subject"]: f
        for f in audit.audit_settings(view=None, cfg=cfg, source_ids={"openwebui": "Team chat", "byok-acme": "byok-acme"}, env={})
    }
    assert findings["Team chat (openwebui)"]["level"] == "warn"
    assert findings["byok-acme"]["level"] == "ok"
    assert findings["gateway"]["level"] == "info"


def test_apply_changes_one_provider_through_the_running_gateway():
    saved: dict = {}
    current = {
        "inbound": {"enabled": False, "requests_per_minute": 60},
        "providers": {"other": ProviderLimit(max_concurrent=1).model_dump()},
    }

    def gateway(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"settings": current})
        saved.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    limit = {"requests_per_minute": 48, "max_concurrent": 4, "on_rate_limit": "wait_retry", "max_wait_seconds": 45, "cooldown_seconds": 12}
    done = audit.apply_provider_limit(
        "openwebui", limit, gateway="http://127.0.0.1:11435", api_key="k", transport=httpx.MockTransport(gateway)
    )
    assert "running gateway" in done["where"] and done["before"] is None
    assert saved["settings"]["providers"]["openwebui"] == limit
    assert saved["settings"]["providers"]["other"]["max_concurrent"] == 1  # left as it was
    assert saved["settings"]["inbound"] == current["inbound"]


def test_apply_writes_the_settings_file_when_no_gateway_runs():
    def no_gateway(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    before = rate_limits.current().model_copy(deep=True)
    try:
        limit = ProviderLimit(max_concurrent=3, on_rate_limit="wait_retry").model_dump()
        done = audit.apply_provider_limit(
            "openwebui", limit, gateway="http://127.0.0.1:11435", transport=httpx.MockTransport(no_gateway)
        )
        assert "settings file" in done["where"]
        rate_limits.reload()
        assert rate_limits.provider_limit("openwebui").max_concurrent == 3
    finally:
        rate_limits.save(before)
        rate_limits.reload()


# ── the command ───────────────────────────────────────────────────────────


@pytest.fixture
def cli(monkeypatch):
    from ollabridge.cli.main import app

    server = FakeChat(capacity=2, service=0.02)
    monkeypatch.setattr(targets, "TRANSPORT", httpx.MockTransport(server))
    return CliRunner(), app, server


def test_plan_and_a_declined_find_limit_send_nothing(cli):
    runner, app, server = cli
    args = ["diagnose", "chat", "--base-url", BASE, "--model", "some-model"]
    planned = runner.invoke(app, [*args, "--plan", "--json"])
    assert planned.exit_code == 0, planned.output
    assert json.loads(planned.stdout)["plan"]["at_most_http_requests"] == 40
    # Not a terminal and no --yes: the limit test must not start on its own.
    declined = runner.invoke(app, [*args, "--find-limit"])
    assert declined.exit_code == 2
    assert server.requests == 0


def test_the_command_prints_a_report(cli):
    runner, app, server = cli
    result = runner.invoke(
        app, ["diagnose", "chat", "--base-url", BASE, "--model", "some-model", "-c", "1,2", "--requests-per-level", "4", "--json"]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["kind"] == "chat" and report["target"]["url"] == f"{BASE}/chat/completions"
    assert [lv["concurrency"] for lv in report["levels"]] == [1, 2]
    assert server.requests == report["safety"]["http_requests"]

    text = runner.invoke(app, ["diagnose", "chat", "--base-url", BASE, "--model", "some-model", "--quick"])
    assert text.exit_code == 0, text.output
    assert "Lower limits" in text.stdout and "Recommended" in text.stdout


def test_an_api_key_is_read_from_the_environment_never_from_the_command_line(cli, monkeypatch):
    runner, app, _server = cli
    missing = runner.invoke(
        app, ["diagnose", "chat", "--base-url", BASE, "--model", "m", "--api-key-env", "NO_SUCH_KEY_VARIABLE", "--quick"]
    )
    assert missing.exit_code == 2
