from __future__ import annotations

import shutil
import subprocess
import time

import anyio
import httpx


def _has_ngrok() -> bool:
    return shutil.which("ngrok") is not None


def start_tunnel(port: int) -> str:
    """Best-effort ngrok tunnel.

    Requires ngrok installed and authenticated.
    Returns an https public URL or raises.
    """
    if not _has_ngrok():
        raise RuntimeError(
            "ngrok not found. Install ngrok + authenticate it, or use Cloudflare Tunnel/Tailscale."
        )

    subprocess.Popen(["ngrok", "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        raise RuntimeError("No https tunnel found (check ngrok auth/status).")

    return anyio.run(_get_url)
