from __future__ import annotations

import json
from typing import Any

import httpx

from ollabridge.core.enrollment import create_join_token
from ollabridge.core.settings import settings


def tool_specs() -> list[dict[str, Any]]:
    """MCP tool definitions (JSON Schema)."""

    return [
        {
            "name": "ollabridge.enroll.create",
            "description": "Create a short-lived node enrollment token.",
            "inputSchema": {
                "type": "object",
                "properties": {"ttl_seconds": {"type": "integer", "default": 3600}},
                "required": [],
            },
        },
        {
            "name": "ollabridge.runtimes.list",
            "description": "List currently connected runtimes.",
            "inputSchema": {
                "type": "object",
                "properties": {"base_url": {"type": "string", "default": f"http://127.0.0.1:{settings.PORT}"}},
                "required": [],
            },
        },
        {
            "name": "ollabridge.gateway.health",
            "description": "Check gateway health.",
            "inputSchema": {
                "type": "object",
                "properties": {"base_url": {"type": "string", "default": f"http://127.0.0.1:{settings.PORT}"}},
                "required": [],
            },
        },
    ]


async def handle_tool(name: str, args: dict[str, Any]) -> str:
    if name == "ollabridge.enroll.create":
        ttl = int(args.get("ttl_seconds") or 3600)
        tok = create_join_token(ttl_seconds=ttl)
        return json.dumps({"token": tok.token, "expires_at": tok.expires_at.isoformat()}, indent=2)

    if name == "ollabridge.runtimes.list":
        base = (args.get("base_url") or f"http://127.0.0.1:{settings.PORT}").rstrip("/")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/admin/runtimes", headers={"X-API-Key": (settings.API_KEYS.split(",")[0].strip())})
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    if name == "ollabridge.gateway.health":
        base = (args.get("base_url") or f"http://127.0.0.1:{settings.PORT}").rstrip("/")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/health")
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

    raise ValueError(f"unknown tool: {name}")
