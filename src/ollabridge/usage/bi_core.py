"""Dashboard aggregation over daily rollup rows.

VENDORED FILE — identical in both OllaBridge repositories; see ``contract.py``.

Both products expose the same ``/v1/bi/*`` responses. Each one only has to
produce *rollup rows* from its own store (SQLite locally, the ledger in the
cloud); every shape the dashboard consumes is derived here, in pure Python.

A rollup row is a mapping with these keys::

    day, provider, billing_provider, model, application_id, agent_id,
    device_id, billing_mode, measurement, status,
    events, unknown_events,
    input_tokens, cache_read_tokens, cache_write_tokens, output_tokens,
    reasoning_tokens,
    cost_micro        Σ best-known cost per event (catalog estimate, else the
                      provider-stated charge)
    reported_micro    Σ provider-stated charges only
    unpriced_tokens   Σ tokens of events that have no cost at all

Money is integer micro-USD. Subscription and local usage is never added to
API spend: it is reported separately as an *equivalent* figure.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .contract import MEASUREMENT_BADGE, TOKEN_DIMENSIONS

Row = Mapping[str, Any]

GROUPABLE = (
    "provider", "billing_provider", "model", "application_id", "agent_id",
    "device_id", "billing_mode", "measurement",
)
UNATTRIBUTED = "unattributed"
#: Providers whose APIs offer prompt caching (used by the cache insight).
_CACHE_CAPABLE = {"anthropic", "openai", "gemini", "openrouter"}


# ── primitives ──────────────────────────────────────────────────────────

def row_tokens(row: Row) -> int:
    return sum(int(row.get(d) or 0) for d in TOKEN_DIMENSIONS)


def _is_api(row: Row) -> bool:
    return (row.get("billing_mode") or "api") == "api"


def _cost(row: Row) -> int:
    return int(row.get("cost_micro") or 0)


def _delta_pct(current: float, previous: float) -> Optional[float]:
    if not previous:
        return None
    return round((current - previous) / previous * 100.0, 1)


def _metric(metric: str) -> Callable[[Row], int]:
    if metric == "tokens":
        return row_tokens
    if metric == "cost":
        # Spend charts show API spend only; see module docstring.
        return lambda r: _cost(r) if _is_api(r) else 0
    if metric == "events":
        return lambda r: int(r.get("events") or 0)
    raise ValueError(f"unknown metric: {metric}")


def _group_key(row: Row, by: str) -> str:
    if by not in GROUPABLE:
        raise ValueError(f"cannot group by: {by}")
    value = row.get(by)
    return str(value) if value not in (None, "") else UNATTRIBUTED


def day_range(start: dt.date, end: dt.date) -> List[str]:
    """Inclusive list of ISO days."""
    days = (end - start).days
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(max(days, 0) + 1)]


def previous_period(start: dt.date, end: dt.date) -> Tuple[dt.date, dt.date]:
    """The equal-length period immediately before ``start``."""
    length = (end - start).days + 1
    return start - dt.timedelta(days=length), start - dt.timedelta(days=1)


def measurement_mix(rows: Iterable[Row]) -> Dict[str, float]:
    """Share of tokens per badge (verified / observed / estimated)."""
    totals: Dict[str, int] = defaultdict(int)
    for row in rows:
        badge = MEASUREMENT_BADGE.get(str(row.get("measurement")), "unavailable")
        totals[badge] += row_tokens(row)
    grand = sum(totals.values())
    if not grand:
        return {}
    return {badge: round(count / grand, 4) for badge, count in sorted(totals.items()) if count}


def _active_agents(rows: Iterable[Row]) -> int:
    return len({r.get("agent_id") for r in rows if r.get("agent_id")})


# ── overview ────────────────────────────────────────────────────────────

def overview(
    rows: Sequence[Row],
    previous_rows: Sequence[Row],
    *,
    start: dt.date,
    end: dt.date,
    budget_limit_micro: Optional[int] = None,
    month_rows: Optional[Sequence[Row]] = None,
    today: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """The KPI cards. ``month_rows`` (month-to-date) feeds budget + forecast."""
    tokens, prev_tokens = sum(map(row_tokens, rows)), sum(map(row_tokens, previous_rows))

    api, prev_api = [r for r in rows if _is_api(r)], [r for r in previous_rows if _is_api(r)]
    estimated, prev_estimated = sum(map(_cost, api)), sum(map(_cost, prev_api))
    billed = sum(int(r.get("reported_micro") or 0) for r in api)
    prev_billed = sum(int(r.get("reported_micro") or 0) for r in prev_api)

    agents, prev_agents = _active_agents(rows), _active_agents(previous_rows)

    result: Dict[str, Any] = {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "total_tokens": {
            "value": tokens,
            "previous": prev_tokens,
            "delta_pct": _delta_pct(tokens, prev_tokens),
            "measurement_mix": measurement_mix(rows),
        },
        "estimated_cost_micro": {
            "value": estimated,
            "previous": prev_estimated,
            "delta_pct": _delta_pct(estimated, prev_estimated),
            # Tokens on API billing that have no price yet — the estimate is a
            # floor until the catalog covers them.
            "unpriced_tokens": sum(int(r.get("unpriced_tokens") or 0) for r in api),
        },
        "billed_cost_micro": {
            "value": billed,
            "previous": prev_billed,
            "delta_pct": _delta_pct(billed, prev_billed),
        },
        "subscription_equivalent_micro": {
            "value": sum(_cost(r) for r in rows if r.get("billing_mode") == "subscription"),
        },
        "active_agents": {
            "value": agents,
            "previous": prev_agents,
            "delta": agents - prev_agents,
            "delta_pct": _delta_pct(agents, prev_agents),
        },
        "requests": {
            "value": sum(int(r.get("events") or 0) for r in rows),
            "failed": sum(int(r.get("events") or 0) for r in rows if r.get("status") == "failed"),
            "unknown_usage": sum(int(r.get("unknown_events") or 0) for r in rows),
        },
        "budget": None,
        "forecast": None,
    }

    if month_rows is not None:
        today = today or dt.datetime.now(dt.timezone.utc).date()
        result["forecast"] = forecast(month_rows, today)
        if budget_limit_micro:
            spent = result["forecast"]["month_to_date_micro"]
            remaining = budget_limit_micro - spent
            result["budget"] = {
                "limit_micro": budget_limit_micro,
                "spent_micro": spent,
                "remaining_micro": remaining,
                "remaining_pct": round(remaining / budget_limit_micro * 100.0, 1),
                "projected_overrun": result["forecast"]["projected_month_end_micro"]
                > budget_limit_micro,
            }
    return result


def forecast(month_rows: Sequence[Row], today: dt.date) -> Dict[str, Any]:
    """Month-end API-spend projection from the month-to-date burn rate.

    A projection, not a bill: linear extrapolation of the average daily spend
    over the days elapsed so far.
    """
    spent = sum(_cost(r) for r in month_rows if _is_api(r))
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    elapsed = max(today.day, 1)
    daily = spent / elapsed
    return {
        "month": today.strftime("%Y-%m"),
        "month_to_date_micro": spent,
        "daily_average_micro": int(round(daily)),
        "projected_month_end_micro": int(round(daily * days_in_month)),
        "days_elapsed": elapsed,
        "days_in_month": days_in_month,
        "method": "linear_burn_rate",
    }


# ── charts ──────────────────────────────────────────────────────────────

def timeseries(
    rows: Sequence[Row],
    *,
    start: dt.date,
    end: dt.date,
    metric: str = "tokens",
    group_by: str = "provider",
    top: int = 6,
) -> Dict[str, Any]:
    """Per-day series, the largest ``top`` groups plus an ``others`` bucket."""
    value_of = _metric(metric)
    days = day_range(start, end)
    index = {day: i for i, day in enumerate(days)}

    per_group: Dict[str, List[int]] = defaultdict(lambda: [0] * len(days))
    for row in rows:
        position = index.get(str(row.get("day")))
        if position is None:
            continue
        per_group[_group_key(row, group_by)][position] += value_of(row)

    # A group with nothing to plot (e.g. only failed attempts) is not a series.
    ranked = sorted(
        ((key, values) for key, values in per_group.items() if any(values)),
        key=lambda kv: (-sum(kv[1]), kv[0]),
    )
    series = [{"key": key, "values": values, "total": sum(values)} for key, values in ranked[:top]]
    rest = ranked[top:]
    if rest:
        others = [sum(values[i] for _, values in rest) for i in range(len(days))]
        series.append({"key": "others", "values": others, "total": sum(others)})
    return {"metric": metric, "group_by": group_by, "days": days, "series": series}


def breakdown(rows: Sequence[Row], *, by: str = "provider", metric: str = "cost") -> Dict[str, Any]:
    """Share of a metric per group, largest first."""
    value_of = _metric(metric)
    totals: Dict[str, int] = defaultdict(int)
    for row in rows:
        totals[_group_key(row, by)] += value_of(row)
    grand = sum(totals.values())
    items = [
        {"key": key, "value": value, "share": round(value / grand, 4) if grand else 0.0}
        for key, value in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        if value
    ]
    return {"by": by, "metric": metric, "total": grand, "items": items}


def agents(
    rows: Sequence[Row], previous_rows: Sequence[Row], *, limit: int = 10
) -> Dict[str, Any]:
    """Top agents / workflows by tokens, with change vs the prior period."""

    def key(row: Row) -> Tuple[str, str]:
        return (
            str(row.get("application_id") or UNATTRIBUTED),
            str(row.get("agent_id") or UNATTRIBUTED),
        )

    current: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in rows:
        bucket = current.setdefault(
            key(row),
            {"tokens": 0, "cost_micro": 0, "events": 0, "failed": 0, "providers": defaultdict(int),
             "rows": []},
        )
        tokens = row_tokens(row)
        bucket["tokens"] += tokens
        bucket["cost_micro"] += _cost(row) if _is_api(row) else 0
        bucket["events"] += int(row.get("events") or 0)
        if row.get("status") == "failed":
            bucket["failed"] += int(row.get("events") or 0)
        bucket["providers"][str(row.get("provider") or UNATTRIBUTED)] += tokens
        bucket["rows"].append(row)

    previous: Dict[Tuple[str, str], int] = defaultdict(int)
    for row in previous_rows:
        previous[key(row)] += row_tokens(row)

    items = []
    for (application_id, agent_id), bucket in current.items():
        providers = bucket["providers"]
        items.append({
            "application_id": application_id,
            "agent_id": agent_id,
            "top_provider": max(providers.items(), key=lambda kv: (kv[1], kv[0]))[0],
            "tokens": bucket["tokens"],
            "cost_micro": bucket["cost_micro"],
            "events": bucket["events"],
            "failed": bucket["failed"],
            "delta_pct": _delta_pct(bucket["tokens"], previous.get((application_id, agent_id), 0)),
            "measurement_mix": measurement_mix(bucket["rows"]),
        })
    items.sort(key=lambda item: (-item["tokens"], item["application_id"], item["agent_id"]))
    return {"total": len(items), "items": items[:limit]}


# ── insights ────────────────────────────────────────────────────────────

def insights(rows: Sequence[Row]) -> List[Dict[str, Any]]:
    """Deterministic, evidence-backed observations. Nothing is auto-applied.

    Every insight states the numbers it was derived from, so the dashboard can
    link to the evidence instead of asking to be trusted.
    """
    out: List[Dict[str, Any]] = []
    total_tokens = sum(map(row_tokens, rows))
    total_events = sum(int(r.get("events") or 0) for r in rows)
    if not total_events:
        return out

    # 1. Money spent on attempts that failed.
    failed = [r for r in rows if r.get("status") == "failed"]
    failed_events = sum(int(r.get("events") or 0) for r in failed)
    failed_cost = sum(_cost(r) for r in failed if _is_api(r))
    if failed_events and failed_events / total_events >= 0.05:
        out.append({
            "id": "failed_attempts",
            "severity": "warning",
            "title": "Failed requests are a noticeable share of traffic",
            "detail": f"{failed_events} of {total_events} attempts failed.",
            "evidence": {"failed_events": failed_events, "events": total_events,
                         "failed_cost_micro": failed_cost},
            "estimated_saving_micro": failed_cost or None,
        })

    # 2. Large uncached input on providers that support prompt caching.
    by_provider: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        provider = str(row.get("provider") or "")
        if provider in _CACHE_CAPABLE and _is_api(row):
            by_provider[provider]["input"] += int(row.get("input_tokens") or 0)
            by_provider[provider]["cache_read"] += int(row.get("cache_read_tokens") or 0)
    for provider, sums in sorted(by_provider.items()):
        prompt_side = sums["input"] + sums["cache_read"]
        if prompt_side >= 1_000_000 and sums["cache_read"] / prompt_side < 0.05:
            out.append({
                "id": f"low_cache_hit:{provider}",
                "severity": "info",
                "title": f"Prompt caching is barely used on {provider}",
                "detail": "Most prompt tokens were billed at the uncached rate. "
                          "Stable system prompts and tool definitions are cacheable.",
                "evidence": {"provider": provider, "input_tokens": sums["input"],
                             "cache_read_tokens": sums["cache_read"]},
                "estimated_saving_micro": None,
            })

    # 3. Usage nobody is accountable for.
    unattributed = sum(row_tokens(r) for r in rows if not r.get("agent_id"))
    if total_tokens and unattributed / total_tokens >= 0.25:
        out.append({
            "id": "unattributed_usage",
            "severity": "info",
            "title": "A large share of tokens has no agent attribution",
            "detail": "Send X-OllaBridge-App and X-OllaBridge-Agent so spend can be "
                      "traced to a workflow.",
            "evidence": {"unattributed_tokens": unattributed, "tokens": total_tokens},
            "estimated_saving_micro": None,
        })

    # 4. Numbers that are guesses.
    mix = measurement_mix(rows)
    if mix.get("estimated", 0.0) >= 0.25:
        out.append({
            "id": "estimated_share",
            "severity": "info",
            "title": "Many token counts are estimates",
            "detail": "These requests returned no usage from the provider, so counts "
                      "were approximated from text length.",
            "evidence": {"estimated_share": mix["estimated"]},
            "estimated_saving_micro": None,
        })

    # 5. API spend that could not be priced.
    unpriced = sum(int(r.get("unpriced_tokens") or 0) for r in rows if _is_api(r))
    if total_tokens and unpriced / total_tokens >= 0.10:
        out.append({
            "id": "unpriced_usage",
            "severity": "info",
            "title": "Some API usage has no price in the catalog",
            "detail": "Estimated cost is a lower bound until these models are priced.",
            "evidence": {"unpriced_tokens": unpriced, "tokens": total_tokens},
            "estimated_saving_micro": None,
        })
    return out
