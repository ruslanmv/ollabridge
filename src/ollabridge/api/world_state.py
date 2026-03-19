"""
World-State Relay — forwards VR spatial updates to HomePilot.

Additive module: does not modify any existing OllaBridge code.
Provides endpoints for VR clients to push world state through
OllaBridge to HomePilot's world-state service.

Endpoints:
  POST /v1/world-state/update  — relay world state to HomePilot
  POST /world-state/update     — legacy path (WorldStateBridge.js)
  GET  /v1/persona/{id}/motion — relay motion plan polling from HomePilot
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["world-state"])

# Shared HTTP client for relaying to HomePilot
_relay_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _relay_client
    if _relay_client is None:
        _relay_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=True,
        )
    return _relay_client


async def _find_homepilot_base(app: Any) -> str | None:
    """Find the first HomePilot node endpoint from the registry."""
    try:
        registry = app.state.obridge.registry
        nodes = registry.healthy_nodes()
        for node in nodes:
            if node.connector == "homepilot" and node.endpoint:
                return node.endpoint.rstrip("/")
    except Exception:
        pass
    return None


@router.post("/v1/world-state/update")
async def world_state_relay(request: Request) -> JSONResponse:
    """
    Relay world-state update from VR client to HomePilot.
    Fire-and-forget: returns immediately, errors are logged.
    """
    base = await _find_homepilot_base(request.app)
    if not base:
        return JSONResponse(status_code=200, content={"ok": True, "relayed": False})

    body = await request.json()

    try:
        client = _get_client()
        await client.post(
            f"{base}/v1/world-state/update",
            json=body,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        logger.debug("[world-state] relay failed: %s", e)

    return JSONResponse(status_code=200, content={"ok": True, "relayed": True})


@router.post("/world-state/update")
async def world_state_relay_legacy(request: Request) -> JSONResponse:
    """Legacy path — WorldStateBridge.js pushes to /world-state/update."""
    base = await _find_homepilot_base(request.app)
    if not base:
        return JSONResponse(status_code=200, content={"ok": True, "relayed": False})

    body = await request.json()

    try:
        client = _get_client()
        await client.post(
            f"{base}/world-state/update",
            json=body,
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:
        logger.debug("[world-state] legacy relay failed: %s", e)

    return JSONResponse(status_code=200, content={"ok": True, "relayed": True})


@router.get("/v1/persona/{persona_id}/motion")
async def motion_plan_relay(persona_id: str, request: Request) -> JSONResponse:
    """
    Relay motion plan polling from VR client to HomePilot.
    """
    base = await _find_homepilot_base(request.app)
    if not base:
        return JSONResponse(status_code=200, content={"motion_plan": None})

    try:
        client = _get_client()
        resp = await client.get(f"{base}/v1/persona/{persona_id}/motion")
        resp.raise_for_status()
        return JSONResponse(status_code=200, content=resp.json())
    except Exception as e:
        logger.debug("[motion] relay failed: %s", e)
        return JSONResponse(status_code=200, content={"motion_plan": None})
