"""Per-model usage view (``GET /v1/bi/models``) — local only.

``bi_core.py`` is shared with OllaBridge Cloud and hash-pinned, so this view
lives here. Every number comes from one :meth:`UsageStore.model_rows` read:
the totals, the table and the chart are sums over the same rows and reconcile
by construction.

Rules (docs/USAGE_BY_MODEL_DESIGN.md):

- A row is ``(provider, model)`` with the *resolved* model id. The same model
  through two providers is two rows; a request made through an alias is one
  event, recorded under the model it resolved to, so it is counted once.
- Unknown is not zero: token sums are ``None`` when no event of the row had a
  count, and a cost with no price is ``unpriced``, never 0.
- Inventory (what the gateway offers now) is kept apart from usage: it never
  adds usage rows, and usage never adds "available" models.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .bi_core import UNATTRIBUTED, day_range

Row = Mapping[str, Any]
Key = Tuple[str, str]

UNKNOWN_MODEL = "unknown"
_INPUT = ("input_tokens", "cache_read_tokens", "cache_write_tokens")
_OUTPUT = ("output_tokens", "reasoning_tokens")
_FAILED = ("failed", "interrupted")

# Thresholds for the insights (kept here so tests can name them).
FAIL_MIN_COUNT = 3
FAIL_MIN_RATE = 0.5
SPIKE_FACTOR = 3.0
SPIKE_MIN_HISTORY = 5


def _add(current: Optional[int], value: Any) -> Optional[int]:
    """Sum that stays ``None`` until a known value arrives."""
    if value is None:
        return current
    return (current or 0) + int(value)


def _side(row: Row, dims: Sequence[str]) -> Optional[int]:
    values = [row.get(d) for d in dims if row.get(d) is not None]
    return sum(int(v) for v in values) if values else None


def inventory_key(entry: Mapping[str, Any]) -> Optional[Key]:
    """``(provider, model id)`` as the ledger would record it."""
    model_id = entry.get("id")
    if not model_id:
        return None
    provider = entry.get("provider_id")
    if not provider:
        source = str(entry.get("source") or "")
        if source.startswith("byok:"):
            provider = f"byok-{source[len('byok:'):]}"
        elif source == "homepilot":
            provider = "homepilot"
        else:
            # Ollama, relay nodes and direct endpoints are recorded as the
            # local runtime (usage/capture.py _classify).
            provider = "ollama"
    return str(provider).lower(), str(model_id)


def _unreachable_providers(unreachable: Iterable[Mapping[str, Any]]) -> set:
    out = set()
    for item in unreachable:
        if item.get("provider_id"):
            out.add(str(item["provider_id"]).lower())
        elif item.get("source") in ("ollama", "relay_link", "direct_endpoint", "providers", None, ""):
            out.add("ollama" if item.get("source") != "providers" else "*")
        elif item.get("source") == "homepilot":
            out.add("homepilot")
    return out


def cost_state(
    *, api_cost: int, api_priced: int, api_unpriced_tokens: int, api_tokens: Optional[int],
    subscription_cost: int, modes: Iterable[str], has_tokens: bool,
) -> Dict[str, Any]:
    """How a cost figure may be shown.

    ``priced``       every API token has a price → ``micro`` is the cost
    ``partial``      some API tokens unpriced → ``micro`` is a floor
    ``unpriced``     API usage with no price at all → no figure
    ``subscription`` covered by a subscription → ``micro`` is the API equivalent
    ``not_billed``   only local / free-tier usage → no figure
    ``none``         nothing measured (e.g. only failed requests)
    """
    modes = sorted({m for m in modes if m})
    if api_tokens:
        if api_priced == 0:
            return {"state": "unpriced", "micro": None, "unpriced_tokens": api_unpriced_tokens, "modes": modes}
        state = "partial" if api_unpriced_tokens else "priced"
        return {"state": state, "micro": api_cost, "unpriced_tokens": api_unpriced_tokens, "modes": modes}
    if api_priced:
        # Priced API events without tokens (a provider-stated charge only).
        return {"state": "priced", "micro": api_cost, "unpriced_tokens": 0, "modes": modes}
    if subscription_cost:
        return {"state": "subscription", "micro": subscription_cost, "unpriced_tokens": 0, "modes": modes}
    if has_tokens:
        return {"state": "not_billed", "micro": None, "unpriced_tokens": 0, "modes": modes}
    return {"state": "none", "micro": None, "unpriced_tokens": 0, "modes": modes}


class _Bucket:
    """Running sums for one model row (or the grand total)."""

    def __init__(self, days: List[str]) -> None:
        self.index = {d: i for i, d in enumerate(days)}
        self.events = self.failed = self.unknown_events = 0
        self.input: Optional[int] = None
        self.output: Optional[int] = None
        self.dims: Dict[str, Optional[int]] = {}
        self.api_cost = self.api_priced = self.api_unpriced = 0
        self.api_tokens: Optional[int] = None
        self.sub_cost = 0
        self.modes: set = set()
        self.daily_tokens = [0] * len(days)
        self.daily_events = [0] * len(days)
        self.daily_cost = [0] * len(days)
        self.errors: Dict[str, int] = defaultdict(int)
        self.requested: Dict[str, int] = defaultdict(int)
        self.measurement: Dict[str, int] = defaultdict(int)
        self.execution: set = set()
        self.billing_providers: set = set()
        self.latency_sum = self.latency_count = 0
        self.last_seen: Optional[str] = None

    def add(self, row: Row) -> None:
        events = int(row.get("events") or 0)
        position = self.index.get(str(row.get("day")))
        inp, out = _side(row, _INPUT), _side(row, _OUTPUT)
        tokens = None if inp is None and out is None else (inp or 0) + (out or 0)
        mode = str(row.get("billing_mode") or "api")
        cost = int(row.get("cost_micro") or 0)

        self.events += events
        self.unknown_events += int(row.get("unknown_events") or 0)
        if row.get("status") in _FAILED:
            self.failed += events
            self.errors[str(row.get("error_category") or "unknown")] += events
        self.input, self.output = _add(self.input, inp), _add(self.output, out)
        for d in (*_INPUT, *_OUTPUT):
            self.dims[d] = _add(self.dims.get(d), row.get(d))
        self.modes.add(mode)
        if mode == "api":
            self.api_cost += cost
            self.api_priced += int(row.get("priced_events") or 0)
            self.api_unpriced += int(row.get("unpriced_tokens") or 0)
            self.api_tokens = _add(self.api_tokens, tokens)
        elif mode == "subscription":
            self.sub_cost += cost
        if position is not None:
            self.daily_tokens[position] += tokens or 0
            self.daily_events[position] += events
            if mode == "api":
                self.daily_cost[position] += cost
        requested = row.get("requested_model")
        if requested and requested != row.get("model"):
            self.requested[str(requested)] += events
        self.measurement[str(row.get("measurement") or "unavailable")] += events
        if row.get("execution"):
            self.execution.add(str(row["execution"]))
        if row.get("billing_provider") and row.get("billing_provider") != row.get("provider"):
            self.billing_providers.add(str(row["billing_provider"]))
        self.latency_sum += int(row.get("latency_sum") or 0)
        self.latency_count += int(row.get("latency_count") or 0)
        seen = row.get("last_seen")
        if seen and (self.last_seen is None or str(seen) > self.last_seen):
            self.last_seen = str(seen)

    @property
    def total(self) -> Optional[int]:
        if self.input is None and self.output is None:
            return None
        return (self.input or 0) + (self.output or 0)

    def cost(self) -> Dict[str, Any]:
        return cost_state(
            api_cost=self.api_cost, api_priced=self.api_priced,
            api_unpriced_tokens=self.api_unpriced, api_tokens=self.api_tokens,
            subscription_cost=self.sub_cost, modes=self.modes, has_tokens=bool(self.total),
        )


def _spike(days: List[str], daily: List[int]) -> Optional[Dict[str, Any]]:
    """The largest day whose tokens are ≥ SPIKE_FACTOR × the median of the
    used days before it (at least SPIKE_MIN_HISTORY of them)."""
    best = None
    for i, value in enumerate(daily):
        history = [v for v in daily[:i] if v > 0]
        if len(history) < SPIKE_MIN_HISTORY or value <= 0:
            continue
        median = statistics.median(history)
        if median and value >= SPIKE_FACTOR * median:
            factor = round(value / median, 1)
            if best is None or factor > best["factor"]:
                best = {"day": days[i], "tokens": value, "median": int(median), "factor": factor}
    return best


def build(
    rows: Sequence[Row],
    *,
    start: dt.date,
    end: dt.date,
    inventory: Optional[Sequence[Mapping[str, Any]]] = None,
    unreachable: Sequence[Mapping[str, Any]] = (),
    capture_enabled: bool = True,
) -> Dict[str, Any]:
    """The whole per-model view from one set of rows."""
    days = day_range(start, end)
    total = _Bucket(days)
    models: Dict[Key, _Bucket] = {}
    sources: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        key = (str(row.get("provider") or "unknown"), str(row.get("model") or UNKNOWN_MODEL))
        models.setdefault(key, _Bucket(days)).add(row)
        total.add(row)
        app = row.get("application_id") or None
        src = sources.setdefault(app or UNATTRIBUTED, {
            "key": app or UNATTRIBUTED, "attributed": bool(app), "tokens": 0, "events": 0, "failed": 0,
        })
        src["tokens"] += (_side(row, _INPUT) or 0) + (_side(row, _OUTPUT) or 0)
        src["events"] += int(row.get("events") or 0)
        if row.get("status") in _FAILED:
            src["failed"] += int(row.get("events") or 0)

    # ── inventory ──
    down = _unreachable_providers(unreachable)
    inv_keys: Dict[Key, Mapping[str, Any]] = {}
    if inventory is not None:
        for entry in inventory:
            k = inventory_key(entry)
            if k is not None:
                inv_keys.setdefault(k, entry)

    items: List[Dict[str, Any]] = []
    for (provider, model), bucket in models.items():
        if inventory is None:
            in_inventory: Optional[bool] = None
        elif (provider, model) in inv_keys:
            in_inventory = True
        elif provider in down or "*" in down:
            in_inventory = None  # its runtime could not be asked
        else:
            in_inventory = False
        entry = inv_keys.get((provider, model)) or {}
        items.append({
            "provider": provider,
            "model": model,
            "source": entry.get("source"),
            "source_display_name": entry.get("source_display_name"),
            "runtime_unreachable": provider in down,
            "in_inventory": in_inventory,
            "tokens": {"total": bucket.total, "input": bucket.input, "output": bucket.output,
                       "dimensions": bucket.dims},
            "requests": bucket.events,
            "failed": bucket.failed,
            "unknown_usage": bucket.unknown_events,
            "errors": dict(sorted(bucket.errors.items(), key=lambda kv: -kv[1])),
            "requested_as": dict(sorted(bucket.requested.items(), key=lambda kv: -kv[1])),
            "measurement": dict(bucket.measurement),
            "execution": sorted(bucket.execution),
            "billing_providers": sorted(bucket.billing_providers),
            "cost": bucket.cost(),
            "avg_latency_ms": round(bucket.latency_sum / bucket.latency_count) if bucket.latency_count else None,
            "last_seen": bucket.last_seen,
            "daily": {"tokens": bucket.daily_tokens, "requests": bucket.daily_events,
                      "cost": bucket.daily_cost},
        })
    items.sort(key=lambda m: (-(m["tokens"]["total"] or 0), -m["requests"], m["model"], m["provider"]))

    used = set(models)
    if inventory is None:
        inventory_view: Dict[str, Any] = {"available": None, "used": len(used), "never_used": None,
                                          "not_in_inventory": None, "unreachable": list(unreachable),
                                          "by_source": {}, "never_used_models": []}
    else:
        by_source: Dict[str, int] = defaultdict(int)
        for entry in inv_keys.values():
            by_source[str(entry.get("source_display_name") or entry.get("source") or "unknown")] += 1
        never = [
            {"provider": k[0], "model": k[1], "source_display_name": e.get("source_display_name"),
             "category": e.get("category")}
            for k, e in sorted(inv_keys.items()) if k not in used
        ]
        inventory_view = {
            "available": len(inv_keys),
            "used": len(used),
            "used_in_inventory": len(used & set(inv_keys)),
            "never_used": len(never),
            "not_in_inventory": sum(1 for m in items if m["in_inventory"] is False),
            "unreachable": list(unreachable),
            "by_source": dict(sorted(by_source.items())),
            "never_used_models": never,
        }

    source_items = sorted(sources.values(), key=lambda s: (-s["tokens"], -s["events"], s["key"]))
    totals = {
        "tokens": {"total": total.total, "input": total.input, "output": total.output},
        "requests": total.events,
        "failed": total.failed,
        "failed_pct": round(total.failed / total.events * 100, 1) if total.events else None,
        "unknown_usage": total.unknown_events,
        "models_used": len(used),
        "cost": total.cost(),
    }
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "capture_enabled": capture_enabled,
        "days": days,
        "totals": totals,
        "daily": {"tokens": total.daily_tokens, "requests": total.daily_events, "cost": total.daily_cost},
        "models": items,
        "sources": {"attributed": any(s["attributed"] for s in source_items), "items": source_items},
        "inventory": inventory_view,
        "insights": insights(items, days, total.daily_tokens),
    }


def insights(models: Sequence[Mapping[str, Any]], days: List[str], daily_tokens: List[int]) -> List[Dict[str, Any]]:
    """Deterministic observations, each with the numbers behind it."""
    out: List[Dict[str, Any]] = []
    failing = set()
    for m in models:
        if m["failed"] >= FAIL_MIN_COUNT and m["failed"] / max(m["requests"], 1) >= FAIL_MIN_RATE:
            top = next(iter(m["errors"]), None)
            failing.add((m["provider"], m["model"]))
            out.append({
                "id": f"repeated_failures:{m['provider']}:{m['model']}",
                "kind": "repeated_failures", "severity": "warning",
                "provider": m["provider"], "model": m["model"],
                # One observation per model: a failing model that is also gone
                # from the inventory says both here.
                "evidence": {"failed": m["failed"], "requests": m["requests"], "top_error": top,
                             "in_inventory": m["in_inventory"]},
            })
    for m in models:
        if m["in_inventory"] is False and (m["provider"], m["model"]) not in failing:
            out.append({
                "id": f"not_in_inventory:{m['provider']}:{m['model']}",
                "kind": "not_in_inventory", "severity": "info",
                "provider": m["provider"], "model": m["model"],
                "evidence": {"requests": m["requests"], "failed": m["failed"]},
            })
    spike = _spike(days, daily_tokens)
    if spike:
        out.append({"id": f"spike:{spike['day']}", "kind": "spike", "severity": "info",
                    "provider": None, "model": None, "evidence": spike})
    unpriced = [m for m in models if m["cost"]["unpriced_tokens"]]
    if unpriced:
        out.append({
            "id": "unpriced_usage", "kind": "unpriced_usage", "severity": "info",
            "provider": None, "model": None,
            "evidence": {"unpriced_tokens": sum(m["cost"]["unpriced_tokens"] for m in unpriced),
                         "models": [f"{m['provider']}:{m['model']}" for m in unpriced]},
        })
    return out
