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

import logging

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

log = logging.getLogger("ollabridge.model_access")

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


def _homepilot_models() -> list[str]:
    """HomePilot persona/personality model ids, when the HomePilot source is
    enabled. Sync + best-effort, mirroring ``_local_ollama_models`` so the
    manifest pipeline can see personas (previously only Ollama was enumerated,
    so personas were never offered to the cloud manifest at all)."""
    from ollabridge.core import runtime_settings as rts

    if not rts.get("homepilot_enabled", getattr(settings, "HOMEPILOT_ENABLED", False)):
        return []
    base = (rts.get("homepilot_base_url", settings.HOMEPILOT_BASE_URL) or "").rstrip("/")
    if not base:
        return []
    api_key = rts.get("homepilot_api_key", settings.HOMEPILOT_API_KEY) or ""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    try:
        r = httpx.get(f"{base}/v1/models", headers=headers, timeout=3)
        if r.status_code == 200:
            data = r.json()
            return [
                str(m.get("id"))
                for m in data.get("data", [])
                if isinstance(m, dict) and m.get("id")
            ]
    except Exception:
        pass
    return []


def _external_source_models() -> list[tuple[str, str, str]]:
    """(source_id, label, model_id) for each connected external source.

    A source contributes the model it is actually configured to serve — the
    one the Sources card shows under its name — plus any other model the user
    has already made an explicit access decision about. Enumerating a
    provider's whole catalog here would mean a network round trip per source
    on every manifest build, to publish hundreds of models the user never
    chose; the selected model is the one they did choose.

    Reads ``providers.yaml`` only. Metadata, no secrets, no network.
    """
    from ollabridge.providers_meta import PROVIDER_CATALOG, load_providers

    decided: dict[str, set[str]] = {}
    for rec in ma.load_all().values():
        decided.setdefault(rec.source_id, set()).add(rec.model_id)

    inv: list[tuple[str, str, str]] = []
    for rec in load_providers():
        if not rec.enabled:
            continue
        spec = PROVIDER_CATALOG.get(rec.kind or rec.name)
        label = rec.display_name or (spec.label if spec else rec.name)
        seen: set[str] = set()
        for mid in [rec.default_model, *sorted(decided.get(rec.name, ()))]:
            mid = (mid or "").strip()
            if mid and mid not in seen:
                seen.add(mid)
                inv.append((rec.name, label, mid))
    return inv


def _inventory() -> list[tuple[str, str, str]]:
    """(source_id, source_label, model_id) across every configured source.

    Local Ollama and HomePilot are enumerated live; external accounts
    contribute the model each is configured to serve. Without the external
    half, a Groq or watsonx source could read "Connected · Routing on" in the
    UI while being invisible to Models & Access and absent from everything
    published to OllaBridge Cloud.
    """
    inv: list[tuple[str, str, str]] = []
    for mid in _local_ollama_models():
        inv.append(("ollama", "Ollama on this PC", mid))
    for mid in _homepilot_models():
        inv.append(("homepilot", "HomePilot personas", mid))
    inv.extend(_external_source_models())
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
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """Update one model's access flags. Unspecified flags are unchanged.

    When a change could affect what the cloud publishes (enabled /
    visible_cloud / allowed_apps / allow_routing), ask the cloud bridge to
    re-publish its approved manifest immediately so the OllaBridge Cloud
    model selector reflects the change within seconds.
    """
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

    cloud_relevant = any(
        v is not None
        for v in (
            body.enabled,
            body.visible_cloud,
            body.allowed_apps,
            body.allow_routing,
        )
    )
    if cloud_relevant:
        bridge = getattr(request.app.state, "cloud_bridge", None)
        if bridge is not None and hasattr(bridge, "refresh_models_now"):
            try:
                await bridge.refresh_models_now()
            except Exception as exc:  # noqa: BLE001
                log.warning("cloud manifest refresh after access change failed: %s", exc)

    return rec.model_dump()


@router.get("/manifest/cloud")
async def cloud_manifest(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """The filtered manifest published to OllaBridge Cloud (visible_cloud only)."""
    manifest = ma.cloud_manifest(_inventory())
    return {"models": manifest, "count": len(manifest)}
