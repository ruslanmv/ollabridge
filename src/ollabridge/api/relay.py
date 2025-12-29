from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ollabridge.core.enrollment import verify_join_token
from ollabridge.core.registry import RuntimeNodeState, RuntimeRegistry


@dataclass
class _RelayConn:
    node_id: str
    ws: WebSocket


class RelayHub:
    """Multiplex requests to nodes connected over WebSocket.

    Protocol is simple JSON frames:
    - node -> server: {"type":"hello", "node_id":"...", ...}
    - server -> node: {"type":"req", "id":"...", "op":"chat|embeddings|models", "payload":{...}}
    - node -> server: {"type":"res", "id":"...", "ok":true, "data":{...}}
    """

    def __init__(self, registry: RuntimeRegistry) -> None:
        self.registry = registry
        self._conns: dict[str, _RelayConn] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def attach(self, node_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[node_id] = _RelayConn(node_id=node_id, ws=ws)

    async def detach(self, node_id: str) -> None:
        async with self._lock:
            self._conns.pop(node_id, None)
        await self.registry.remove(node_id)

    async def request(self, node_id: str, op: str, payload: dict[str, Any], *, timeout_s: float = 120) -> dict[str, Any]:
        async with self._lock:
            conn = self._conns.get(node_id)
            if not conn:
                raise RuntimeError("node not connected")
            req_id = str(uuid.uuid4())
            fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending[req_id] = fut
            await conn.ws.send_text(json.dumps({"type": "req", "id": req_id, "op": op, "payload": payload}))

        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        finally:
            async with self._lock:
                self._pending.pop(req_id, None)

    async def handle_frame(self, node_id: str, frame: dict[str, Any]) -> None:
        if frame.get("type") != "res":
            return
        req_id = frame.get("id")
        if not req_id:
            return
        async with self._lock:
            fut = self._pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(frame)


def build_relay_router(*, registry: RuntimeRegistry, hub: RelayHub) -> APIRouter:
    router = APIRouter()

    @router.websocket("/relay/connect")
    async def relay_connect(ws: WebSocket):
        # Token comes via query param to keep node bootstrap command simple.
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4401)
            return

        try:
            verify_join_token(token)
        except Exception:
            await ws.close(code=4403)
            return

        await ws.accept()
        node_id: Optional[str] = None
        try:
            # Expect hello first
            raw = await ws.receive_text()
            hello = json.loads(raw)
            if hello.get("type") != "hello":
                await ws.close(code=4400)
                return

            node_id = str(hello.get("node_id") or "").strip() or str(uuid.uuid4())
            tags = list(hello.get("tags") or [])
            models = list(hello.get("models") or [])
            capacity = int(hello.get("capacity") or 1)

            await hub.attach(node_id, ws)
            await registry.upsert(
                RuntimeNodeState(
                    node_id=node_id,
                    connector="relay_link",
                    tags=tags,
                    models=models,
                    capacity=capacity,
                    meta={"via": "relay"},
                )
            )
            await ws.send_text(json.dumps({"type": "hello_ack", "node_id": node_id}))

            while True:
                msg = await ws.receive_text()
                frame = json.loads(msg)
                await hub.handle_frame(node_id, frame)
                await registry.touch(node_id)
        except WebSocketDisconnect:
            pass
        except Exception:
            # Avoid crashing the server; node will reconnect.
            pass
        finally:
            if node_id:
                await hub.detach(node_id)

    return router
