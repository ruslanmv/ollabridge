"""Models → Testing: ``POST /v1/models/check`` and ``GET /v1/models/checks``.

A check goes through the gateway's own ``/v1/chat/completions`` in-process, so
it meets the same routing, rate limits and error codes as every real client.
The page runs the queue (two at a time) and Stop; this route checks one model.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ollabridge import model_checks as mc
from ollabridge.core.security import require_api_key

router = APIRouter(tags=["models"])

_INVENTORY_TTL_S = 30.0
_inventory_cache: Dict[int, Tuple[float, List[Dict[str, Any]]]] = {}
_store: Optional[mc.CheckStore] = None


def get_store() -> mc.CheckStore:
    global _store
    if _store is None:
        _store = mc.CheckStore()
    return _store


async def _inventory(request: Request) -> List[Dict[str, Any]]:
    """The gateway's models, cached briefly so "Check all" lists them once."""
    key = id(request.app)
    cached = _inventory_cache.get(key)
    if cached and time.monotonic() - cached[0] < _INVENTORY_TTL_S:
        return cached[1]
    collect = getattr(request.app.state, "collect_models", None)
    models: List[Dict[str, Any]] = []
    if collect is not None:
        models, _ = await collect()
    _inventory_cache[key] = (time.monotonic(), models)
    return models


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=256)


async def _ask(request: Request, model: str) -> Tuple[Optional[int], Any, int, bool]:
    """One chat call to this same app. → (status, body, latency_ms, timed_out)."""
    headers = {"X-OllaBridge-App": mc.CHECK_APP, "Content-Type": "application/json"}
    for name in ("x-api-key", "authorization"):  # the caller's own credentials, if any
        if request.headers.get(name):
            headers[name] = request.headers[name]
    client_host = request.client.host if request.client else "127.0.0.1"
    transport = httpx.ASGITransport(app=request.app, client=(client_host, 0))
    payload = {"model": model, "max_tokens": mc.CHECK_MAX_TOKENS, "stream": False,
               "messages": [{"role": "user", "content": mc.CHECK_MESSAGE}]}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://ollabridge.internal") as client:
            response = await asyncio.wait_for(
                client.post("/v1/chat/completions", json=payload, headers=headers),
                timeout=mc.CHECK_TIMEOUT_S,
            )
    except asyncio.TimeoutError:
        return None, None, int((time.monotonic() - started) * 1000), True
    latency = int((time.monotonic() - started) * 1000)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body, latency, False


@router.post("/v1/models/check", dependencies=[Depends(require_api_key)])
async def check_model(body: CheckBody, request: Request) -> Dict[str, Any]:
    """Send the fixed check message to one model; return its verdict."""
    inventory = await _inventory(request)
    entry = next((m for m in inventory if m.get("id") == body.model), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"'{body.model}' is not in this gateway's model list")
    source = entry.get("source_display_name") or entry.get("source")
    status, reply, latency, timed_out = await _ask(request, body.model)
    result = {
        "model": body.model,
        "source": source,
        "latency_ms": None if timed_out else latency,
        "http_status": status,
        "checked_at": mc.now_iso(),
        **mc.verdict(status=status, body=reply, latency_ms=latency, timed_out=timed_out,
                     source=source, inventory_ids=[m.get("id") for m in inventory if m.get("id")],
                     model=body.model),
    }
    get_store().save(result)
    return result


@router.get("/v1/models/checks", dependencies=[Depends(require_api_key)])
def last_checks() -> Dict[str, Any]:
    """The last check of every model, by model id."""
    return {"items": get_store().all()}
