"""Read the gateway's current settings for one question: what happens when
many calls arrive at once?

Nothing is changed and no provider is contacted. With the gateway running
the audit reads ``GET /admin/rate-limits`` (the same data as Settings → Rate
limits: saved limits, calls routed per provider, recent rate-limit answers);
without it, the saved settings and the configured sources on disk.

Also here: :func:`apply_provider_limit`, the one place the diagnosis writes
anything, and only when ``--apply`` names a provider.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import httpx

from ollabridge.core import rate_limits
from ollabridge.core.rate_limits import (
    DEFAULT_PROVIDER_LIMIT,
    ProviderLimit,
    RateLimitSettings,
)

Finding = dict[str, str]

#: An inbound limit below this refuses a parallel run from one client.
LOW_INBOUND_RPM = 600


def _finding(level: str, subject: str, detail: str, fix: str = "") -> Finding:
    return {"level": level, "subject": subject, "detail": detail, "fix": fix}


def _limit_text(limits: Mapping[str, Any]) -> str:
    pace = f"{limits['requests_per_minute']}/minute" if limits["requests_per_minute"] else "no pace"
    cap = f"{limits['max_concurrent']} at once" if limits["max_concurrent"] else "no cap on parallel calls"
    mode = (
        f"waits and retries up to {limits['max_wait_seconds']} s"
        if limits["on_rate_limit"] == "wait_retry"
        else "fails fast on a rate limit"
    )
    return f"{pace}, {cap}, {mode}"


def _provider_finding(
    pid: str, name: str, limits: Mapping[str, Any], *, requests: int, limited_last_hour: int
) -> Finding:
    label = name if name == pid else f"{name} ({pid})"
    fix = (
        f"measure it and apply the result: ollabridge diagnose chat --model {pid}/<model> --apply {pid}  "
        "(or Settings → Rate limits → Use suggested)"
    )
    unbounded = not limits["requests_per_minute"] and not limits["max_concurrent"]
    used = f"{requests} call(s) routed" + (f", {limited_last_hour} rate-limited in the last hour" if limited_last_hour else "")
    if limits["on_rate_limit"] == "fail_fast":
        return _finding(
            "warn",
            label,
            f"{_limit_text(limits)}; {used}. A burst over the provider's own limit is answered with a 429 "
            "to every caller at once, and nothing queues or retries",
            fix,
        )
    if unbounded:
        return _finding(
            "warn",
            label,
            f"{_limit_text(limits)}; {used}. Rate limits are retried, but nothing bounds the burst that causes them",
            fix,
        )
    return _finding(
        "ok",
        label,
        f"{_limit_text(limits)}; {used}. Callers must wait longer than {limits['max_wait_seconds']} s plus the "
        "answer time per try, or they give up while their request is still queued",
    )


def audit_settings(
    *,
    view: Mapping[str, Any] | None,
    cfg: RateLimitSettings | None = None,
    source_ids: Mapping[str, str] | None = None,
    env: Mapping[str, str] = os.environ,
) -> list[Finding]:
    """Findings about the current settings. *view* is the gateway's
    ``/admin/rate-limits`` answer when it is running; otherwise *cfg* (the
    saved settings) and *source_ids* (provider id → name of each configured
    source) are used."""
    findings: list[Finding] = []
    if view is not None:
        inbound = view["inbound"]
        rows = list(view.get("providers") or [])
        idle = 0
        for row in rows:
            state = row.get("state") or {}
            limited = int(state.get("rate_limited_last_hour") or 0)
            requests = int(row.get("requests") or 0)
            if not (row.get("configured") or requests or limited):
                idle += 1
                continue
            findings.append(
                _provider_finding(
                    row["id"], row.get("name") or row["id"], row["limits"], requests=requests, limited_last_hour=limited
                )
            )
        if idle:
            findings.append(
                _finding("info", "other providers", f"{idle} registered provider(s) have no limits and no calls since the gateway started")
            )
        if not rows:
            findings.append(_finding("info", "providers", "no provider is registered in the running gateway"))
    else:
        cfg = cfg or rate_limits.current()
        inbound = cfg.inbound.model_dump()
        findings.append(
            _finding("info", "gateway", "not running: read from the saved settings; calls per provider are not known")
        )
        for pid, name in sorted((source_ids or {}).items()):
            limit = cfg.providers.get(pid) or DEFAULT_PROVIDER_LIMIT
            findings.append(_provider_finding(pid, name, limit.model_dump(), requests=0, limited_last_hour=0))

    if inbound.get("enabled"):
        rpm = int(inbound.get("requests_per_minute") or 0)
        refused = int(inbound.get("refused_last_hour") or 0)
        level = "warn" if rpm < LOW_INBOUND_RPM or refused else "ok"
        findings.append(
            _finding(
                level,
                "inbound limit",
                f"on: {rpm} model calls a minute per client"
                + (f", {refused} refused in the last hour" if refused else "")
                + (". A parallel run from one client is cut at that rate" if level == "warn" else ""),
                "raise it, or turn it off, in Settings → Rate limits" if level == "warn" else "",
            )
        )
    else:
        findings.append(_finding("ok", "inbound limit", "off: the gateway itself refuses no caller"))

    connect = env.get("OLLABRIDGE_CONNECT_TIMEOUT_S") or "10"
    network = (env.get("OLLABRIDGE_NETWORK_CHECK") or "on").lower()
    findings.append(
        _finding(
            "info",
            "timeouts",
            f"a provider gets {connect} s to accept a connection and 120 s to answer. A caller whose own limit "
            "per try is shorter gives up first and retries, which doubles the load on a slow provider",
        )
    )
    findings.append(
        _finding(
            "ok" if network not in ("0", "off", "false", "no", "disabled") else "info",
            "network check",
            "on: a lost connection is answered in seconds, not after a timeout per call"
            if network not in ("0", "off", "false", "no", "disabled")
            else "off (OLLABRIDGE_NETWORK_CHECK): a lost connection costs every call its full timeout",
        )
    )
    return findings


def configured_source_ids() -> dict[str, str]:
    """Provider registry id → display name for each enabled source on disk."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss
    from ollabridge.providers_meta import load_providers

    out: dict[str, str] = {}
    for rec in load_providers():
        if not rec.enabled:
            continue
        kind = rec.kind or rec.name
        pid = dss._provider_id() if dss.is_dynamic(kind) else dss.byok_provider_id(rec.name)
        out[pid] = rec.display_name or rec.name
    return out


class ApplyError(RuntimeError):
    pass


def apply_provider_limit(
    provider_id: str,
    limit: Mapping[str, Any],
    *,
    gateway: str,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Save *limit* for *provider_id*: through the running gateway (applies at
    once, without a restart), else in the settings file. Every other setting
    is left as it is. Returns where it was written and the value before."""
    wanted = ProviderLimit(**dict(limit)).model_dump()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = f"{gateway.rstrip('/')}/admin/rate-limits"
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            got = client.get(url, headers=headers)
            if got.status_code in (401, 403):
                raise ApplyError("the gateway refused the API key; nothing was changed")
            if got.status_code != 200:
                raise ApplyError(f"the gateway answered HTTP {got.status_code}; nothing was changed")
            settings = got.json()["settings"]
            before = (settings.get("providers") or {}).get(provider_id)
            settings.setdefault("providers", {})[provider_id] = wanted
            put = client.put(url, headers=headers, json={"settings": settings})
            if put.status_code != 200:
                raise ApplyError(f"the gateway refused the change (HTTP {put.status_code}): {put.text[:200]}")
            return {"where": "the running gateway (applies now)", "before": before, "after": wanted}
    except httpx.TransportError:
        pass  # no gateway on that port: write the file it reads at start
    rate_limits.reload()
    current = rate_limits.current()
    previous = current.providers.get(provider_id)
    rate_limits.save(
        current.model_copy(update={"providers": {**current.providers, provider_id: ProviderLimit(**wanted)}})
    )
    return {
        "where": "the settings file (applies when the gateway next starts)",
        "before": previous.model_dump() if previous else None,
        "after": wanted,
    }
