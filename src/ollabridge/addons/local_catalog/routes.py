"""
``/local/*`` REST routes for the local model fleet.

Two route groups:

- ``/local/runtime/...``  — node info, ping, pairing surface
- ``/local/models/...``   — catalog CRUD, sync, test, pull

All endpoints sit under the existing ``require_api_key`` dependency. The
local app exposes these on ``http://localhost:11435`` and the cloud
heartbeat consumes them to render the unified "Local Providers" section in
the cloud Admin.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.addons.local_catalog.client import LocalRuntimeClient
from ollabridge.addons.local_catalog.health import LocalModelHealthChecker
from ollabridge.addons.local_catalog.pulls import LocalPullManager
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.schemas import LocalModel, LocalSetupStatus
from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService
from ollabridge.core.security import require_api_key
from ollabridge.core.settings import settings

logger = logging.getLogger("ollabridge.local_catalog")


router = APIRouter(prefix="/local", tags=["local-catalog"])


# ── Pydantic request bodies ─────────────────────────────────


class SyncRequest(BaseModel):
    node_id: Optional[str] = None
    auto_enable: int = Field(default=3, ge=0, le=20)


class ManualAddRequest(BaseModel):
    node_id: str
    external_model_id: str
    runtime: str = "ollama"
    display_name: Optional[str] = None
    enabled: bool = True
    pinned: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    supports_embeddings: bool = False


class PullRequest(BaseModel):
    node_id: Optional[str] = None
    model: str


class EnableRequest(BaseModel):
    enabled: bool = True


class PinRequest(BaseModel):
    pinned: bool = True


# ── Helpers ─────────────────────────────────────────────────


def _components(request: Request) -> tuple[
    LocalCatalogRepository, LocalCatalogSyncService, LocalModelHealthChecker, LocalPullManager,
]:
    repo = getattr(request.app.state, "local_catalog_repo", None)
    svc = getattr(request.app.state, "local_catalog_sync", None)
    health = getattr(request.app.state, "local_catalog_health", None)
    pulls = getattr(request.app.state, "local_catalog_pulls", None)
    if not (repo and svc and health and pulls):
        raise HTTPException(503, "Local catalog not initialised")
    return repo, svc, health, pulls


def _default_node_id() -> str:
    return settings.LOCAL_NODE_ID or "local"


def _build_client(base_url: Optional[str] = None) -> LocalRuntimeClient:
    return LocalRuntimeClient(base_url=base_url or settings.OLLAMA_BASE_URL)


def _model_to_dict(m: LocalModel) -> dict:
    return {
        "router_model_id": m.router_model_id,
        "node_id": m.node_id,
        "runtime": m.runtime.value,
        "external_model_id": m.external_model_id,
        "display_name": m.display_name,
        "family": m.family,
        "parameter_size": m.parameter_size,
        "parameter_count": m.parameter_count,
        "quantization": m.quantization,
        "context_window": m.context_window,
        "disk_size_bytes": m.disk_size_bytes,
        "size_marker": m.size_marker,
        "capabilities": m.capabilities.model_dump() if m.capabilities else None,
        "rank": m.rank,
        "score": round(m.score, 4),
        "is_top_recommended": m.is_top_recommended,
        "enabled": m.enabled,
        "pinned": m.pinned,
        "manually_added": m.manually_added,
        "setup_status": m.setup_status.value,
        "modified_at": m.modified_at.isoformat() if m.modified_at else None,
        "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
        "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
        "last_error": m.last_error,
        "latency_observed_ms": m.latency_observed_ms,
        "avg_latency_ms": m.avg_latency_ms,
    }


# ── /local/runtime ──────────────────────────────────────────


@router.get("/runtime/info")
async def runtime_info(request: Request, _key: str = Depends(require_api_key)):
    """Summary used by cloud Admin to render the local node card."""
    repo, _svc, _hc, _pulls = _components(request)
    client = _build_client()
    node_id = _default_node_id()
    reachable = await client.ping()
    stats = repo.stats(node_id)
    return {
        "node_id": node_id,
        "node_name": settings.APP_NAME,
        "runtime": "ollama",
        "runtime_base_url": settings.OLLAMA_BASE_URL,
        "reachable": reachable,
        "stats": stats.model_dump(mode="json"),
        "capabilities": {
            "chat": True,
            "embeddings": True,
            "streaming": True,
            "tools": True,
        },
    }


# ── /local/models ───────────────────────────────────────────


@router.get("/models")
async def list_models(
    request: Request,
    node_id: Optional[str] = None,
    enabled: Optional[bool] = None,
    top: Optional[bool] = None,
    family: Optional[str] = None,
    limit: int = 500,
    _key: str = Depends(require_api_key),
):
    repo, _svc, _hc, _pulls = _components(request)
    models = repo.list_models(node_id)
    if enabled is not None:
        models = [m for m in models if m.enabled == enabled]
    if top:
        models = [m for m in models if m.is_top_recommended]
    if family:
        fam = family.lower()
        models = [m for m in models if (m.family or "").lower() == fam]
    models.sort(key=lambda m: (-(m.score or 0.0), m.router_model_id))
    return {
        "models": [_model_to_dict(m) for m in models[:limit]],
        "stats": repo.stats(node_id).model_dump(mode="json"),
        "nodes": repo.list_nodes(),
    }


@router.get("/models/top")
async def list_top_models(
    request: Request,
    node_id: Optional[str] = None,
    limit: int = 3,
    _key: str = Depends(require_api_key),
):
    repo, _svc, _hc, _pulls = _components(request)
    top = repo.list_top(node_id)[:limit]
    return {"models": [_model_to_dict(m) for m in top]}


@router.post("/models/sync")
async def sync_models(
    request: Request,
    body: SyncRequest = Body(default_factory=SyncRequest),
    _key: str = Depends(require_api_key),
):
    _repo, svc, _hc, _pulls = _components(request)
    node_id = body.node_id or _default_node_id()
    client = _build_client()
    result = await svc.sync_node(
        node_id=node_id, client=client, auto_enable_top=body.auto_enable,
    )
    return result.model_dump(mode="json")


@router.post("/models/manual")
async def add_manual_model(
    request: Request,
    body: ManualAddRequest,
    _key: str = Depends(require_api_key),
):
    _repo, svc, _hc, _pulls = _components(request)
    m = await svc.add_manual_model(
        node_id=body.node_id,
        external_model_id=body.external_model_id,
        runtime=body.runtime,
        display_name=body.display_name,
        enabled=body.enabled,
        pinned=body.pinned,
        supports_tools=body.supports_tools,
        supports_vision=body.supports_vision,
        supports_embeddings=body.supports_embeddings,
    )
    return _model_to_dict(m)


@router.post("/models/{router_model_id:path}/enable")
async def enable_model(
    router_model_id: str,
    request: Request,
    body: EnableRequest = Body(default_factory=EnableRequest),
    _key: str = Depends(require_api_key),
):
    repo, _svc, _hc, _pulls = _components(request)
    ok = await repo.set_enabled(router_model_id, body.enabled)
    if not ok:
        raise HTTPException(404, f"Model not found: {router_model_id}")
    await repo.save()
    return {"ok": True, "router_model_id": router_model_id, "enabled": body.enabled}


@router.post("/models/{router_model_id:path}/pin")
async def pin_model(
    router_model_id: str,
    request: Request,
    body: PinRequest = Body(default_factory=PinRequest),
    _key: str = Depends(require_api_key),
):
    repo, _svc, _hc, _pulls = _components(request)
    ok = await repo.set_pinned(router_model_id, body.pinned)
    if not ok:
        raise HTTPException(404, f"Model not found: {router_model_id}")
    await repo.save()
    return {"ok": True, "router_model_id": router_model_id, "pinned": body.pinned}


@router.post("/models/{router_model_id:path}/test")
async def test_model(
    router_model_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
):
    repo, _svc, health, _pulls = _components(request)
    client = _build_client()
    ok = await health.check_one(router_model_id, client, force=True)
    m = repo.get(router_model_id)
    if not m:
        raise HTTPException(404, f"Model not found: {router_model_id}")
    return {
        "ok": ok,
        "router_model_id": router_model_id,
        "setup_status": m.setup_status.value,
        "latency_ms": m.latency_observed_ms,
        "error": m.last_error,
    }


@router.delete("/models/{router_model_id:path}")
async def delete_model(
    router_model_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
):
    repo, _svc, _hc, _pulls = _components(request)
    m = repo.get(router_model_id)
    if not m:
        raise HTTPException(404, f"Model not found: {router_model_id}")
    if not m.manually_added:
        raise HTTPException(400, "Only manually-added catalog entries can be deleted via this endpoint")
    await repo.delete(router_model_id)
    await repo.save()
    return {"ok": True, "router_model_id": router_model_id}


# ── /local/models/pull (background streaming) ───────────────


@router.post("/models/pull")
async def pull_model(
    request: Request,
    body: PullRequest,
    _key: str = Depends(require_api_key),
):
    _repo, _svc, _hc, pulls = _components(request)
    node_id = body.node_id or _default_node_id()
    client = _build_client()
    progress = await pulls.start(node_id=node_id, external_model_id=body.model, client=client)
    return {
        "node_id": progress.node_id,
        "external_model_id": progress.external_model_id,
        "status": progress.status,
        "progress_pct": progress.progress_pct,
    }


@router.get("/models/pull/{external_model_id:path}")
async def pull_status(
    external_model_id: str,
    request: Request,
    node_id: Optional[str] = None,
    _key: str = Depends(require_api_key),
):
    _repo, _svc, _hc, pulls = _components(request)
    nid = node_id or _default_node_id()
    progress = pulls.get(nid, external_model_id)
    if not progress:
        raise HTTPException(404, "No pull in progress for this model")
    return {
        "node_id": progress.node_id,
        "external_model_id": progress.external_model_id,
        "status": progress.status,
        "total_bytes": progress.total_bytes,
        "completed_bytes": progress.completed_bytes,
        "progress_pct": progress.progress_pct,
        "error": progress.error,
        "last_update": progress.last_update.isoformat(),
    }


@router.get("/models/pulls/active")
async def active_pulls(request: Request, _key: str = Depends(require_api_key)):
    _repo, _svc, _hc, pulls = _components(request)
    rows = pulls.list_active()
    return {"pulls": [
        {
            "node_id": p.node_id,
            "external_model_id": p.external_model_id,
            "status": p.status,
            "progress_pct": p.progress_pct,
        }
        for p in rows
    ]}


# ── Heartbeat-ready manifest for cloud Admin ────────────────


@router.get("/cloud/manifest")
async def cloud_manifest(
    request: Request,
    node_id: Optional[str] = None,
    _key: str = Depends(require_api_key),
):
    """
    Manifest the cloud bridge ships in its heartbeat so the cloud Admin
    can render this node beside cloud providers.

    Shape is intentionally a superset of what the cloud's
    ``huggingface_catalog`` produces — same field names, same enums — so
    cloud side ingestion is trivial.
    """
    repo, _svc, _hc, _pulls = _components(request)
    nid = node_id or _default_node_id()
    models = repo.list_models(nid)
    return {
        "node": {
            "id": nid,
            "name": settings.APP_NAME,
            "runtime": "ollama",
            "runtime_base_url": settings.OLLAMA_BASE_URL,
            "execution_location": "local",
        },
        "stats": repo.stats(nid).model_dump(mode="json"),
        "models": [_model_to_dict(m) for m in models],
    }
