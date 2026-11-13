"""From measurements to settings: pure functions, no I/O.

The rules, stated once:

* **Best concurrency** is the lowest level that reaches 90 % of the peak
  throughput among the levels where every request succeeded. Above it, more
  parallel calls buy latency, not answers.
* **Requests per minute** is 80 % of the endpoint's limit when one is known
  (published, observed or given): the headroom absorbs other clients on the
  same key and clock skew between the two windows. With no known limit no
  pace is invented; the concurrency cap alone bounds the load.
* **A rate limit is retried, not failed**: wait-and-retry, with the wait the
  endpoint asked for (``Retry-After``) as the first step when it sends one.
* **The caller must outlast the queue**: a client whose per-try timeout is
  shorter than (max wait in OllaBridge + the answer time) gives up while its
  request is still queued, and its retry adds load to an endpoint that is
  already limiting.
"""

from __future__ import annotations

import math
from typing import Any

from ollabridge.core.rate_limits import ProviderLimit
from ollabridge.diagnose.models import (
    RATE_LIMITED,
    LevelResult,
    LimitProbe,
    RateHeaders,
    Sample,
)

#: Share of a known limit to plan for.
HEADROOM = 0.8
#: A level counts as "at the peak" from this share of the best throughput.
NEAR_PEAK = 0.9


def pick_concurrency(levels: list[LevelResult]) -> dict[str, Any]:
    """Best and highest clean concurrency, and the first level that failed."""
    clean = [lv for lv in levels if lv.clean]
    failing = next((lv for lv in levels if not lv.clean), None)
    out: dict[str, Any] = {
        "best": None,
        "max_clean": None,
        "peak_per_minute": None,
        "p50_s": None,
        "p95_s": None,
        "first_failing": failing.concurrency if failing else None,
        "first_failure": (failing.to_dict()["first_error"] or failing.stopped) if failing else "",
    }
    if not clean:
        return out
    peak = max(lv.throughput for lv in clean)
    best = min((lv for lv in clean if lv.throughput >= NEAR_PEAK * peak), key=lambda lv: lv.concurrency)
    out.update(
        best=best.concurrency,
        max_clean=max(lv.concurrency for lv in clean),
        peak_per_minute=round(best.throughput * 60, 1),
        p50_s=best.latency(0.5),
        p95_s=best.latency(0.95),
    )
    return out


def rate_limit_finding(
    *,
    headers: RateHeaders | None,
    probe: LimitProbe | None,
    levels: list[LevelResult],
    assume: float | None,
    accepted: int,
    seconds: float,
) -> dict[str, Any]:
    """What is known about the endpoint's request limit, and how it is known."""
    out: dict[str, Any] = {
        "per_minute": None,
        "source": "none",
        "exact": False,
        "signalled_as": None,
        "retry_after_sent": None,
        "retry_after_s": None,
        "recovers_after_s": None,
        "published": headers.to_dict() if headers else None,
        "note": "",
    }
    hit_level = next((lv for lv in levels if lv.accepted_before_limit is not None), None)
    hit: Sample | None = None
    if hit_level is not None:
        hit = next((s for s in hit_level.samples if s.outcome == RATE_LIMITED), None)
    status = probe.status if probe and probe.found else (hit.status if hit else None)
    waited = probe.retry_after if probe and probe.found else (hit.retry_after if hit else None)
    if status is not None:
        out["signalled_as"] = f"HTTP {status}" + ("" if status == 429 else " with a rate-limit message in its body")
        out["retry_after_sent"] = waited is not None
        out["retry_after_s"] = waited
    if probe and probe.recovered_after is not None:
        out["recovers_after_s"] = round(probe.recovered_after, 1)

    if assume:
        out.update(per_minute=float(assume), source="assumed", exact=True, note="the limit given with --assume-limit")
    elif headers is not None and headers.limit:
        out.update(per_minute=headers.per_minute, source="header", exact=headers.window_seconds is not None)
        out["note"] = f"published in the {headers.family} response headers" + (
            "" if headers.window_seconds else "; they do not state the window, a minute is assumed"
        )
    elif probe is not None and probe.found:
        out.update(per_minute=float(probe.accepted_in_window), source="observed")
        out["note"] = (
            f"refused a request after accepting {probe.accepted_in_window} in the last 60 s; "
            "the real limit is that or a little higher, and lower for you if other clients share the key"
        )
    elif hit_level is not None:
        out.update(per_minute=float(hit_level.accepted_before_limit or 0), source="observed")
        out["note"] = (
            f"refused a request at concurrency {hit_level.concurrency} after accepting "
            f"{hit_level.accepted_before_limit} in the last 60 s: a limit of about that many a minute, "
            f"or a cap on parallel requests below {hit_level.concurrency}. "
            "--find-limit at a lower concurrency tells the two apart"
        )
    else:
        out["note"] = f"no rate limit met: {accepted} request(s) accepted in {seconds:.0f} s" + (
            f" ({probe.stopped})" if probe and probe.stopped else ""
        )
    return out


def provider_limit(
    *,
    concurrency: int | None,
    rate: dict[str, Any],
    p95: float | None,
    client_timeout: float | None,
) -> dict[str, Any]:
    """The Settings → Rate limits entry for the provider behind this endpoint."""
    rpm = 0
    if rate.get("per_minute"):
        rpm = max(1, min(10_000, math.floor(rate["per_minute"] * HEADROOM)))
    if client_timeout:
        # Answer the caller (with a 429 and a Retry-After) before it gives up.
        max_wait = int(max(5, min(3_600, client_timeout - (p95 or 0.0) - 5)))
    else:
        max_wait = 120
    if rate.get("retry_after_s"):
        cooldown = math.ceil(rate["retry_after_s"])
    elif rate.get("recovers_after_s"):
        cooldown = math.ceil(rate["recovers_after_s"])
    elif rate.get("per_minute") or rate.get("signalled_as"):
        cooldown = 15
    else:
        cooldown = 0
    return ProviderLimit(
        requests_per_minute=rpm,
        max_concurrent=max(0, min(1_000, concurrency or 0)),
        on_rate_limit="wait_retry",
        max_wait_seconds=max_wait,
        cooldown_seconds=max(0, min(3_600, cooldown)),
    ).model_dump()


def _ceil_to(value: float, step: int) -> int:
    return int(math.ceil(value / step) * step)


def chat_advice(
    *,
    levels: list[LevelResult],
    rate: dict[str, Any],
    baseline: dict[str, Any],
    prompt_sizes: list[dict[str, Any]],
    client_timeout: float | None,
    output_tokens: int | None,
) -> dict[str, Any]:
    pick = pick_concurrency(levels)
    p95 = pick["p95_s"] or baseline.get("p95_s")
    limit = provider_limit(concurrency=pick["best"], rate=rate, p95=p95, client_timeout=client_timeout)

    # The longest answer this run saw or can project decides the client timeout.
    slowest = max(
        [p95 or 0.0]
        + [float(p["seconds"]) for p in prompt_sizes if p.get("outcome") == "ok"]
        + [float(p["projected_s"]) for p in prompt_sizes if p.get("projected_s")]
    )
    timeout = max(30, _ceil_to(slowest * 1.5, 5)) if slowest else None

    why: list[str] = []
    if pick["best"] is not None:
        why.append(
            f"concurrency {pick['best']} gives {pick['peak_per_minute']:g} answers a minute "
            f"(p95 {pick['p95_s']:.1f} s); it is the lowest level within 10% of the peak"
        )
        if pick["first_failing"] is not None:
            why.append(f"concurrency {pick['first_failing']} failed: {pick['first_failure']}")
    else:
        why.append("no concurrency sweep ran or no level was clean: concurrency is not measured")
    if limit["requests_per_minute"]:
        why.append(
            f"{limit['requests_per_minute']} requests a minute is {HEADROOM:.0%} of the "
            f"{rate['per_minute']:g}/minute limit ({rate['source']})"
        )
    else:
        why.append("no request limit is known, so no pace is set: the concurrency cap bounds the load")
    if client_timeout and timeout and timeout > client_timeout:
        why.append(
            f"the caller's {client_timeout:g} s per try is shorter than the {slowest:.0f} s the slowest "
            f"answer takes: raise it to {timeout} s, or stream the answer so tokens arrive before the limit"
        )
    return {
        "concurrency": pick["best"],
        "max_clean_concurrency": pick["max_clean"],
        "capacity_per_minute": pick["peak_per_minute"],
        "requests_per_minute": limit["requests_per_minute"] or None,
        "provider_limit": limit,
        "client": {
            "max_parallel_calls": pick["best"],
            "timeout_per_try_s": timeout,
            "outlast_the_queue_s": (limit["max_wait_seconds"] + math.ceil(p95 or 0)) if p95 else None,
            "retry": "429 and 503 only, after the Retry-After the answer carries; back off with jitter otherwise",
        },
        "why": why,
        "output_tokens_assumed": output_tokens,
    }


def mcp_advice(
    *,
    levels: list[LevelResult],
    rate: dict[str, Any],
    requests_per_call: int,
    call_seconds: float | None,
    calls_per_task: int | None,
    task_seconds: float | None,
) -> dict[str, Any]:
    pick = pick_concurrency(levels)
    out: dict[str, Any] = {
        "requests_per_call": {"new_session_each_call": requests_per_call, "reused_session": 1},
        "max_clean_concurrency": pick["max_clean"],
        "tool_calls_per_minute": None,
        "parallel_calls": None,
        "parallel_tasks": None,
        "client": {
            "reuse_session": requests_per_call > 1,
            "retry": (
                "retry a 429 after its Retry-After"
                if rate.get("retry_after_sent")
                else "retry a 429 with backoff and jitter (2 s, 4 s, 8 s…): this edge sends no Retry-After"
                if rate.get("retry_after_sent") is False
                else "retry a 429 after its Retry-After, or with backoff and jitter when it sends none"
            ),
        },
        "why": [],
    }
    why: list[str] = out["why"]
    why.append(
        f"a client that opens a session for every call spends {requests_per_call} HTTP requests on it "
        "(initialize, initialized, the call" + (", end session)" if requests_per_call >= 4 else ")")
        + "; on a kept session a call is 1"
    )
    per_minute = rate.get("per_minute")
    if not per_minute:
        why.append("the edge's request limit is not known: pass --assume-limit N or run --find-limit to size the calls")
        return out

    safe = per_minute * HEADROOM
    calls = {
        "new_session_each_call": math.floor(safe / requests_per_call),
        "reused_session": math.floor(safe),
        "at_the_limit_new_session": math.floor(per_minute / requests_per_call),
    }
    out["tool_calls_per_minute"] = calls
    why.append(
        f"{per_minute:g} requests a minute ({rate['source']}) is {calls['at_the_limit_new_session']} tool calls a "
        f"minute with a session per call; planning for {HEADROOM:.0%} leaves {calls['new_session_each_call']}, "
        f"or {calls['reused_session']} on a kept session"
    )
    if call_seconds:
        cap = pick["max_clean"]
        by_rate = {
            key: max(1, math.floor(calls[key] * call_seconds / 60.0))
            for key in ("new_session_each_call", "reused_session")
        }
        # Never above what the sweep saw the server handle cleanly.
        parallel = {key: min(value, cap) for key, value in by_rate.items()} if cap else dict(by_rate)
        out["parallel_calls"] = {**parallel, "call_seconds": call_seconds}
        line = (
            f"a call takes about {call_seconds:g} s, so {parallel['new_session_each_call']} can run in parallel "
            f"without passing the limit ({parallel['reused_session']} on a kept session)"
        )
        if parallel != by_rate:
            line += (
                f"; capped at {cap}, the highest concurrency the sweep measured clean "
                f"(the limit alone would allow {by_rate['reused_session']}: -c with higher levels measures more)"
            )
        why.append(line)
    if calls_per_task and task_seconds:
        per_task = calls_per_task * 60.0 / task_seconds
        tasks = {
            key: math.floor(calls[key] / per_task) for key in ("new_session_each_call", "reused_session")
        }
        out["parallel_tasks"] = {**tasks, "calls_per_task": calls_per_task, "task_seconds": task_seconds}
        why.append(
            f"a task making {calls_per_task} calls in {task_seconds:g} s uses {per_task:.1f} calls a minute: "
            f"{tasks['new_session_each_call']} task(s) in parallel, {tasks['reused_session']} on kept sessions"
        )
    return out
