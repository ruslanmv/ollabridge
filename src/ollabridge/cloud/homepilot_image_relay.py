"""Cloud-relay adapter for HomePilot image generation.

This module intentionally talks to the local OllaBridge HTTP gateway instead of
re-implementing HomePilot's Imagine protocol.  The gateway endpoints are the
same ones used by a directly connected 3D Avatar browser, so local and Cloud
paths share validation, HomePilot credentials, response limits, and behavior.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

RELAY_CAPABILITY = "homepilot.image"
CAPABILITY_OP = "homepilot.image.capability"
GENERATE_OP = "homepilot.image.generate"
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _gateway() -> tuple[str, dict[str, str]]:
    from ollabridge.core.settings import settings

    base = f"http://127.0.0.1:{settings.PORT}"
    headers: dict[str, str] = {}
    keys = [key.strip() for key in settings.API_KEYS.split(",") if key.strip()]
    if keys:
        headers["X-API-Key"] = keys[0]
    return base, headers


async def capability() -> dict[str, Any]:
    """Return the local HomePilot image capability response verbatim."""
    base, headers = _gateway()
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{base}/v1/media/homepilot/capability",
            headers={**headers, "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return (
            data
            if isinstance(data, dict)
            else {"available": False, "reason": "invalid-response"}
        )


async def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate through the local gateway and return relay-safe base64 bytes."""
    base, headers = _gateway()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10 * 60.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        response = await client.post(
            f"{base}/v1/media/homepilot/generate",
            json=payload,
            headers={
                **headers,
                "Accept": "image/*",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()

    content = response.content
    if len(content) > _MAX_IMAGE_BYTES:
        raise ValueError("HomePilot generated image exceeded the relay size limit")

    content_type = str(response.headers.get("content-type") or "image/png")
    content_type = content_type.split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        raise ValueError("HomePilot generation endpoint returned non-image media")

    return {
        "content": base64.b64encode(content).decode("ascii"),
        "mime_type": content_type,
        "size_bytes": len(content),
        "sha256": response.headers.get("x-content-sha256", ""),
    }
