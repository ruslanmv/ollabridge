"""Local usage API: ``/v1/bi/*`` (dashboard) and ``/otlp/v1/*`` (telemetry in).

``/v1/bi/*`` returns the same shapes as OllaBridge Cloud's, so one dashboard
serves both.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ollabridge.core.security import _is_loopback, require_api_key
from ollabridge.core.settings import settings

from . import bi_core, capture, otlp, outbox
from .store import get_usage_store

router = APIRouter(tags=["usage"])

MAX_RANGE_DAYS = 400
MAX_OTLP_BYTES = 4 * 1024 * 1024


def _period(from_: Optional[dt.date], to: Optional[dt.date]) -> tuple[dt.date, dt.date]:
    end = to or dt.datetime.now(dt.timezone.utc).date()
    start = from_ or end - dt.timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"range is limited to {MAX_RANGE_DAYS} days")
    return start, end


def _filters(provider, application_id, agent_id, device_id) -> Dict[str, Optional[str]]:
    return {"provider": provider, "application_id": application_id,
            "agent_id": agent_id, "device_id": device_id}


# ── dashboard reads ─────────────────────────────────────────────────────

@router.get("/v1/bi/overview", dependencies=[Depends(require_api_key)])
def bi_overview(
    from_: Optional[dt.date] = Query(default=None, alias="from"),
    to: Optional[dt.date] = None,
    provider: Optional[str] = None,
    application_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    start, end = _period(from_, to)
    prev_start, prev_end = bi_core.previous_period(start, end)
    today = dt.datetime.now(dt.timezone.utc).date()
    store, filters = get_usage_store(), _filters(provider, application_id, agent_id, device_id)
    return bi_core.overview(
        store.rollup_rows(start, end, **filters),
        store.rollup_rows(prev_start, prev_end, **filters),
        start=start, end=end,
        budget_limit_micro=store.get_budget_limit(),
        month_rows=store.rollup_rows(today.replace(day=1), today),
        today=today,
    )


@router.get("/v1/bi/timeseries", dependencies=[Depends(require_api_key)])
def bi_timeseries(
    from_: Optional[dt.date] = Query(default=None, alias="from"),
    to: Optional[dt.date] = None,
    metric: str = Query(default="tokens", pattern="^(tokens|cost|events)$"),
    group_by: str = "provider",
    provider: Optional[str] = None,
    application_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    if group_by not in bi_core.GROUPABLE:
        raise HTTPException(status_code=422, detail=f"group_by must be one of {bi_core.GROUPABLE}")
    start, end = _period(from_, to)
    rows = get_usage_store().rollup_rows(
        start, end, **_filters(provider, application_id, agent_id, device_id)
    )
    return bi_core.timeseries(rows, start=start, end=end, metric=metric, group_by=group_by)


@router.get("/v1/bi/breakdown", dependencies=[Depends(require_api_key)])
def bi_breakdown(
    from_: Optional[dt.date] = Query(default=None, alias="from"),
    to: Optional[dt.date] = None,
    by: str = "provider",
    metric: str = Query(default="cost", pattern="^(tokens|cost|events)$"),
) -> Dict[str, Any]:
    if by not in bi_core.GROUPABLE:
        raise HTTPException(status_code=422, detail=f"by must be one of {bi_core.GROUPABLE}")
    start, end = _period(from_, to)
    return bi_core.breakdown(get_usage_store().rollup_rows(start, end), by=by, metric=metric)


@router.get("/v1/bi/agents", dependencies=[Depends(require_api_key)])
def bi_agents(
    from_: Optional[dt.date] = Query(default=None, alias="from"),
    to: Optional[dt.date] = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> Dict[str, Any]:
    start, end = _period(from_, to)
    prev_start, prev_end = bi_core.previous_period(start, end)
    store = get_usage_store()
    return bi_core.agents(
        store.rollup_rows(start, end), store.rollup_rows(prev_start, prev_end), limit=limit
    )


@router.get("/v1/bi/insights", dependencies=[Depends(require_api_key)])
def bi_insights(
    from_: Optional[dt.date] = Query(default=None, alias="from"),
    to: Optional[dt.date] = None,
) -> Dict[str, Any]:
    start, end = _period(from_, to)
    return {"items": bi_core.insights(get_usage_store().rollup_rows(start, end))}


@router.get("/v1/bi/events", dependencies=[Depends(require_api_key)])
def bi_events(
    trace_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> Dict[str, Any]:
    """Raw events — the evidence behind a number. Newest first."""
    rows = get_usage_store().events(trace_id=trace_id, agent_id=agent_id, limit=limit)
    for row in rows:
        row.pop("sync_state", None)
    return {"items": rows}


@router.get("/v1/bi/sources", dependencies=[Depends(require_api_key)])
def bi_sources() -> Dict[str, Any]:
    """Where usage comes from, how fresh it is, and what has synced."""
    allowed, reason = outbox.sync_allowed()
    store = get_usage_store()
    return {
        "capture_enabled": capture.enabled(),
        "sources": store.sources(),
        "cloud_sync": {"enabled": allowed, "reason": reason, "counts": store.sync_counts()},
        "pricing_version": capture.get_catalog().version,
    }


class BudgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: Monthly limit in micro-USD; null removes the budget.
    limit_micro: Optional[int] = Field(default=None, ge=1, le=10**15)


@router.get("/v1/bi/budget", dependencies=[Depends(require_api_key)])
def get_budget() -> Dict[str, Any]:
    return {"period": "monthly", "limit_micro": get_usage_store().get_budget_limit()}


@router.put("/v1/bi/budget", dependencies=[Depends(require_api_key)])
def put_budget(body: BudgetBody) -> Dict[str, Any]:
    get_usage_store().set_budget_limit(body.limit_micro)
    return {"period": "monthly", "limit_micro": body.limit_micro}


@router.post("/v1/bi/sync", dependencies=[Depends(require_api_key)])
async def bi_sync() -> Dict[str, Any]:
    """Upload pending usage metadata now (only if the user enabled it)."""
    return await outbox.sync_once()


# ── telemetry in (Claude Code OTLP http/json) ───────────────────────────

def _otlp_caller(request: Request) -> None:
    """Loopback callers need no key — the exporter runs on this machine.
    Anything else must present a normal API key."""
    if _is_loopback(request):
        return
    require_api_key(
        request,
        x_api_key=request.headers.get("x-api-key"),
        authorization=request.headers.get("authorization"),
    )


async def _otlp_json(request: Request) -> Dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        raise HTTPException(
            status_code=415,
            detail="Send OTLP as JSON: set OTEL_EXPORTER_OTLP_PROTOCOL=http/json",
        )
    body = await request.body()
    if len(body) > MAX_OTLP_BYTES:
        raise HTTPException(status_code=413, detail="OTLP payload too large")
    try:
        import json

        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="OTLP payload must be an object")
    return payload


@router.post("/otlp/v1/logs", dependencies=[Depends(_otlp_caller)])
async def otlp_logs(request: Request) -> Dict[str, Any]:
    """Receive Claude Code events; store one usage event per API request."""
    payload = await _otlp_json(request)
    if capture.enabled():
        store = get_usage_store()
        for event in otlp.parse_logs(payload, billing_mode=settings.CLAUDE_CODE_BILLING):
            capture.price(event)
            store.record(event)
    return {}  # OTLP success: empty ExportLogsServiceResponse


@router.post("/otlp/v1/metrics", dependencies=[Depends(_otlp_caller)])
async def otlp_metrics(request: Request) -> Dict[str, Any]:
    """Accepted and discarded: per-request events already carry the usage, and
    counting the aggregate metrics as well would double count."""
    await _otlp_json(request)
    return {}
