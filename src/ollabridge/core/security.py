from __future__ import annotations

from fastapi import Header, HTTPException, Request

from ollabridge.core.settings import settings
from ollabridge.core.pairing import pairing


def _keys() -> set[str]:
    return {k.strip() for k in (settings.API_KEYS or "").split(",") if k.strip()}


def _extract_token(
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host.startswith("127.") or host == "::1" or host == "localhost"


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    """Accepts either:
    - X-API-Key: <key>
    - Authorization: Bearer <key>

    Returns the validated key string.
    """
    mode = (settings.AUTH_MODE or "required").strip().lower()
    token = _extract_token(x_api_key, authorization)

    client_host = request.client.host if request.client else None
    is_local = _is_loopback(client_host)

    if mode == "local-trust":
        if is_local:
            return token or "local"
        if not token or token not in _keys():
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return token

    if mode == "pairing":
        if not token or not pairing().token_valid(token):
            raise HTTPException(status_code=401, detail="Invalid or missing pairing token")
        return token

    # default: required
    if not token or token not in _keys():
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return token
