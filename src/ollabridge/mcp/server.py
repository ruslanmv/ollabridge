"""OllaBridge MCP server (stdio).

This exposes the Control Plane as a tool server for any MCP-capable agent.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from ollabridge.mcp.tools import tool_specs, handle_tool


def _rpc_result(rpc_id: Any, content_text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error,
        },
    }


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


async def _handle(msg: dict[str, Any]) -> dict[str, Any]:
    method = msg.get("method")
    rpc_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "ollabridge", "version": "1.1"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tool_specs()}}

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            out = await handle_tool(str(name), dict(args))
            return _rpc_result(rpc_id, out)
        except Exception as e:
            return _rpc_result(rpc_id, f"error: {e}", is_error=True)

    return _rpc_error(rpc_id, -32601, f"unknown method: {method}")


async def run_stdio() -> None:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_running_loop().connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_running_loop())

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue

        res = await _handle(msg)
        writer.write((json.dumps(res) + "\n").encode("utf-8"))
        await writer.drain()


def main() -> None:
    asyncio.run(run_stdio())
