"""Push the gateway's provider preferences to OllaBridge Cloud.

Sends a sanitised snapshot — provider configs, alias map, HF connection
metadata — over the existing cloud relay credentials (device_token).

What is NEVER sent:
  - HF tokens (or any other secret).
  - The user's API keys.
  - Request / response bodies.

Cloud uses the snapshot for two things:
  1. Display the device's current routing setup in the admin UI.
  2. Fall-over: when a device is offline, cloud can route the alias to
     the same intent bucket using its own catalog.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


PREFS_ENDPOINT = "/api/devices/me/preferences"


def build_payload(
    *,
    device_id: str,
    providers: list[Any],
    aliases: dict[str, list[Any]],
    hf_status: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the cloud sync payload — secrets-free by construction.

    ``providers`` is the raw list from ``ProviderRegistry.list_providers()``
    (we strip internal-only fields). ``aliases`` is the alias resolution
    map. ``hf_status`` is the HF status block from
    ``/admin/providers/huggingface/status``."""
    safe_providers = []
    for cfg in providers:
        # Pydantic models from ProviderRegistry; tolerate plain dicts too.
        cfg_dict = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)
        safe_providers.append({
            "id": cfg_dict.get("id"),
            "name": cfg_dict.get("name"),
            "kind": cfg_dict.get("kind"),
            "enabled": cfg_dict.get("enabled"),
            "tier": cfg_dict.get("tier"),
            "category": cfg_dict.get("category"),
            "tags": cfg_dict.get("tags", []),
        })

    safe_aliases: dict[str, list[dict[str, str]]] = {}
    for name, candidates in aliases.items():
        out = []
        for c in candidates:
            c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
            out.append({
                "provider": c_dict.get("provider"),
                "model": c_dict.get("model"),
            })
        safe_aliases[name] = out

    safe_hf = None
    if hf_status:
        safe_hf = {
            "connected": bool(hf_status.get("connected")),
            "mode": hf_status.get("mode") or "free_credit_only",
            "bill_to": hf_status.get("bill_to"),
            "encrypted_at_rest": bool(hf_status.get("encrypted_at_rest")),
            "catalog_entries": (hf_status.get("catalog") or {}).get("entries", 0),
            "token_synced": False,  # always false — the gateway never ships secrets
        }

    return {
        "device_id": device_id,
        "synced_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "schema_version": 1,
        "providers": safe_providers,
        "aliases": safe_aliases,
        "hf_status": safe_hf,
    }


async def push_to_cloud(
    *,
    cloud_url: str,
    device_token: str,
    payload: dict[str, Any],
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST the payload to the cloud preferences endpoint.

    Returns ``{"ok": True, "stored_at": "..."}`` on success. Raises
    ``RuntimeError`` with a clean message on any failure — the caller
    decides whether to surface it or store-and-retry."""
    if not cloud_url:
        raise RuntimeError("cloud not connected: no cloud_url")
    if not device_token:
        raise RuntimeError("cloud not connected: no device_token")

    url = f"{cloud_url.rstrip('/')}{PREFS_ENDPOINT}"
    headers = {
        "Authorization": f"Bearer {device_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"timeout pushing preferences: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"transport error pushing preferences: {exc}") from exc

    if response.status_code >= 400:
        snippet = response.text[:200] if response.text else ""
        raise RuntimeError(
            f"cloud rejected preferences ({response.status_code}): {snippet}"
        )
    try:
        return response.json()
    except ValueError:
        return {"ok": True, "raw": response.text[:200]}
