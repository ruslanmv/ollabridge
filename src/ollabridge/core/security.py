from __future__ import annotations

from fastapi import Header, HTTPException
from ollabridge.core.settings import settings


def _keys() -> set[str]:
    return {k.strip() for k in (settings.API_KEYS or "").split(",") if k.strip()}


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Accepts either:
    - X-API-Key: <key>
    - Authorization: Bearer <key>

    Returns the validated key string.
    """
    key = None
    if x_api_key:
        key = x_api_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        key = authorization.split(" ", 1)[1].strip()

    if not key or key not in _keys():
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key
