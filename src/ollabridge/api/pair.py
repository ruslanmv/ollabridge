from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ollabridge.core.settings import settings
from ollabridge.core.pairing import pairing


router = APIRouter()


class PairReq(BaseModel):
    code: str
    client_name: str | None = None


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    return host.startswith("127.") or host == "::1" or host == "localhost"


@router.get("/pair/info")
async def pair_info(request: Request):
    if settings.AUTH_MODE != "pairing":
        raise HTTPException(status_code=404, detail="pairing_not_enabled")

    if settings.PAIRING_LOCAL_ONLY and not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="pairing_local_only")

    info = pairing().get_pair_info() or pairing().reset_pair_code()
    return {
        "pairing": True,
        "auth_mode": settings.AUTH_MODE,
        "local_only": bool(settings.PAIRING_LOCAL_ONLY),
        "expires_in": info.expires_in,
    }


@router.post("/pair")
async def pair_exchange(req: PairReq, request: Request):
    if settings.AUTH_MODE != "pairing":
        raise HTTPException(status_code=404, detail="pairing_not_enabled")

    if settings.PAIRING_LOCAL_ONLY and not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="pairing_local_only")

    if not pairing().validate_pair_code(req.code):
        raise HTTPException(status_code=400, detail="invalid_pair_code")

    token = pairing().mint_token(client_name=req.client_name)
    return {"token": token, "token_type": "bearer"}
