"""Admin REST API for the multi-provider router.

Endpoints
---------

``GET  /admin/providers``                 — every provider with config + state
``GET  /admin/providers/aliases``         — current alias resolution map
``POST /admin/providers/{id}/enable``     — flip a provider on
``POST /admin/providers/{id}/disable``    — flip a provider off
``POST /admin/providers/test``            — end-to-end test of model/alias

Hugging Face specific
~~~~~~~~~~~~~~~~~~~~~

``POST /admin/providers/huggingface/connect``     — store HF token (encrypted)
``POST /admin/providers/huggingface/disconnect``  — wipe stored HF token
``GET  /admin/providers/huggingface/status``      — connection + last sync info
``POST /admin/providers/huggingface/refresh``     — trigger catalog sync
``GET  /admin/providers/huggingface/models``      — paginated catalog query
``GET  /admin/providers/huggingface/recommendations``
                                                  — top-N per capability bucket

All endpoints sit under :func:`require_api_key` so they share the
gateway's existing pairing-aware auth.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ollabridge.addons.providers.errors import ProviderError
from ollabridge.addons.providers.hf_catalog.schemas import (
    ScoringProfile,
)
from ollabridge.core.security import require_api_key

logger = logging.getLogger("ollabridge.providers_routes")


router = APIRouter(prefix="/admin/providers", tags=["providers"])


# ── Request / response bodies ──────────────────────────────


class HuggingFaceConnectRequest(BaseModel):
    token: str = Field(..., min_length=4, description="HF access token (hf_...)")
    bill_to: Optional[str] = Field(
        default=None, description="HF org slug to bill against (X-HF-Bill-To)"
    )
    mode: str = Field(
        default="free_credit_only",
        description="free_credit_only | allow_paid | provider_keys",
    )


class ProviderTestRequest(BaseModel):
    model: str = Field(..., description="Concrete model id or alias to test")
    prompt: str = Field(default="ping", max_length=200)
    max_tokens: int = Field(default=8, ge=1, le=64)


class RefreshRequest(BaseModel):
    limit: int = Field(default=100, ge=10, le=500)
    profile: ScoringProfile = ScoringProfile.FREE_LAB


# ── Helpers ────────────────────────────────────────────────


def _registry(request: Request):
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:
        raise HTTPException(status_code=503, detail="provider registry not initialised")
    return reg


def _provider_router(request: Request):
    prouter = getattr(request.app.state, "provider_router", None)
    if prouter is None:
        raise HTTPException(status_code=503, detail="provider router not initialised")
    return prouter


def _secret_store(request: Request):
    store = getattr(request.app.state, "secret_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="secret store not initialised")
    return store


def _hf_components(request: Request):
    snapshot = getattr(request.app.state, "hf_catalog_snapshot", None)
    sync = getattr(request.app.state, "hf_catalog_sync", None)
    if snapshot is None or sync is None:
        raise HTTPException(status_code=503, detail="HF catalog not initialised")
    return snapshot, sync


def _provider_summary(config, state) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "kind": config.kind,
        "enabled": config.enabled,
        "tier": config.tier.value,
        "category": config.category.value,
        "priority": config.priority,
        "weight": config.weight,
        "base_url": config.base_url,
        "credential_env": config.credential_env,
        "tags": list(config.tags),
        "notes": config.notes,
        "state": {
            "health": state.health.value,
            "avg_latency_ms": round(state.avg_latency_ms, 1),
            "request_count": state.request_count,
            "token_count": state.token_count,
            "consecutive_failures": state.consecutive_failures,
            "monthly_tokens_used": state.monthly_tokens_used,
            "monthly_requests_used": state.monthly_requests_used,
            "is_quota_exhausted": state.is_quota_exhausted,
            "last_error": state.last_error,
        } if state else None,
    }


# ── Generic provider endpoints ─────────────────────────────


@router.get("", dependencies=[Depends(require_api_key)])
async def list_providers(request: Request) -> dict[str, Any]:
    registry = _registry(request)
    items = []
    for config in registry.list_providers():
        state = registry.get_state(config.id)
        items.append(_provider_summary(config, state))
    return {
        "providers": items,
        "total": len(items),
        "enabled": registry.enabled_count,
    }


@router.get("/aliases", dependencies=[Depends(require_api_key)])
async def list_aliases(request: Request) -> dict[str, Any]:
    registry = _registry(request)
    aliases = {
        name: [{"provider": c.provider, "model": c.model} for c in cands]
        for name, cands in registry.aliases.items()
    }
    return {"aliases": aliases, "total": len(aliases)}


@router.get("/{provider_id}", dependencies=[Depends(require_api_key)])
async def get_provider(provider_id: str, request: Request) -> dict[str, Any]:
    registry = _registry(request)
    config = registry.get_config(provider_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"provider '{provider_id}' not found")
    state = registry.get_state(provider_id)
    return _provider_summary(config, state)


@router.post("/{provider_id}/enable", dependencies=[Depends(require_api_key)])
async def enable_provider(provider_id: str, request: Request) -> dict[str, Any]:
    registry = _registry(request)
    config = registry.get_config(provider_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"provider '{provider_id}' not found")
    config.enabled = True
    return {"ok": True, "provider": provider_id, "enabled": True}


@router.post("/{provider_id}/disable", dependencies=[Depends(require_api_key)])
async def disable_provider(provider_id: str, request: Request) -> dict[str, Any]:
    registry = _registry(request)
    config = registry.get_config(provider_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"provider '{provider_id}' not found")
    config.enabled = False
    return {"ok": True, "provider": provider_id, "enabled": False}


@router.post("/test", dependencies=[Depends(require_api_key)])
async def test_provider_route(
    request: Request,
    body: ProviderTestRequest = Body(...),
) -> dict[str, Any]:
    """Send a tiny prompt through the router for the given model/alias.

    Returns the OpenAI-compatible response plus the route chosen, so the
    UI can confirm which upstream actually answered.
    """
    prouter = _provider_router(request)
    candidates = prouter.resolve(body.model)
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"no provider can serve model/alias '{body.model}'",
        )
    chosen = candidates[0]
    try:
        result = await prouter.route_chat(
            body.model,
            [{"role": "user", "content": body.prompt}],
            max_tokens=body.max_tokens,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "ok": True,
        "chose": {
            "provider_id": chosen.provider_id,
            "model": chosen.model,
            "score": round(chosen.score, 4),
            "reason": chosen.reason,
        },
        "response": result,
    }


# ── Hugging Face specific ──────────────────────────────────


@router.post("/huggingface/connect", dependencies=[Depends(require_api_key)])
async def hf_connect(
    request: Request,
    body: HuggingFaceConnectRequest = Body(...),
) -> dict[str, Any]:
    """Persist the HF token (encrypted) and hot-swap it into the running adapter."""
    store = _secret_store(request)
    store.set("huggingface", body.token)
    if body.bill_to:
        store.set("huggingface_bill_to", body.bill_to)
    else:
        store.delete("huggingface_bill_to")
    store.set("huggingface_mode", body.mode)

    # Hot-swap into the running HF adapter without restart.
    registry = _registry(request)
    adapter = registry.get_adapter("huggingface-free")
    if adapter is not None:
        adapter.api_key = body.token
        # bill_to is HF adapter-specific; set defensively.
        if hasattr(adapter, "bill_to"):
            adapter.bill_to = body.bill_to

    return {
        "ok": True,
        "connected": True,
        "bill_to": body.bill_to,
        "mode": body.mode,
        "encrypted": store.is_encrypted,
    }


@router.post("/huggingface/disconnect", dependencies=[Depends(require_api_key)])
async def hf_disconnect(request: Request) -> dict[str, Any]:
    store = _secret_store(request)
    store.delete("huggingface")
    store.delete("huggingface_bill_to")
    store.delete("huggingface_mode")

    registry = _registry(request)
    adapter = registry.get_adapter("huggingface-free")
    if adapter is not None:
        adapter.api_key = None
        if hasattr(adapter, "bill_to"):
            adapter.bill_to = None

    return {"ok": True, "connected": False}


@router.get("/huggingface/status", dependencies=[Depends(require_api_key)])
async def hf_status(request: Request) -> dict[str, Any]:
    store = _secret_store(request)
    snapshot, sync = _hf_components(request)
    last = sync.last_result
    return {
        "connected": store.has("huggingface"),
        "bill_to": store.get("huggingface_bill_to"),
        "mode": store.get("huggingface_mode") or "free_credit_only",
        "encrypted_at_rest": store.is_encrypted,
        "catalog": {
            "entries": snapshot.entry_count,
            "last_sync": (
                {
                    "started_at": last.started_at.isoformat(),
                    "finished_at": last.finished_at.isoformat(),
                    "duration_s": last.duration_s,
                    "ok": last.ok,
                    "fetched": last.fetched,
                    "upserted": last.upserted,
                    "marked_stale": last.marked_stale,
                    "aliases_written": last.aliases_written,
                    "error": last.error,
                }
                if last else None
            ),
        },
    }


@router.post("/huggingface/refresh", dependencies=[Depends(require_api_key)])
async def hf_refresh(
    request: Request,
    body: RefreshRequest = Body(default_factory=RefreshRequest),
) -> dict[str, Any]:
    _, sync = _hf_components(request)
    # Use the user's token if connected; refresh works anonymously too.
    store = _secret_store(request)
    token = store.get("huggingface")
    if token and hasattr(sync.client, "token"):
        sync.client.token = token

    result = await sync.run(limit=body.limit, profile=body.profile)
    return {
        "ok": result.ok,
        "duration_s": result.duration_s,
        "fetched": result.fetched,
        "upserted": result.upserted,
        "marked_stale": result.marked_stale,
        "aliases_written": result.aliases_written,
        "error": result.error,
    }


@router.get("/huggingface/models", dependencies=[Depends(require_api_key)])
async def hf_models(
    request: Request,
    task: str | None = Query(default=None, description="chat-completion | vlm | image-generation | video-generation"),
    supports_tools: bool | None = Query(default=None),
    supports_structured_output: bool | None = Query(default=None),
    free_credit_only: bool = Query(default=False),
    max_price_per_1m: float | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    snapshot, _ = _hf_components(request)
    rows = snapshot.filter(
        task=task,
        supports_tools=supports_tools,
        supports_structured_output=supports_structured_output,
        free_credit_only=free_credit_only,
        max_price_per_1m=max_price_per_1m,
    )
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "models": [r.model_dump(mode="json") for r in page],
    }


@router.get("/huggingface/recommendations", dependencies=[Depends(require_api_key)])
async def hf_recommendations(request: Request, n: int = Query(default=3, ge=1, le=10)) -> dict[str, Any]:
    """Top-N entries per capability bucket — drives the Discover UI."""
    snapshot, _ = _hf_components(request)
    from ollabridge.addons.providers.hf_catalog.alias_writer import build_managed_aliases

    managed = build_managed_aliases(snapshot.list_entries())
    # Cap each bucket to ``n`` for the UI.
    capped = {alias: candidates[:n] for alias, candidates in managed.items()}
    return {"buckets": capped, "total_buckets": len(capped)}


# ── Cloud preferences sync ────────────────────────────────


@router.post("/sync-to-cloud", dependencies=[Depends(require_api_key)])
async def sync_to_cloud(request: Request) -> dict[str, Any]:
    """Push a (secrets-free) snapshot of provider preferences to OllaBridge Cloud.

    Requires the gateway to already be paired with cloud (see
    /admin/cloud/pair/start). Returns the cloud's acknowledgement plus
    the snapshot that was sent, so the caller can verify nothing
    sensitive leaked."""
    from ollabridge.cloud.preferences_sync import build_payload, push_to_cloud

    registry = _registry(request)
    bridge = getattr(request.app.state, "cloud_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="cloud bridge not initialised")

    creds = getattr(bridge, "_creds", None)
    cloud_url = getattr(creds, "cloud_url", "") if creds else ""
    device_token = getattr(creds, "device_token", "") if creds else ""
    device_id = getattr(creds, "device_id", "") if creds else ""
    if not (cloud_url and device_token):
        raise HTTPException(
            status_code=409,
            detail="gateway is not paired with OllaBridge Cloud — pair first via /admin/cloud/pair/start",
        )

    snapshot, _ = (None, None)
    try:
        snapshot, _ = _hf_components(request)
    except HTTPException:
        pass  # HF catalog optional — preferences sync still works without it.

    hf_status_payload: dict[str, Any] | None = None
    secret_store = getattr(request.app.state, "secret_store", None)
    if snapshot is not None:
        hf_status_payload = {
            "connected": bool(secret_store and secret_store.has("huggingface")),
            "mode": secret_store.get("huggingface_mode") if secret_store else None,
            "bill_to": secret_store.get("huggingface_bill_to") if secret_store else None,
            "encrypted_at_rest": bool(secret_store and secret_store.is_encrypted),
            "catalog": {"entries": snapshot.entry_count},
        }

    payload = build_payload(
        device_id=device_id,
        providers=registry.list_providers(),
        aliases=registry.aliases,
        hf_status=hf_status_payload,
    )

    try:
        ack = await push_to_cloud(
            cloud_url=cloud_url, device_token=device_token, payload=payload,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"ok": True, "cloud_ack": ack, "payload": payload}
