from __future__ import annotations

import shutil
import subprocess
import time
import os

import anyio
import httpx


def _has_public_link_client(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def start_tunnel(port: int) -> str:
    """Best-effort public access URL.

    Enterprise guidance: in production, use a managed edge or private overlay.

    For dev, this function can launch a user-provided "public link" client (any tool).
    Configure via:
      - OBRIDGE_PUBLIC_LINK_CMD (default: "ngrok")

    The client must expose a local status API compatible with "http://127.0.0.1:4040/api/tunnels".
    """
    cmd = os.environ.get("OBRIDGE_PUBLIC_LINK_CMD", "ngrok")
    if not _has_public_link_client(cmd):
        raise RuntimeError(
            "No public-link client found on PATH. Set OBRIDGE_PUBLIC_LINK_CMD or use a managed edge/private overlay."
        )

    subprocess.Popen([cmd, "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)

    async def _get_url() -> str:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("http://127.0.0.1:4040/api/tunnels")
            r.raise_for_status()
            data = r.json()
            for t in data.get("tunnels", []) or []:
                url = t.get("public_url")
                if url and url.startswith("https://"):
                    return url
        raise RuntimeError("No https tunnel found (check your public-link client status).")

    return anyio.run(_get_url)
