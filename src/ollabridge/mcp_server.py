"""
OllaBridge MCP Server

Model Context Protocol (MCP) server that exposes OllaBridge as a set of tools
for external AI agents to bootstrap and control local LLM infrastructure.

This allows agents to:
- Check if Ollama is installed
- Install Ollama (Linux/macOS)
- Ensure models are available
- Start/stop the OllaBridge gateway
- Check gateway health

Usage:
    ollabridge-mcp           # Start MCP server (stdio mode)
    python -m ollabridge.mcp_server
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from ollabridge.utils.installer import (
    ensure_model,
    ensure_ollama_server_running,
    install_ollama,
    is_ollama_installed,
)

# ----------------------------
# MCP Protocol Helpers
# ----------------------------


def _rpc_result(rpc_id: Any, content_text: str, *, is_error: bool = False) -> dict:
    """Create a JSON-RPC 2.0 tool call result."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error,
        },
    }


def _rpc_error(rpc_id: Any, code: int, message: str) -> dict:
    """Create a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": code, "message": message},
    }


# ----------------------------
# MCP Tool Definitions
# ----------------------------

TOOLS: list[dict] = [
    {
        "name": "ollabridge.check_ollama",
        "description": "Check whether Ollama is installed and visible on PATH.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ollabridge.install_ollama",
        "description": "Install Ollama (Linux/macOS automatic; Windows opens download page).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assume_yes": {
                    "type": "boolean",
                    "description": "If true, do not prompt interactively (required for MCP mode).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "ollabridge.ensure_model",
        "description": "Ensure an Ollama model is present; pulls it if missing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Model name (e.g., deepseek-r1, llama3.1, nomic-embed-text)",
                }
            },
            "required": ["model"],
        },
    },
    {
        "name": "ollabridge.start_gateway",
        "description": "Start the OllaBridge gateway in the background and return local URL + pid.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "127.0.0.1", "description": "Bind host"},
                "port": {"type": "integer", "default": 11435, "description": "Bind port"},
                "model": {"type": "string", "default": "deepseek-r1", "description": "Default chat model"},
                "workers": {"type": "integer", "default": 1, "description": "Number of worker processes"},
                "share": {"type": "boolean", "default": False, "description": "Enable public URL (ngrok)"},
            },
            "required": [],
        },
    },
    {
        "name": "ollabridge.stop_gateway",
        "description": "Stop a previously started gateway process by PID.",
        "inputSchema": {
            "type": "object",
            "properties": {"pid": {"type": "integer", "description": "Process ID to terminate"}},
            "required": ["pid"],
        },
    },
    {
        "name": "ollabridge.health",
        "description": "Check gateway health endpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_url": {
                    "type": "string",
                    "description": "Gateway base URL (e.g., http://127.0.0.1:11435)",
                }
            },
            "required": ["base_url"],
        },
    },
    {
        "name": "ollabridge.list_models",
        "description": "List all Ollama models currently installed.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


# ----------------------------
# Gateway Process Tracking
# ----------------------------


@dataclass
class GatewayProcess:
    """Represents a running gateway instance."""

    pid: int
    base_url: str
    public_url: Optional[str] = None
    model: str = "deepseek-r1"


# In-memory tracking of gateway processes started by this MCP server
GATEWAYS: Dict[int, GatewayProcess] = {}


# ----------------------------
# Tool Implementation Functions
# ----------------------------


async def tool_check_ollama(_: dict) -> str:
    """Check if Ollama is installed."""
    installed = is_ollama_installed()
    return json.dumps({"installed": installed, "message": "Ollama found" if installed else "Ollama not found"}, indent=2)


async def tool_install_ollama(args: dict) -> str:
    """Install Ollama (requires assume_yes=True for non-interactive mode)."""
    assume_yes = bool(args.get("assume_yes", False))

    if not assume_yes:
        return json.dumps(
            {
                "ok": False,
                "message": "MCP mode requires assume_yes=true to avoid interactive prompts. "
                "Set assume_yes to true to proceed with installation.",
            },
            indent=2,
        )

    if is_ollama_installed():
        return json.dumps({"ok": True, "message": "Ollama already installed."}, indent=2)

    try:
        install_ollama(assume_yes=True)
        return json.dumps(
            {
                "ok": True,
                "message": "Ollama installation triggered. Verify with ollabridge.check_ollama.",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "message": "Installation failed. You may need to install manually from https://ollama.com/download",
            },
            indent=2,
        )


async def tool_ensure_model(args: dict) -> str:
    """Ensure a model is available (pulls if missing)."""
    model = (args.get("model") or "").strip()
    if not model:
        raise ValueError("model parameter is required")

    if not is_ollama_installed():
        return json.dumps(
            {
                "ok": False,
                "message": "Ollama not installed. Use ollabridge.install_ollama first.",
            },
            indent=2,
        )

    try:
        ensure_ollama_server_running()
        ensure_model(model)
        return json.dumps({"ok": True, "model": model, "message": f"Model '{model}' is ready."}, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "model": model,
                "error": str(e),
                "message": f"Failed to ensure model '{model}'. Is Ollama running?",
            },
            indent=2,
        )


async def tool_list_models(_: dict) -> str:
    """List all installed Ollama models."""
    if not is_ollama_installed():
        return json.dumps(
            {
                "ok": False,
                "message": "Ollama not installed.",
            },
            indent=2,
        )

    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return json.dumps(
                {
                    "ok": False,
                    "message": "Failed to list models. Is Ollama running?",
                    "stderr": result.stderr,
                },
                indent=2,
            )

        return json.dumps(
            {
                "ok": True,
                "output": result.stdout,
                "message": "Models listed successfully.",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "message": "Failed to list models.",
            },
            indent=2,
        )


async def tool_start_gateway(args: dict) -> str:
    """Start the OllaBridge gateway as a background process."""
    host = (args.get("host") or "127.0.0.1").strip()
    port = int(args.get("port") or 11435)
    model = (args.get("model") or "deepseek-r1").strip()
    workers = int(args.get("workers") or 1)
    share = bool(args.get("share") or False)

    if not is_ollama_installed():
        return json.dumps(
            {
                "ok": False,
                "message": "Ollama not installed. Use ollabridge.install_ollama first.",
            },
            indent=2,
        )

    # Ensure Ollama is running and model is available
    try:
        ensure_ollama_server_running()
        ensure_model(model)
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "message": f"Failed to prepare Ollama/model '{model}'.",
            },
            indent=2,
        )

    # Start gateway as a subprocess (so MCP server stays responsive)
    cmd = [
        sys.executable,
        "-m",
        "ollabridge.cli.main",
        "start",
        "--host",
        host,
        "--port",
        str(port),
        "--model",
        model,
        "--workers",
        str(workers),
    ]
    if share:
        cmd.append("--share")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
            start_new_session=True,  # allows clean termination of process group
        )

        base_url = f"http://{host}:{port}"
        gw = GatewayProcess(pid=proc.pid, base_url=base_url, model=model, public_url=None)
        GATEWAYS[proc.pid] = gw

        return json.dumps(
            {
                "ok": True,
                "pid": proc.pid,
                "base_url": base_url,
                "openai_base_url": f"{base_url}/v1",
                "health_url": f"{base_url}/health",
                "model": model,
                "workers": workers,
                "message": "Gateway started. Use ollabridge.health to verify readiness (may take a few seconds).",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "message": "Failed to start gateway process.",
            },
            indent=2,
        )


async def tool_stop_gateway(args: dict) -> str:
    """Stop a gateway process by PID."""
    pid = args.get("pid")
    if not pid:
        raise ValueError("pid parameter is required")

    pid = int(pid)

    try:
        # Kill process group (since we started with start_new_session)
        os.killpg(pid, signal.SIGTERM)
        GATEWAYS.pop(pid, None)
        return json.dumps({"ok": True, "pid": pid, "message": "Gateway stopped."}, indent=2)
    except ProcessLookupError:
        return json.dumps(
            {
                "ok": False,
                "pid": pid,
                "message": "Process not found (already stopped or invalid PID).",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "pid": pid,
                "error": str(e),
                "message": "Failed to stop gateway.",
            },
            indent=2,
        )


async def tool_health(args: dict) -> str:
    """Check gateway health endpoint."""
    base_url = (args.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("base_url parameter is required")

    url = base_url.rstrip("/") + "/health"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            return json.dumps(
                {
                    "ok": r.status_code == 200,
                    "status_code": r.status_code,
                    "response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
                    "message": "Gateway is healthy" if r.status_code == 200 else "Gateway returned non-200 status",
                },
                indent=2,
            )
    except httpx.TimeoutException:
        return json.dumps(
            {
                "ok": False,
                "message": "Health check timed out. Gateway may still be starting.",
            },
            indent=2,
        )
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": str(e),
                "message": "Health check failed. Is the gateway running?",
            },
            indent=2,
        )


# ----------------------------
# Tool Handler Registry
# ----------------------------

TOOL_HANDLERS = {
    "ollabridge.check_ollama": tool_check_ollama,
    "ollabridge.install_ollama": tool_install_ollama,
    "ollabridge.ensure_model": tool_ensure_model,
    "ollabridge.list_models": tool_list_models,
    "ollabridge.start_gateway": tool_start_gateway,
    "ollabridge.stop_gateway": tool_stop_gateway,
    "ollabridge.health": tool_health,
}


# ----------------------------
# MCP Message Handler
# ----------------------------


async def handle_message(msg: dict) -> dict:
    """Handle a single MCP JSON-RPC 2.0 message."""
    rpc_id = msg.get("id", None)
    method = msg.get("method")

    # Initialize (MCP handshake)
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "ollabridge-mcp",
                    "version": "1.0.0",
                },
            },
        }

    # List tools
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"tools": TOOLS, "nextCursor": None},
        }

    # Call a tool
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}

        if name not in TOOL_HANDLERS:
            return _rpc_error(rpc_id, -32602, f"Unknown tool: {name}")

        try:
            text = await TOOL_HANDLERS[name](args)
            return _rpc_result(rpc_id, text, is_error=False)
        except Exception as e:
            return _rpc_result(rpc_id, f"{type(e).__name__}: {e}", is_error=True)

    # Ping (optional, for keepalive)
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    # Unknown method
    return _rpc_error(rpc_id, -32601, f"Method not found: {method}")


# ----------------------------
# MCP Stdio Transport
# ----------------------------


async def _stdio_main():
    """Run MCP server over stdio (JSON-RPC 2.0 line-delimited)."""
    # Set up async stdin reader
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    # Set up async stdout writer
    writer_transport, writer_protocol = await asyncio.get_running_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, asyncio.get_running_loop())

    # Message loop
    while True:
        line = await reader.readline()
        if not line:
            break

        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            # Invalid JSON; cannot respond without id
            continue

        resp = await handle_message(msg)
        writer.write((json.dumps(resp) + "\n").encode("utf-8"))
        await writer.drain()


def main():
    """Entry point for MCP server (stdio mode)."""
    try:
        asyncio.run(_stdio_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
