"""
/admin/cloud/* API routes — manage the OllaBridge Cloud relay connection.

These endpoints let the frontend UI:
  - View cloud connection status
  - Start TV-style pairing with OllaBridge Cloud
  - Poll pairing progress
  - Connect / disconnect the relay bridge
  - Unlink (delete saved credentials)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("ollabridge.cloud")

router = APIRouter(prefix="/admin/cloud", tags=["cloud"])


# ── Request / Response Models ────────────────────────────────────────


class CloudPairStartRequest(BaseModel):
    cloud_url: str


class CloudConnectRequest(BaseModel):
    cloud_url: str
    device_token: str
    device_id: str = ""


# ── Helpers ──────────────────────────────────────────────────────────


def _get_bridge(request: Request):
    mgr = getattr(request.app.state, "cloud_bridge", None)
    if mgr is None:
        raise HTTPException(503, "Cloud bridge manager not initialized")
    return mgr


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/status")
async def cloud_status(request: Request):
    """Current cloud relay connection status."""
    mgr = _get_bridge(request)
    return mgr.status.to_dict()


@router.post("/pair/start")
async def cloud_pair_start(request: Request, body: CloudPairStartRequest):
    """Start TV-style device pairing with OllaBridge Cloud."""
    mgr = _get_bridge(request)
    try:
        result = await mgr.start_pairing(body.cloud_url)
        return {
            "ok": True,
            "user_code": result.user_code,
            "verification_url": result.verification_url,
            "expires_in": result.expires_in,
        }
    except Exception as exc:
        raise HTTPException(502, f"Failed to start pairing: {exc}")


@router.post("/pair/poll")
async def cloud_pair_poll(request: Request):
    """Poll pairing status — returns approved + auto-connects on success."""
    mgr = _get_bridge(request)
    try:
        result = await mgr.poll_pairing()
        resp = {"status": result.status}
        if result.approved:
            resp["device_id"] = result.approved.device_id
        return resp
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Poll failed: {exc}")


@router.post("/connect")
async def cloud_connect(request: Request, body: CloudConnectRequest):
    """Manually connect to OllaBridge Cloud with existing credentials."""
    mgr = _get_bridge(request)
    try:
        await mgr.connect(body.cloud_url, body.device_token, body.device_id)
        return {"ok": True, "state": mgr.status.state.value}
    except Exception as exc:
        raise HTTPException(502, f"Connection failed: {exc}")


@router.post("/disconnect")
async def cloud_disconnect(request: Request):
    """Disconnect from OllaBridge Cloud (keeps saved credentials)."""
    mgr = _get_bridge(request)
    await mgr.disconnect()
    return {"ok": True, "state": "disconnected"}


@router.post("/unlink")
async def cloud_unlink(request: Request):
    """Disconnect and delete saved credentials."""
    mgr = _get_bridge(request)
    await mgr.unlink()
    return {"ok": True, "state": "disconnected", "credentials_deleted": True}
