from __future__ import annotations

import random

from fastapi import Header, HTTPException, Request
from ollabridge.core.settings import settings


# ---------------------------------------------------------------------------
# Module-level reference to PairingManager (set at startup when mode=pairing)
# ---------------------------------------------------------------------------
_pairing_manager = None


def set_pairing_manager(mgr) -> None:
    """Called once at startup to wire in the PairingManager instance."""
    global _pairing_manager
    _pairing_manager = mgr


def _keys() -> set[str]:
    return {k.strip() for k in (settings.API_KEYS or "").split(",") if k.strip()}


def generate_pairing_code() -> str:
    """Generate a short human-readable pairing code like '421-087'."""
    left = random.randint(100, 999)
    right = random.randint(0, 999)
    return f"{left}-{right:03d}"


def _extract_bearer(authorization: str | None) -> str | None:
    """Extract token from Authorization: Bearer <token>."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _is_loopback(request: Request) -> bool:
    """Check if the request comes from a loopback address."""
    if request.client is None:
        return False
    host = request.client.host
    return host in ("127.0.0.1", "::1", "localhost")


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Mode-aware authentication dependency.

    AUTH_MODE behaviour:
      required    – static API keys via X-API-Key or Bearer (default)
      local-trust – skip auth for loopback clients; require key for remote
      pairing     – accept paired-device tokens OR static keys
    """
    mode = (settings.AUTH_MODE or "required").lower().strip()

    # ── local-trust: loopback clients bypass auth ──────────────────────
    if mode == "local-trust" and _is_loopback(request):
        return "__local_trust__"

    # ── Extract candidate key from headers ─────────────────────────────
    key = None
    if x_api_key:
        key = x_api_key.strip()
    else:
        key = _extract_bearer(authorization)

    # ── pairing mode: accept paired tokens AND static keys ─────────────
    if mode == "pairing":
        # Try static keys first (admin always works)
        if key and key in _keys():
            return key
        # Try paired-device token
        if key and _pairing_manager and _pairing_manager.validate_token(key):
            return key
        # Loopback fallback for pairing mode too
        if _is_loopback(request):
            return "__local_trust__"
        raise HTTPException(status_code=401, detail="Invalid or missing API key / pairing token")

    # ── required mode (default) ────────────────────────────────────────
    if not key or key not in _keys():
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key
