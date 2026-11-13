"""The diagnosis itself: the phases, in order, and the report they produce.

Chat endpoint:

1. **Baseline**: three one-word requests, one after the other. The first is
   on a cold connection; the rest give the fastest answer the endpoint can
   produce. A failure here ends the run before any load is applied.
2. **Speed** (streaming): one 128-token answer, for time to first token and
   tokens per second.
3. **Prompt sizes** (opt-in): one request per size, to see how the answer
   time grows with the input and whether the caller's timeout survives it.
4. **Concurrency sweep**: 1, 2, 4, 8… in flight, a few requests each; ends
   at the first refusal or sign of saturation (see ``engine.sweep``).
5. **Limit** (opt-in, ``find_limit``): send until the first rate-limit
   answer, stop, and time the recovery.

An MCP endpoint gets the same shape with protocol methods only: handshake,
``ping``, ``tools/list``, one call with a session of its own (to count what
that costs), an optional named tool, the sweep on ``ping``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ollabridge.diagnose import recommend
from ollabridge.diagnose.engine import (
    Budget,
    BudgetSpent,
    find_limit,
    measure_recovery,
    plan_levels,
    sweep,
)
from ollabridge.diagnose.models import (
    PROTOCOL_ERROR,
    RATE_LIMITED,
    TIMEOUT,
    LevelResult,
    LimitProbe,
    RateHeaders,
    Sample,
    percentile,
)
from ollabridge.diagnose.targets import ChatTarget, McpTarget, filler_prompt

Say = Callable[[str], Any]

BASELINE_REQUESTS = 3
SPEED_TOKENS = 128


@dataclass
class ChatOptions:
    levels: list[int] = field(default_factory=lambda: [1, 2, 4, 8])
    per_level: int = 6
    max_requests: int = 60
    max_seconds: float = 300.0
    quick: bool = False
    find_limit: bool = False
    stream: bool = True
    prompt_tokens: list[int] = field(default_factory=list)
    client_timeout: float | None = None
    output_tokens: int | None = None
    assume_limit: float | None = None
    limit_concurrency: int | None = None


@dataclass
class McpOptions:
    levels: list[int] = field(default_factory=lambda: [1, 2, 4])
    per_level: int = 6
    max_requests: int = 40
    max_seconds: float = 180.0
    quick: bool = False
    find_limit: bool = False
    tool: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_calls: int = 1
    call_seconds: float | None = None
    calls_per_task: int | None = None
    task_seconds: float | None = None
    assume_limit: float | None = None
    limit_concurrency: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _unusable(sample: Sample) -> str:
    """Why the run cannot go on after this first answer."""
    hint = ""
    if sample.status in (401, 403):
        hint = " Check the API key (--api-key-env)."
    elif sample.status == 404:
        hint = " Check the URL and the model name."
    elif sample.outcome == RATE_LIMITED:
        hint = " It was limiting before this run applied any load; wait and run again."
    return f"the endpoint is not usable right now: {sample.detail or sample.outcome}.{hint}"


def chat_plan(opts: ChatOptions) -> dict[str, Any]:
    """What a run would send, without sending it (``--plan``)."""
    fixed = BASELINE_REQUESTS + (1 if opts.stream else 0) + len(opts.prompt_tokens)
    levels = [] if opts.quick else plan_levels(opts.levels, opts.per_level, max(0, opts.max_requests - fixed))
    swept = sum(n for _, n in levels)
    return {
        "baseline_requests": BASELINE_REQUESTS,
        "speed_requests": 1 if opts.stream else 0,
        "prompt_size_requests": [{"tokens": n} for n in opts.prompt_tokens],
        "levels": [{"concurrency": c, "requests": n} for c, n in levels],
        "find_limit": (
            f"then up to {max(0, opts.max_requests - fixed - swept)} more requests, until the first rate-limit answer"
            if opts.find_limit
            else "no"
        ),
        "at_most_http_requests": opts.max_requests if opts.find_limit else fixed + swept,
        "at_most_seconds": opts.max_seconds,
        "largest_prompt_tokens": max(opts.prompt_tokens, default=0),
    }


def mcp_plan(opts: McpOptions) -> dict[str, Any]:
    fixed = 2 + BASELINE_REQUESTS + 1 + 4 + (opts.tool_calls if opts.tool else 0) + 1
    levels = [] if opts.quick else plan_levels(opts.levels, opts.per_level, max(0, opts.max_requests - fixed))
    swept = sum(n for _, n in levels)
    return {
        "handshake_requests": 2,
        "ping_requests": BASELINE_REQUESTS,
        "tools_list_requests": 1,
        "own_session_call_requests": 4,
        "tool_calls": {"tool": opts.tool, "calls": opts.tool_calls} if opts.tool else "none: no tool is run",
        "levels": [{"concurrency": c, "requests": n} for c, n in levels],
        "find_limit": (
            f"then up to {max(0, opts.max_requests - fixed - swept)} more pings, until the first rate-limit answer"
            if opts.find_limit
            else "no"
        ),
        "end_session_requests": 1,
        "at_most_http_requests": opts.max_requests if opts.find_limit else fixed + swept,
        "at_most_seconds": opts.max_seconds,
    }


def _last_headers(samples: list[Sample]) -> RateHeaders | None:
    return next((s.limits for s in reversed(samples) if s.limits is not None), None)


def _limits_section(
    *, baseline: dict[str, Any], pick: dict[str, Any], rate: dict[str, Any], samples: list[Sample]
) -> dict[str, Any]:
    oks = [s.seconds for s in samples if s.ok]
    return {
        "lower": {
            "fastest_answer_s": _r(min(oks) if oks else None),
            "connection_setup_s": baseline.get("connection_setup_s"),
            "first_token_s": baseline.get("first_token_s"),
        },
        "upper": {
            "peak_per_minute": pick["peak_per_minute"],
            "best_concurrency": pick["best"],
            "max_clean_concurrency": pick["max_clean"],
            "first_failing_concurrency": pick["first_failing"],
            "first_failure": pick["first_failure"],
            "rate_limit_per_minute": rate["per_minute"],
            "slowest_answer_s": _r(max(oks) if oks else None),
            "timeouts": sum(1 for s in samples if s.outcome == TIMEOUT),
        },
    }


async def _limit_phase(
    op,
    *,
    levels: list[LevelResult],
    budget: Budget,
    concurrency: int,
    say: Say,
    sleep: Callable[[float], Awaitable[Any]],
    clock: Callable[[], float],
) -> LimitProbe:
    """Drive to the limit (unless the sweep already met it), then time recovery."""
    hit_level = next((lv for lv in levels if lv.accepted_before_limit is not None), None)
    if hit_level is not None:
        hit = next(s for s in hit_level.samples if s.outcome == RATE_LIMITED)
        probe = LimitProbe(
            found=True,
            accepted_in_window=hit_level.accepted_before_limit or 0,
            status=hit.status,
            retry_after=hit.retry_after,
            detail=hit.detail,
            stopped="met during the concurrency sweep",
        )
    else:
        say(f"finding the rate limit at concurrency {concurrency} (stops at the first refusal)")
        probe = await find_limit(op, concurrency=concurrency, budget=budget, clock=clock)
    if probe.found:
        say("rate limit met; waiting for the endpoint to accept a request again")
        await measure_recovery(op, probe, budget, sleep=sleep, clock=clock)
    return probe


async def diagnose_chat(
    target: ChatTarget,
    opts: ChatOptions,
    *,
    say: Say = lambda _msg: None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started_at, t0 = _now(), clock()
    budget = Budget(opts.max_requests, opts.max_seconds, clock=clock)
    samples: list[Sample] = []
    levels: list[LevelResult] = []
    baseline: dict[str, Any] = {}
    prompt_sizes: list[dict[str, Any]] = []
    probe: LimitProbe | None = None
    stopped = ""
    sweep_reason = "not run (--quick)" if opts.quick else ""
    notes: list[str] = []

    async def one(**kw: Any) -> Sample:
        budget.take(1)
        sample = await target.call(**kw)
        budget.note_accepted(sample.accepted_requests)
        samples.append(sample)
        return sample

    try:
        say("baseline: three single requests")
        base: list[Sample] = []
        for index in range(BASELINE_REQUESTS):
            sample = await one()
            base.append(sample)
            if not sample.ok and (index == 0 or sample.outcome == RATE_LIMITED):
                stopped = _unusable(sample)
                raise BudgetSpent(stopped)
        oks = [s.seconds for s in base if s.ok]
        warm = percentile([s.seconds for s in base[1:] if s.ok], 0.5)
        baseline = {
            "requests": len(base),
            "fastest_s": _r(min(oks)),
            "p50_s": _r(percentile(oks, 0.5)),
            "p95_s": _r(percentile(oks, 0.95)),
            "cold_s": _r(base[0].seconds),
            "warm_s": _r(warm),
            "connection_setup_s": _r(max(0.0, base[0].seconds - warm)) if warm is not None else None,
            "tokens_in": base[0].tokens_in,
        }

        tokens_per_s: float | None = None
        if opts.stream:
            say("speed: one streamed answer")
            speed = await one(max_tokens=SPEED_TOKENS, stream=True)
            if speed.ok:
                baseline["first_token_s"] = _r(speed.ttft)
                generating = speed.seconds - (speed.ttft or 0.0)
                if speed.tokens_out and speed.tokens_out > 1 and generating > 0.05:
                    tokens_per_s = speed.tokens_out / generating
                    baseline["tokens_per_s"] = round(tokens_per_s, 1)
                baseline["speed_answer_s"] = _r(speed.seconds)
                baseline["speed_tokens_out"] = speed.tokens_out
                if speed.ttft is not None and speed.seconds - speed.ttft < 0.05 and (speed.tokens_out or 0) > 8:
                    notes.append(
                        "the answer arrived in one piece although streaming was asked for: the endpoint "
                        "buffers it, so time to first token equals the whole answer time"
                    )
            elif speed.outcome == RATE_LIMITED:
                stopped = _unusable(speed)
                raise BudgetSpent(stopped)
            else:
                notes.append(f"streaming is not usable on this endpoint ({speed.detail}); measured without it")

        for size in opts.prompt_tokens:
            say(f"prompt size: about {size} tokens")
            sample = await one(prompt=filler_prompt(size), stream=opts.stream)
            row: dict[str, Any] = {
                "target_tokens": size,
                "tokens_in": sample.tokens_in,
                "outcome": sample.outcome,
                "seconds": _r(sample.seconds),
                "first_token_s": _r(sample.ttft),
                "detail": sample.detail,
            }
            if sample.ok and tokens_per_s and opts.output_tokens:
                row["projected_s"] = _r((sample.ttft or sample.seconds) + opts.output_tokens / tokens_per_s, 1)
            if opts.client_timeout:
                needed = row.get("projected_s") or sample.seconds
                row["fits_client_timeout"] = sample.ok and needed <= opts.client_timeout
            prompt_sizes.append(row)
            if sample.outcome == RATE_LIMITED:
                stopped = "the endpoint answered with a rate limit during the prompt-size requests"
                raise BudgetSpent(stopped)

        if not opts.quick:
            plan = plan_levels(opts.levels, opts.per_level, budget.remaining)
            say("concurrency sweep: " + ", ".join(f"{c}×{n}" for c, n in plan))
            levels, sweep_reason = await sweep(
                target.op(),
                plan,
                budget,
                on_level=lambda lv: say(
                    f"  concurrency {lv.concurrency}: {len(lv.ok_samples)}/{len(lv.samples)} ok, "
                    f"{lv.throughput * 60:.0f}/min"
                ),
                clock=clock,
            )
            for level in levels:
                samples.extend(level.samples)

        if opts.find_limit:
            pick = recommend.pick_concurrency(levels)
            probe = await _limit_phase(
                target.op(max_tokens=1),
                levels=levels,
                budget=budget,
                concurrency=opts.limit_concurrency or pick["max_clean"] or 2,
                say=say,
                sleep=sleep,
                clock=clock,
            )
    except BudgetSpent as exc:
        stopped = stopped or str(exc)

    rate = recommend.rate_limit_finding(
        headers=_last_headers(samples),
        probe=probe,
        levels=levels,
        assume=opts.assume_limit,
        accepted=budget.accepted_total,
        seconds=clock() - t0,
    )
    pick = recommend.pick_concurrency(levels)
    advice = recommend.chat_advice(
        levels=levels,
        rate=rate,
        baseline=baseline,
        prompt_sizes=prompt_sizes,
        client_timeout=opts.client_timeout,
        output_tokens=opts.output_tokens,
    )
    return {
        "kind": "chat",
        "target": target.describe(),
        "started_at": started_at,
        "duration_s": _r(clock() - t0, 1),
        "safety": {
            "http_requests": budget.used,
            "max_requests": opts.max_requests,
            "max_seconds": opts.max_seconds,
            "stopped": stopped or budget.spent or "",
            "mode": "find-limit" if opts.find_limit else "quick" if opts.quick else "sweep",
        },
        "baseline": baseline,
        "prompt_sizes": prompt_sizes,
        "levels": [lv.to_dict() for lv in levels],
        "sweep_ended": sweep_reason,
        "limit_probe": probe.to_dict() if probe else None,
        "rate_limit": rate,
        "limits": _limits_section(baseline=baseline, pick=pick, rate=rate, samples=samples),
        "recommendations": advice,
        "notes": notes,
    }


async def diagnose_mcp(
    target: McpTarget,
    opts: McpOptions,
    *,
    say: Say = lambda _msg: None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started_at, t0 = _now(), clock()
    budget = Budget(opts.max_requests, opts.max_seconds, clock=clock)
    samples: list[Sample] = []
    levels: list[LevelResult] = []
    baseline: dict[str, Any] = {}
    probe: LimitProbe | None = None
    stopped = ""
    sweep_reason = "not run (--quick)" if opts.quick else ""
    notes: list[str] = []
    requests_per_call = 4
    probe_method = "ping"
    tool_seconds: float | None = None

    def keep(sample: Sample) -> Sample:
        budget.note_accepted(sample.accepted_requests)
        samples.append(sample)
        return sample

    try:
        say("handshake: initialize + initialized")
        budget.take(2)
        opened = keep(await target.open_session())
        if not opened.ok:
            stopped = _unusable(opened)
            raise BudgetSpent(stopped)
        baseline["handshake_s"] = _r(opened.seconds)
        if not target.stateful:
            notes.append("the server issues no session id: a call with its own session costs 3 requests, not 4")

        say("baseline: three pings on the session")
        pings: list[Sample] = []
        for index in range(BASELINE_REQUESTS):
            budget.take(1)
            sample = keep(await target.rpc(probe_method, session=target.session))
            if index == 0 and sample.outcome == PROTOCOL_ERROR:
                # A server without ``ping``: the tool list is the next cheapest read.
                probe_method = "tools/list"
                notes.append("the server does not answer ping; tools/list is used as the probe instead")
                continue
            if sample.outcome == RATE_LIMITED:
                stopped = _unusable(sample)
                raise BudgetSpent(stopped)
            pings.append(sample)
        ok_pings = [s.seconds for s in pings if s.ok]
        baseline["probe_method"] = probe_method
        baseline["fastest_s"] = _r(min(ok_pings) if ok_pings else None)
        baseline["p50_s"] = _r(percentile(ok_pings, 0.5))

        budget.take(1)
        listed = keep(await target.rpc("tools/list", session=target.session))
        tools = (listed.data or {}).get("tools") if listed.ok and isinstance(listed.data, dict) else None
        baseline["tools"] = len(tools) if isinstance(tools, list) else None
        baseline["tools_list_s"] = _r(listed.seconds) if listed.ok else None
        if opts.tool and isinstance(tools, list) and opts.tool not in {t.get("name") for t in tools if isinstance(t, dict)}:
            notes.append(f"the server does not list a tool named {opts.tool!r}; it was not called")
            opts = McpOptions(**{**opts.__dict__, "tool": None})

        say("one call with a session of its own")
        budget.take(4 if target.stateful else 3)
        own = keep(await target.cycle(probe_method))
        if own.ok:
            requests_per_call = own.http_requests
            baseline["own_session_call_s"] = _r(own.seconds)
            baseline["own_session_requests"] = own.http_requests
        elif own.outcome == RATE_LIMITED:
            stopped = "the endpoint answered with a rate limit during the baseline"
            raise BudgetSpent(stopped)

        if opts.tool:
            say(f"tool call: {opts.tool} × {opts.tool_calls}")
            durations: list[float] = []
            for _ in range(max(1, opts.tool_calls)):
                budget.take(1)
                called = keep(
                    await target.rpc(
                        "tools/call", {"name": opts.tool, "arguments": opts.tool_args}, session=target.session
                    )
                )
                if called.outcome == RATE_LIMITED:
                    stopped = "the endpoint answered with a rate limit during the tool call"
                    raise BudgetSpent(stopped)
                if called.ok:
                    durations.append(called.seconds)
                    if isinstance(called.data, dict) and called.data.get("isError"):
                        notes.append(f"{opts.tool} answered with isError: its duration may not be typical")
                else:
                    notes.append(f"{opts.tool} failed: {called.detail}")
            tool_seconds = percentile(durations, 0.5)
            baseline["tool"] = opts.tool
            baseline["tool_call_s"] = _r(tool_seconds)

        if not opts.quick:
            plan = plan_levels(opts.levels, opts.per_level, max(0, budget.remaining - 1))
            say("concurrency sweep: " + ", ".join(f"{c}×{n}" for c, n in plan))
            levels, sweep_reason = await sweep(
                target.op(probe_method),
                plan,
                budget,
                on_level=lambda lv: say(
                    f"  concurrency {lv.concurrency}: {len(lv.ok_samples)}/{len(lv.samples)} ok, "
                    f"{lv.throughput * 60:.0f}/min"
                ),
                clock=clock,
            )
            for level in levels:
                samples.extend(level.samples)

        if opts.find_limit:
            pick = recommend.pick_concurrency(levels)
            probe = await _limit_phase(
                target.op(probe_method),
                levels=levels,
                budget=budget,
                concurrency=opts.limit_concurrency or pick["max_clean"] or 2,
                say=say,
                sleep=sleep,
                clock=clock,
            )
    except BudgetSpent as exc:
        stopped = stopped or str(exc)
    finally:
        # Leave no session behind, whatever happened above.
        if target.session:
            ended = await target.close_session()
            if ended is not None:
                budget.used += 1
                samples.append(ended)

    rate = recommend.rate_limit_finding(
        headers=_last_headers(samples),
        probe=probe,
        levels=levels,
        assume=opts.assume_limit,
        accepted=budget.accepted_total,
        seconds=clock() - t0,
    )
    pick = recommend.pick_concurrency(levels)
    advice = recommend.mcp_advice(
        levels=levels,
        rate=rate,
        requests_per_call=requests_per_call,
        call_seconds=opts.call_seconds or tool_seconds,
        calls_per_task=opts.calls_per_task,
        task_seconds=opts.task_seconds,
    )
    return {
        "kind": "mcp",
        "target": target.describe(),
        "started_at": started_at,
        "duration_s": _r(clock() - t0, 1),
        "safety": {
            "http_requests": budget.used,
            "max_requests": opts.max_requests,
            "max_seconds": opts.max_seconds,
            "stopped": stopped or budget.spent or "",
            "mode": "find-limit" if opts.find_limit else "quick" if opts.quick else "sweep",
            "tools_run": [opts.tool] if opts.tool else [],
        },
        "baseline": baseline,
        "levels": [lv.to_dict() for lv in levels],
        "sweep_ended": sweep_reason,
        "limit_probe": probe.to_dict() if probe else None,
        "rate_limit": rate,
        "limits": _limits_section(baseline=baseline, pick=pick, rate=rate, samples=samples),
        "recommendations": advice,
        "notes": notes,
    }
