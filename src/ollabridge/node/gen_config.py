"""
Generation-runner configuration (Wave A — Batch 0).

All multimodal generation on the local node is gated behind
``OLLABRIDGE_NODE_GEN_ENABLED`` (default off). With it off the node advertises
and serves exactly what it does today — chat/embeddings/models over the Cloud
relay — and never reports image/video capability or accepts generation ops.

Everything here is read from the environment so it composes with the existing
``cloud-connect`` CLI without new flags.
"""

from __future__ import annotations

import os
from pathlib import Path


def gen_enabled() -> bool:
    """True when this node may advertise + serve image/video generation."""
    return os.environ.get("OLLABRIDGE_NODE_GEN_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def comfyui_url() -> str:
    """Base URL of the local ComfyUI instance."""
    return os.environ.get("OLLABRIDGE_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")


def homepilot_url() -> str:
    """Base URL of the local HomePilot backend (probed for runtime detection)."""
    return os.environ.get("OLLABRIDGE_HOMEPILOT_URL", "http://127.0.0.1:8001").rstrip("/")


def workflows_dir() -> Path:
    """Directory of ComfyUI workflow templates.

    Defaults to the small bundled set next to this module. Point
    ``OLLABRIDGE_COMFYUI_WORKFLOWS_DIR`` at adapted copies of HomePilot's
    ``comfyui/workflows`` to light up flux/sdxl/ltx/wan models — see
    ``comfyui_adapter`` for the placeholder convention.
    """
    env = os.environ.get("OLLABRIDGE_COMFYUI_WORKFLOWS_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).parent / "workflows"


# model id → (workflow filename, task). Operators supplying real HomePilot
# workflows get the richer set; the bundled set ships only ``sd-txt2img`` so a
# fresh install advertises at least one image model for the proof gate.
MODEL_WORKFLOWS: dict[str, tuple[str, str]] = {
    "sd-txt2img": ("txt2img.json", "image"),
    "flux-schnell": ("txt2img-flux-schnell.json", "image"),
    "flux-dev": ("txt2img-flux-dev.json", "image"),
    "sdxl": ("txt2img-sdxl.json", "image"),
    "sdxl-base": ("txt2img-sdxl.json", "image"),
    "ltx-video": ("img2vid-ltx.json", "video"),
    "wan-video": ("img2vid-wan.json", "video"),
}
