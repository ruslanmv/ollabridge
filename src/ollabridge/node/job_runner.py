"""
Generation job runner (Wave A — Batch 4 / LN-2).

Bridges a routed relay op (``images.generate`` / ``images.edit`` /
``videos.generate``) to the ComfyUI adapter and returns the ``res.data`` payload
the Cloud expects: ``{"artifacts": [Artifact, ...]}``.

The ``on_progress`` callback is invoked with ``(percent, message)`` so the agent
can forward ``{"type":"progress",...}`` frames over the existing relay tunnel.
"""

from __future__ import annotations

from typing import Any

from ollabridge.node.comfyui_adapter import ComfyUIAdapter, ProgressCb

# Relay op → ComfyUI is workflow-driven, so the op only selects which payload
# fields are relevant; the workflow itself encodes txt2img vs img2vid vs edit.
_PARAM_KEYS = (
    "prompt", "negative_prompt", "seed", "width", "height", "steps", "cfg",
    "num_frames", "fps", "image", "mask",
)


async def run_generation(
    op: str,
    payload: dict[str, Any],
    *,
    adapter: ComfyUIAdapter | None = None,
    on_progress: ProgressCb = None,
) -> dict:
    """Execute one generation op and return ``{"artifacts": [...]}``."""
    model = payload.get("model") or ""
    if not model:
        raise ValueError("generation request missing 'model'")

    params = {k: payload.get(k) for k in _PARAM_KEYS if payload.get(k) is not None}
    adapter = adapter or ComfyUIAdapter()
    artifact = await adapter.generate(model=model, params=params, on_progress=on_progress)
    return {"artifacts": [artifact]}


def is_generation_op(op: str | None) -> bool:
    return op in ("images.generate", "images.edit", "videos.generate")
