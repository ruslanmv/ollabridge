from __future__ import annotations

import asyncio
import json
import os
import platform as py_platform
import socket
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import websockets

from ollabridge.node.runtime import LocalRuntime


@dataclass(frozen=True)
class NodeConfig:
    control: str
    token: str
    node_id: str
    runtime_base_url: str
    tags: list[str]
    capacity: int


@dataclass(frozen=True)
class CloudDeviceConfig:
    cloud_url: str
    device_id: str
    device_token: str
    runtime_base_url: str


def default_node_id() -> str:
    return os.environ.get("OBRIDGE_NODE_ID") or f"node-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"


async def run_node(config: NodeConfig) -> None:
    """Connect to the Local Control Plane and serve inference over the relay link."""
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
            "meta": {"platform": py_platform.platform()},
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


def _platform_short() -> str:
    p = py_platform.system().lower()
    if "darwin" in p or "mac" in p:
        return "macos"
    if "windows" in p:
        return "windows"
    return "linux"


def _chat_completion_payload(model: str, content: str) -> dict[str, Any]:
    # OpenAI-ish shape (what Cloud examples show)
    return {
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


async def run_cloud_device(config: CloudDeviceConfig) -> None:
    """
    Connect to OllaBridge Cloud relay using Authorization: Bearer <device_token>
    and speak the Cloud protocol (docs/PROTOCOL.md).
    """
    runtime = LocalRuntime(config.runtime_base_url)
    models = await runtime.list_models()

    ws_url = f"{config.cloud_url.rstrip('/')}/relay/connect"
    headers = {"Authorization": f"Bearer {config.device_token}"}

    async with websockets.connect(ws_url, extra_headers=headers, max_size=2**25) as ws:
        hello = {
            "type": "hello",
            "device_id": config.device_id,
            "client_version": "ollabridge-local-cloud-compat/0.1.0",
            "platform": _platform_short(),
            "models": models,
            "capabilities": ["chat", "embeddings", "models"],
            "protocol_version": "0.1.0",
        }
        await ws.send(json.dumps(hello))

        stop = asyncio.Event()

        async def heartbeat() -> None:
            # Device should ping every 30-60 seconds; Cloud responds pong
            while not stop.is_set():
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    return
                await asyncio.sleep(30)

        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                raw = await ws.recv()
                frame = json.loads(raw)

                mtype = frame.get("type")
                if mtype in ("pong", "hello_ack"):
                    continue

                if mtype != "req":
                    continue

                req_id = frame.get("id")
                op = frame.get("op")
                payload = frame.get("payload") or {}

                # Cloud: op in {chat, embeddings, models}
                try:
                    if op == "models":
                        models = await runtime.list_models()
                        res = {
                            "type": "res",
                            "id": req_id,
                            "ok": True,
                            "data": {"object": "list", "data": [{"id": m, "object": "model"} for m in models]},
                        }
                        await ws.send(json.dumps(res))
                        continue

                    if op == "embeddings":
                        model = payload.get("model") or ""
                        text = payload.get("input") or payload.get("text") or ""
                        emb = await runtime.embeddings(model=model, text=str(text))
                        res = {
                            "type": "res",
                            "id": req_id,
                            "ok": True,
                            "data": {
                                "object": "list",
                                "model": model,
                                "data": [{"object": "embedding", "index": 0, "embedding": emb}],
                            },
                        }
                        await ws.send(json.dumps(res))
                        continue

                    if op == "chat":
                        model = payload.get("model") or ""
                        messages = payload.get("messages") or []
                        stream = bool(payload.get("stream") is True)

                        if not stream:
                            content = await runtime.chat(model=model, messages=messages)
                            res = {
                                "type": "res",
                                "id": req_id,
                                "ok": True,
                                "data": _chat_completion_payload(model=model, content=content),
                            }
                            await ws.send(json.dumps(res))
                            continue

                        # Streaming: send delta chunks + done
                        async for chunk in runtime.chat_stream(model=model, messages=messages):
                            await ws.send(json.dumps({"type": "delta", "id": req_id, "content": chunk}))
                        await ws.send(json.dumps({"type": "done", "id": req_id}))
                        continue

                    # Unknown op
                    await ws.send(json.dumps({"type": "res", "id": req_id, "ok": False, "error": f"unknown op: {op}"}))

                except Exception as e:
                    # Cloud protocol supports either res(ok=false) or error frames; keep it simple:
                    await ws.send(json.dumps({"type": "res", "id": req_id, "ok": False, "error": str(e)}))

        finally:
            stop.set()
            try:
                hb_task.cancel()
            except Exception:
                pass
