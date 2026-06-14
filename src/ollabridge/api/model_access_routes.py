"""``/admin/model-access/*`` — per-model access controls (the "Models & Access"
tab backend).

Separates *which models are visible where* from *which sources are configured*
(see docs/UX_SOURCES_MODEL.md). Reads the live model inventory, joins it with
the persisted access flags, and lets the UI toggle visibility (this PC / LAN /
cloud), per-app allow-lists, and the routing opt-in per model.

Metadata only — no secret ever touches these endpoints.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ollabridge.core.security import require_api_key
from ollabridge.core.settings import settings
from ollabridge import model_access as ma

router = APIRouter(prefix="/admin/model-access", tags=["model-access"])


class AccessPatch(BaseModel):
    enabled: Optional[bool] = None
    visible_local: Optional[bool] = None
    visible_lan: Optional[bool] = None
    visible_cloud: Optional[bool] = None
    allowed_apps: Optional[list[str]] = None
    allowed_workspace: Optional[bool] = None
    allow_routing: Optional[bool] = None


def _local_ollama_models() -> list[str]:
    try:
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            return [
                m.get("name", "") for m in r.json().get("models", []) if m.get("name")
            ]
    except Exception:
        pass
    return []


def _inventory() -> list[tuple[str, str, str]]:
    """(source_id, source_label, model_id) across local Ollama + configured sources.

    Concrete model lists are only available for local Ollama today; external
    sources expose their models after a catalog sync (out of scope here), so
    they appear as a source row the UI can drill into.
    """
    inv: list[tuple[str, str, str]] = []
    for mid in _local_ollama_models():
        inv.append(("ollama", "Ollama on this PC", mid))
    return inv


@router.get("")
async def list_access(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """Model inventory joined with access flags, grouped by source."""
    grouped: dict[str, dict[str, Any]] = {}
    for source_id, source_label, model_id in _inventory():
        rec = ma.get(source_id, model_id)
        grouped.setdefault(
            source_id,
            {"source_id": source_id, "source_label": source_label, "models": []},
        )
        grouped[source_id]["models"].append(rec.model_dump())
    return {"sources": list(grouped.values())}


@router.post("/{source_id}/{model_id:path}")
async def set_access(
    source_id: str,
    model_id: str,
    body: AccessPatch,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """Update one model's access flags. Unspecified flags are unchanged."""
    rec = ma.set_access(
        source_id,
        model_id,
        enabled=body.enabled,
        visible_local=body.visible_local,
        visible_lan=body.visible_lan,
        visible_cloud=body.visible_cloud,
        allowed_apps=body.allowed_apps,
        allowed_workspace=body.allowed_workspace,
        allow_routing=body.allow_routing,
    )
    return rec.model_dump()


@router.get("/manifest/cloud")
async def cloud_manifest(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """The filtered manifest published to OllaBridge Cloud (visible_cloud only)."""
    manifest = ma.cloud_manifest(_inventory())
    return {"models": manifest, "count": len(manifest)}
