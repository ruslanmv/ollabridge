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
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi import Body
from pydantic import BaseModel, Field

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


# ---------------------------------------------------------------------------
# HomePilot remote image generation — additive browser-facing transport.
# ---------------------------------------------------------------------------

_HOME_PILOT_PROBE_TIMEOUT_S = 8.0
_HOME_PILOT_GENERATE_TIMEOUT_S = 10 * 60.0
_MAX_REMOTE_IMAGE_BYTES = 20 * 1024 * 1024


class HomePilotGenerateRequest(BaseModel):
    """Stable browser-facing request shape for HomePilot Imagine mode."""

    model_config = {"populate_by_name": True, "extra": "ignore"}

    prompt: str = Field(..., min_length=1, max_length=4000)
    mode: str = Field(default="imagine", pattern="^imagine$")
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    aspect_ratio: str = Field(default="1:1", alias="aspectRatio", max_length=16)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    count: int = Field(default=1, ge=1, le=1)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _hp_enabled() -> bool:
    cfg = rts.get_all()
    if "homepilot_enabled" in cfg:
        return _truthy(cfg.get("homepilot_enabled"))
    return _truthy(settings.HOMEPILOT_ENABLED)


def _hp_headers(*, accept: str = "application/json", json_body: bool = False) -> dict[str, str]:
    headers = {"Accept": accept}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = str(_hp_api_key() or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    return headers


@router.get("/v1/media/homepilot/capability", dependencies=[Depends(require_api_key)])
async def homepilot_image_capability() -> dict[str, Any]:
    """Report whether configured HomePilot can accept Imagine requests."""
    if not _hp_enabled():
        return {
            "ok": True,
            "available": False,
            "enabled": False,
            "ready": False,
            "reason": "disabled",
            "device": "HomePilot",
        }

    base = _hp_base()
    if not base:
        return {
            "ok": True,
            "available": False,
            "enabled": True,
            "ready": False,
            "reason": "not-configured",
            "device": "HomePilot",
        }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_HOME_PILOT_PROBE_TIMEOUT_S),
            follow_redirects=True,
        ) as client:
            response = await client.get(f"{base}/health", headers=_hp_headers())
    except httpx.HTTPError as exc:
        log.info("HomePilot capability probe failed: %s", exc)
        return {
            "ok": True,
            "available": False,
            "enabled": True,
            "ready": False,
            "reason": "unreachable",
            "device": "HomePilot",
        }

    if response.status_code in (401, 403):
        reason = "unauthorized"
    elif response.status_code >= 400:
        reason = "upstream-error"
    else:
        reason = "ok"

    available = reason == "ok"
    return {
        "ok": True,
        "available": available,
        "enabled": True,
        "ready": available,
        "reason": reason,
        "device": "HomePilot",
    }


def _first_image_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    media = payload.get("media")
    if not isinstance(media, dict):
        return ""
    images = media.get("images")
    if not isinstance(images, list) or not images:
        return ""
    item = images[0]
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("url") or item.get("path") or item.get("href") or "").strip()
    return ""


def _generated_image_url(base: str, value: str) -> str:
    """Resolve a HomePilot-returned media location; never accepts browser input."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme:
        return raw if parsed.scheme in {"http", "https"} else ""
    return urljoin(f"{base.rstrip('/')}/", raw.lstrip("/"))


def _image_content_type(response: httpx.Response, source_url: str) -> str:
    content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("image/"):
        return content_type
    guessed = mimetypes.guess_type(urlparse(source_url).path)[0] or ""
    return guessed if guessed.startswith("image/") else ""


@router.post("/v1/media/homepilot/generate", dependencies=[Depends(require_api_key)])
async def homepilot_generate_image(
    body: HomePilotGenerateRequest = Body(...),
) -> Response:
    """Generate one image via HomePilot Imagine and return only the image bytes."""
    if not _hp_enabled():
        raise HTTPException(status_code=409, detail="HomePilot integration is disabled")

    base = _hp_base()
    if not base:
        raise HTTPException(status_code=503, detail="HomePilot base URL not configured")

    request_body: dict[str, Any] = {
        "message": f"imagine {body.prompt.strip()}",
        "mode": "imagine",
        "imgBatchSize": 1,
        "imgAspectRatio": body.aspect_ratio,
        "imgWidth": body.width,
        "imgHeight": body.height,
        "promptRefinement": True,
    }
    if body.seed is not None:
        request_body["imgSeed"] = body.seed

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_HOME_PILOT_GENERATE_TIMEOUT_S, connect=10.0),
            follow_redirects=True,
        ) as client:
            generated = await client.post(
                f"{base}/chat",
                json=request_body,
                headers={
                    **_hp_headers(json_body=True),
                    "X-Client-Type": "vr-chatbot",
                },
            )
            if generated.status_code in (401, 403):
                raise HTTPException(status_code=502, detail="HomePilot rejected its configured credential")
            if generated.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"HomePilot generation failed ({generated.status_code})",
                )

            try:
                payload = generated.json()
            except ValueError as exc:
                raise HTTPException(status_code=502, detail="HomePilot returned invalid generation JSON") from exc

            source = _first_image_url(payload)
            source_url = _generated_image_url(base, source)
            if not source_url:
                raise HTTPException(status_code=502, detail="HomePilot returned no generated image")

            image = await client.get(
                source_url,
                headers=_hp_headers(accept="image/*"),
            )
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="HomePilot image generation timed out") from exc
    except httpx.HTTPError as exc:
        log.warning("HomePilot image generation bridge failed: %s", exc)
        raise HTTPException(status_code=502, detail="HomePilot image generation is unreachable") from exc

    if image.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"HomePilot image fetch failed ({image.status_code})")

    media_type = _image_content_type(image, source_url)
    if not media_type:
        raise HTTPException(status_code=502, detail="HomePilot generated media was not an image")

    content = image.content
    if len(content) > _MAX_REMOTE_IMAGE_BYTES:
        raise HTTPException(status_code=502, detail="HomePilot generated image exceeded the bridge size limit")

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
