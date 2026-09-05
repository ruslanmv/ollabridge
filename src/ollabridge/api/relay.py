from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

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

    **Streams (avatar session relay).** The two frames above are a request/response pair, and
    they are enough for inference: the cloud asks, the node answers, nobody else speaks. They
    are not enough for the avatar session, where HomePilot starts turns of its own — curiosity,
    a greeting, a reaction. A node with something to say has nowhere to put it in a protocol
    where every frame is an answer to a question the cloud asked.

    So there are two more, and they are deliberately the mirror of each other:

    - server -> node: {"type":"sig", "stream":"...", "op":"...", "payload":{...}}
    - node -> server: {"type":"ev",  "stream":"...", "payload":{...}}

    Both are fire-and-forget. `sig` is not a `req` with the response ignored, because a `req`
    allocates a future that something must resolve — an unanswered one leaks until timeout, and
    a session sends thousands. `ev` is not a `res`, because it answers nothing.

    `stream` is what makes fan-out possible: one node may carry several browser sessions at
    once, and an event has to reach the one it belongs to rather than all of them.
    """

    def __init__(self, registry: RuntimeRegistry) -> None:
        self.registry = registry
        self._conns: dict[str, _RelayConn] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        #: stream_id -> the queue its browser session is reading. Bounded: a browser that
        #: stops reading must not let a chatty node consume the cloud's memory.
        self._streams: dict[str, asyncio.Queue] = {}
        #: stream_id -> node_id, so closing a node closes its streams and no session is left
        #: waiting on frames that can never arrive.
        self._stream_node: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def attach(self, node_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[node_id] = _RelayConn(node_id=node_id, ws=ws)

    async def detach(self, node_id: str) -> None:
        async with self._lock:
            self._conns.pop(node_id, None)
            dead = [sid for sid, owner in self._stream_node.items() if owner == node_id]
            for sid in dead:
                queue = self._streams.pop(sid, None)
                self._stream_node.pop(sid, None)
                # `None` is the end-of-stream marker: a reader blocked on `get()` has to be
                # woken, or the browser session hangs until its own socket times out.
                if queue is not None:
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(None)
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
        kind = frame.get("type")
        if kind == "ev":
            await self._deliver_event(node_id, frame)
            return
        if kind != "res":
            return
        req_id = frame.get("id")
        if not req_id:
            return
        async with self._lock:
            fut = self._pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(frame)

    # ── streams ──────────────────────────────────────────────────────────────

    async def open_stream(self, node_id: str, *, maxsize: int = 256) -> tuple[str, asyncio.Queue]:
        """Register a stream on `node_id` and return its id and inbound queue.

        The queue is bounded. An unbounded one turns a browser that stopped reading — a closed
        laptop lid, a backgrounded tab — into unbounded growth in the cloud process, and the
        node has no way to know it is talking to nobody.
        """
        stream_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._streams[stream_id] = queue
            self._stream_node[stream_id] = node_id
        return stream_id, queue

    async def close_stream(self, stream_id: str) -> None:
        """Forget a stream. Idempotent: both ends may notice the end at once."""
        async with self._lock:
            self._streams.pop(stream_id, None)
            self._stream_node.pop(stream_id, None)

    async def signal(self, node_id: str, stream_id: str, op: str, payload: dict[str, Any]) -> None:
        """Send a fire-and-forget frame to a node. Raises if the node is gone."""
        async with self._lock:
            conn = self._conns.get(node_id)
            if not conn:
                raise RuntimeError("node not connected")
        await conn.ws.send_text(
            json.dumps({"type": "sig", "stream": stream_id, "op": op, "payload": payload})
        )

    async def _deliver_event(self, node_id: str, frame: dict[str, Any]) -> None:
        """Route one `ev` to the stream that owns it, and to nothing else."""
        stream_id = str(frame.get("stream") or "")
        async with self._lock:
            queue = self._streams.get(stream_id)
            owner = self._stream_node.get(stream_id)
        # A node may only push into streams it owns. Without this a compromised or buggy node
        # could inject frames into another node's browser session.
        if queue is None or owner != node_id:
            return
        try:
            queue.put_nowait(frame.get("payload"))
        except asyncio.QueueFull:
            # The session is not keeping up. Dropping the oldest keeps a live conversation
            # current rather than replaying a backlog nobody wants when it recovers.
            try:
                queue.get_nowait()
                queue.put_nowait(frame.get("payload"))
            except Exception:
                pass


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
        node_id: str | None = None
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
