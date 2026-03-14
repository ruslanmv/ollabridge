"""Pairing API endpoints for OllaBridge device-pairing auth mode.

Endpoints:
  GET  /pair/info     – Public: returns pairing status and auth mode
  POST /pair/generate – Generate a new pairing code (admin)
  POST /pair          – Exchange a pairing code for a persistent bearer token
  GET  /pair/devices  – List paired devices (requires auth)
  POST /pair/revoke   – Revoke a paired device (requires auth)
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.core.pairing import PairingManager
from ollabridge.core.settings import settings


router = APIRouter(prefix="/pair", tags=["pairing"])


class PairRequest(BaseModel):
    code: str = Field(..., description="The pairing code displayed in the gateway console")
    label: str = Field("device", description="Friendly name for this device")


class PairResponse(BaseModel):
    ok: bool
    device_id: str = ""
    token: str = ""


class RevokeRequest(BaseModel):
    device_id: str


def _get_manager(request: Request) -> PairingManager:
    """Retrieve the PairingManager from app state — auto-create if needed."""
    mgr = getattr(request.app.state, "pairing_manager", None)
    if mgr is None:
        # Lazily create a PairingManager even if AUTH_MODE != pairing.
        # This allows the UI to generate codes and manage devices regardless.
        from ollabridge.core.security import set_pairing_manager
        mgr = PairingManager()
        request.app.state.pairing_manager = mgr
        set_pairing_manager(mgr)
    return mgr


def _format_code(code: str) -> str:
    """Format a numeric code with hyphens for readability (e.g. 421087 -> 421-087)."""
    mid = len(code) // 2
    return f"{code[:mid]}-{code[mid:]}" if len(code) >= 4 else code


@router.get("/info")
async def pair_info(request: Request):
    """Public endpoint: check pairing status and auth mode."""
    auth_mode = (settings.AUTH_MODE or "required").lower().strip()
    mgr = getattr(request.app.state, "pairing_manager", None)

    result: dict = {
        "auth_mode": auth_mode,
        "pairing_enabled": auth_mode == "pairing",
        "code_length": settings.PAIRING_CODE_LENGTH,
        "code_ttl": settings.PAIRING_CODE_TTL_SECONDS,
    }

    if mgr is None:
        result["pairing_available"] = False
        result["message"] = (
            "Pairing mode is not active. Current auth mode: "
            + auth_mode
        )
        result["device_count"] = 0
        return result

    code = mgr.current_code
    result["device_count"] = len(mgr.list_devices())
    if code is None:
        result["pairing_available"] = False
        result["message"] = "No active pairing code. Click 'Generate Code' to create one."
    else:
        remaining = max(0, int(code.created_at + code.ttl - time.time()))
        result["pairing_available"] = True
        result["ttl_remaining"] = remaining
        result["code_display"] = _format_code(code.code)

    return result


@router.post("/generate")
async def pair_generate(request: Request):
    """Generate a new pairing code (for admin use from UI or CLI)."""
    mgr = _get_manager(request)
    pc = mgr.generate_code()
    return {
        "ok": True,
        "code": pc.code,
        "code_display": _format_code(pc.code),
        "ttl": pc.ttl,
        "expires_in": pc.ttl,
    }


@router.post("", response_model=PairResponse)
async def pair_exchange(body: PairRequest, request: Request):
    """Exchange a valid pairing code for a persistent bearer token."""
    mgr = _get_manager(request)
    # Strip hyphens from formatted codes (e.g. "421-087" -> "421087")
    clean_code = body.code.replace("-", "").strip()
    raw_token = mgr.exchange(clean_code, body.label)
    if raw_token is None:
        raise HTTPException(401, "Invalid or expired pairing code")
    # Find the device_id that was just created
    devices = mgr.list_devices()
    device_id = devices[-1]["device_id"] if devices else ""

    # Auto-create a consumer node for the paired device
    consumers = getattr(request.app.state, "obridge", None)
    if consumers is not None:
        consumers = getattr(consumers, "consumers", None)
    if consumers is not None:
        try:
            consumers.ensure_from_pair(device_id, body.label)
        except Exception:
            pass  # non-critical — don't block pairing

    return PairResponse(ok=True, device_id=device_id, token=raw_token)


@router.get("/devices")
async def list_devices(request: Request):
    """List all paired devices (no secrets exposed)."""
    mgr = _get_manager(request)
    return {"devices": mgr.list_devices()}


@router.post("/revoke")
async def revoke_device(body: RevokeRequest, request: Request):
    """Revoke a paired device's access."""
    mgr = _get_manager(request)
    ok = mgr.revoke(body.device_id)
    if not ok:
        raise HTTPException(404, f"Device '{body.device_id}' not found")
    return {"ok": True, "revoked": body.device_id}
