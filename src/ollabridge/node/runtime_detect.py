"""
Runtime detection (Wave A — Batch 2 / LN-1).

Probes the local runtimes a generation node might expose — ComfyUI and a local
HomePilot backend — and reports their reachability. Best-effort and fast: each
probe is short-timeout and failures are reported as ``status: "down"`` rather
than raised.
"""

from __future__ import annotations

import httpx

from ollabridge.node import gen_config


async def detect_runtimes() -> list[dict]:
    """Return runtime descriptors for the ``hello`` node block.

    Always includes a ComfyUI entry (up/down) so the Cloud can see *why* image
    capability is or isn't available; the HomePilot entry is included only when
    reachable, since it's optional.
    """
    runtimes: list[dict] = []

    comfy = gen_config.comfyui_url()
    runtimes.append({
        "kind": "comfyui",
        "endpoint": comfy,
        "status": "up" if await _probe(f"{comfy}/system_stats") else "down",
    })

    hp = gen_config.homepilot_url()
    if await _probe(f"{hp}/health") or await _probe(f"{hp}/api/health"):
        runtimes.append({"kind": "homepilot", "endpoint": hp, "status": "up"})

    return runtimes


async def comfyui_up() -> bool:
    """Convenience: is the local ComfyUI reachable right now?"""
    return await _probe(f"{gen_config.comfyui_url()}/system_stats")


async def _probe(url: str, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            return r.status_code < 500
    except Exception:
        return False
