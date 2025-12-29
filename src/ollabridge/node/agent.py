from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import uuid
from dataclasses import dataclass
from typing import Any

import websockets

from ollabridge.core.settings import settings
from ollabridge.node.runtime import LocalRuntime


@dataclass(frozen=True)
class NodeConfig:
    control: str
    token: str
    node_id: str
    runtime_base_url: str
    tags: list[str]
    capacity: int


def default_node_id() -> str:
    return os.environ.get("OBRIDGE_NODE_ID") or f"node-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


async def run_node(config: NodeConfig) -> None:
    """Connect to the Control Plane and serve inference over the relay link."""

    runtime = LocalRuntime(config.runtime_base_url)
    models = await runtime.list_models()

    ws_url = f"{config.control.rstrip('/')}/relay/connect?token={config.token}"

    async with websockets.connect(ws_url, max_size=2**25) as ws:
        hello = {
            "type": "hello",
            "node_id": config.node_id,
            "tags": config.tags,
            "models": models,
            "capacity": config.capacity,
            "meta": {
                "platform": platform.platform(),
            },
        }
        await ws.send(json.dumps(hello))
        _ = await ws.recv()  # hello_ack

        while True:
            raw = await ws.recv()
            frame = json.loads(raw)
            if frame.get("type") != "req":
                continue
            req_id = frame.get("id")
            op = frame.get("op")
            payload = frame.get("payload") or {}

            try:
                if op == "chat":
                    content = await runtime.chat(model=payload["model"], messages=payload["messages"])
                    res = {"type": "res", "id": req_id, "ok": True, "data": {"content": content}}
                elif op == "embeddings":
                    emb = await runtime.embeddings(model=payload["model"], text=payload.get("input") or "")
                    res = {"type": "res", "id": req_id, "ok": True, "data": {"embedding": emb}}
                elif op == "models":
                    models = await runtime.list_models()
                    res = {
                        "type": "res",
                        "id": req_id,
                        "ok": True,
                        "data": {"object": "list", "data": [{"id": m, "object": "model"} for m in models]},
                    }
                else:
                    res = {"type": "res", "id": req_id, "ok": False, "error": f"unknown op: {op}"}
            except Exception as e:
                res = {"type": "res", "id": req_id, "ok": False, "error": str(e)}

            await ws.send(json.dumps(res))
