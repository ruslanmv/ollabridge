"""
Trace Relay Routes — REST API for forwarding embodiment traces to HomePilot.

ADDITIVE ONLY: New file, new router. Mounted via app.include_router()
in main.py alongside world_state_router.

Endpoints:
  POST /v1/traces  — Accept trace batch from 3D client, relay to HomePilot
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ollabridge.core.security import require_api_key

log = logging.getLogger("ollabridge.trace_relay")

router = APIRouter(tags=["trace-relay"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class TraceEventPayload(BaseModel):
    """Single trace event from the client-side TraceRecorder."""
    trace_id: str = ""
    event_id: str = ""
    seq: int = 0
    timestamp: str = ""
    elapsed_ms: float = 0
    kind: str = "custom"
    name: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = None


class TraceBatchRequest(BaseModel):
    """Batch of trace events flushed from the client."""
    trace_id: str
    persona_id: str = ""
    events: List[TraceEventPayload]
    flushed_at: str = ""


class TraceBatchResponse(BaseModel):
    """Response after relay attempt."""
    accepted: int
    relayed: bool
    trace_id: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Lazy TraceRelay accessor
# ---------------------------------------------------------------------------

def _get_trace_relay(app):
    """Get or create the TraceRelay singleton on app.state."""
    relay = getattr(app.state, "_trace_relay", None)
    if relay is None:
        from ollabridge.connectors.trace_relay import TraceRelay
        from ollabridge.core import runtime_settings as rts

        cfg = rts.get_all()
        hp_base = cfg.get("homepilot_base_url", "")
        hp_key = cfg.get("homepilot_api_key", "")

        relay = TraceRelay(homepilot_base=hp_base, api_key=hp_key)
        app.state._trace_relay = relay
    return relay


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/v1/traces", response_model=TraceBatchResponse)
async def ingest_traces(
    req: TraceBatchRequest,
    request: Request,
    _key: str = Depends(require_api_key),
):
    """
    Accept a batch of trace events from the 3D-Avatar-Chatbot client
    and relay them to HomePilot's spatial memory service.

    If HomePilot is not configured, events are accepted (202) but not relayed.
    """
    relay = _get_trace_relay(request.app)

    events_dicts = [ev.model_dump() for ev in req.events]

    result = await relay.relay_traces(
        trace_id=req.trace_id,
        persona_id=req.persona_id,
        events=events_dicts,
        flushed_at=req.flushed_at,
    )

    relayed = result.get("relayed", False)
    detail = ""
    if not relayed:
        detail = result.get("reason", result.get("error", "unknown"))

    return TraceBatchResponse(
        accepted=len(events_dicts),
        relayed=relayed,
        trace_id=req.trace_id,
        detail=detail,
    )
