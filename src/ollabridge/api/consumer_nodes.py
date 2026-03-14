"""Consumer Nodes API — CRUD endpoints for the consumer node registry.

Endpoints:
  GET    /consumer-nodes          — List all consumer nodes
  POST   /consumer-nodes          — Create a new consumer node
  PATCH  /consumer-nodes/{id}     — Update a consumer node
  DELETE /consumer-nodes/{id}     — Remove a consumer node
  POST   /consumer-nodes/{id}/heartbeat — Touch last_seen timestamp
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.core.security import require_api_key


router = APIRouter(prefix="/consumer-nodes", tags=["consumer-nodes"])


class CreateConsumerNode(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    kind: str = Field("custom")
    protocol: str = Field("WebSocket")
    description: str = Field("")
    enabled: bool = Field(True)


class PatchConsumerNode(BaseModel):
    name: str | None = None
    kind: str | None = None
    protocol: str | None = None
    description: str | None = None
    enabled: bool | None = None


def _get_registry(request: Request):
    return request.app.state.obridge.consumers


@router.get("")
async def list_consumer_nodes(
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    registry = _get_registry(request)
    nodes = registry.list_all()
    return {
        "nodes": [n.to_dict() for n in nodes],
        "count": len(nodes),
    }


@router.post("")
async def create_consumer_node(
    body: CreateConsumerNode,
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    from ollabridge.core.consumer_registry import ConsumerNode

    registry = _get_registry(request)
    node = ConsumerNode(
        name=body.name,
        kind=body.kind,
        protocol=body.protocol,
        description=body.description,
        enabled=body.enabled,
    )
    created = registry.add(node)
    return {"ok": True, "node": created.to_dict()}


@router.patch("/{node_id}")
async def patch_consumer_node(
    node_id: str,
    body: PatchConsumerNode,
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    registry = _get_registry(request)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(422, "No fields to update")
    updated = registry.update(node_id, patch)
    if updated is None:
        raise HTTPException(404, f"Consumer node '{node_id}' not found")
    return {"ok": True, "node": updated.to_dict()}


@router.delete("/{node_id}")
async def delete_consumer_node(
    node_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    registry = _get_registry(request)
    removed = registry.remove(node_id)
    if not removed:
        raise HTTPException(404, f"Consumer node '{node_id}' not found")
    return {"ok": True, "deleted": node_id}


@router.post("/{node_id}/heartbeat")
async def heartbeat(
    node_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
) -> dict[str, Any]:
    registry = _get_registry(request)
    node = registry.get(node_id)
    if node is None:
        raise HTTPException(404, f"Consumer node '{node_id}' not found")
    registry.touch(node_id)
    return {"ok": True}
