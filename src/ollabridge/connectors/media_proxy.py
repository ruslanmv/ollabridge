"""Media proxy — serves HomePilot media through OllaBridge.

VR clients should not need to know HomePilot's internal file-serving
patterns (/files/..., /v1/assets/...).  This module provides a single
GET /v1/media/proxy/{path} route that forwards to the HomePilot backend.

No permanent media database.  Proxy or rewrite only.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ollabridge.core.settings import settings
from ollabridge.core.security import require_api_key
from ollabridge.core import runtime_settings as rts

log = logging.getLogger("ollabridge.media_proxy")

router = APIRouter(tags=["media-proxy"])


def _hp_base() -> str:
    cfg = rts.get_all()
    return (cfg.get("homepilot_base_url") or settings.HOMEPILOT_BASE_URL or "").rstrip("/")


def _hp_api_key() -> str:
    cfg = rts.get_all()
    return cfg.get("homepilot_api_key") or settings.HOMEPILOT_API_KEY or ""


def _try_api_key_or_token(
    request: Request,
    token: str | None = Query(default=None),
) -> str:
    """Allow auth via headers (standard) or ?token= query param (for <img> tags).

    Falls back to require_api_key for header-based auth.  If that fails but a
    valid ?token= query parameter is present, accept it instead.  This enables
    browser <img> tags to fetch proxied media without custom headers — essential
    for cloud deployments where loopback trust is unavailable.
    """
    # Try standard header-based auth first
    try:
        return require_api_key(
            request,
            x_api_key=request.headers.get("x-api-key"),
            authorization=request.headers.get("authorization"),
        )
    except HTTPException:
        pass

    # Fallback: ?token= query parameter (validated as API key or pairing token)
    if token:
        from ollabridge.core.security import _keys, _pairing_manager
        token = token.strip()
        if token in _keys():
            return token
        if _pairing_manager and _pairing_manager.validate_token(token):
            return token

    raise HTTPException(status_code=401, detail="Invalid or missing API key / token")


@router.get("/v1/media/proxy/{path:path}")
async def media_proxy(
    path: str,
    request: Request,
    _key: str = Depends(_try_api_key_or_token),
) -> Response:
    """Proxy a HomePilot media file to the VR client.

    Accepts paths like:
        /v1/media/proxy/files/projects/.../image.png
        /v1/media/proxy/v1/assets/.../image.png

    Forwards to HomePilot as:
        {hp_base}/{path}

    Auth: header-based (X-API-Key / Bearer) or ?token= query parameter.
    """
    base = _hp_base()
    if not base:
        raise HTTPException(502, "HomePilot base URL not configured")

    # Security: reject path traversal
    if ".." in path:
        raise HTTPException(400, "Invalid path")

    upstream_url = f"{base}/{path}"
    headers = {}
    api_key = _hp_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    # Forward HomePilot auth as ?token= query param too (for file endpoints
    # that support query-param auth, e.g. HomePilot /files/ for <img> tags).
    params = {}
    if api_key:
        params["token"] = api_key

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(upstream_url, headers=headers, params=params)
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, f"Upstream returned {resp.status_code}")

            content_type = resp.headers.get("content-type", "")
            if not content_type:
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"

            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "private, max-age=3600, immutable",
                },
            )
    except httpx.HTTPError as e:
        log.warning("Media proxy error for %s: %s", path, e)
        raise HTTPException(502, f"Failed to fetch media: {e}")


def rewrite_attachment_urls(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite HomePilot attachment URLs to OllaBridge proxy URLs.

    Transforms /files/... or full http://.../ URLs to /v1/media/proxy/files/...
    so VR clients fetch through OllaBridge instead of hitting HomePilot directly.
    """
    result = []
    base = _hp_base()

    for att in attachments:
        att = dict(att)  # shallow copy
        url = att.get("url", "")

        # Strip HomePilot base URL prefix if present
        if base and url.startswith(base):
            url = url[len(base):]

        # Convert to proxy path
        if url.startswith("/"):
            url = url.lstrip("/")
        att["url"] = f"/v1/media/proxy/{url}"
        att["delivery"] = "url"

        result.append(att)

    return result
