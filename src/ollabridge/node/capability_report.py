"""
Capability report (Wave A — Batch 2 / LN-1).

Assembles the optional structured ``node`` block of the ``hello`` message
(docs/contracts/jobs-protocol.md §3, in the ollabridge-cloud repo) from:

  * detected GPU (``gpu_detect``),
  * detected runtimes (``runtime_detect``),
  * the node's chat models (the existing Ollama list), and
  * the image/video models whose ComfyUI workflow templates are present.

This is additive to the legacy flat ``models`` / ``capabilities`` arrays — the
Cloud reads the ``node`` block only when ``MULTIMODAL_RELAY_ENABLED``, and an
old Cloud simply ignores it.
"""

from __future__ import annotations

from ollabridge.node import gen_config
from ollabridge.node.gpu_detect import detect_gpu


def image_video_models() -> list[dict]:
    """The (model, task) entries this node can actually serve via ComfyUI —
    i.e. those in ``MODEL_WORKFLOWS`` whose workflow file exists on disk."""
    out: list[dict] = []
    wdir = gen_config.workflows_dir()
    for model_id, (filename, task) in gen_config.MODEL_WORKFLOWS.items():
        if (wdir / filename).exists():
            out.append({"model_id": model_id, "task": task, "runtime": "comfyui"})
    return out


def extra_capabilities(runtimes: list[dict]) -> list[str]:
    """Flat-array capability additions (``image``/``video``) for the hello,
    only when generation is enabled, ComfyUI is up, and workflows exist."""
    if not gen_config.gen_enabled() or not _comfyui_up(runtimes):
        return []
    tasks = {m["task"] for m in image_video_models()}
    caps: list[str] = []
    if "image" in tasks:
        caps.append("image")
    if "video" in tasks:
        caps.append("video")
    return caps


def build_node_block(
    ollama_models: list[str], runtimes: list[dict], platform: str
) -> dict:
    """Build the structured ``node`` block.

    Image/video models are advertised only when generation is enabled *and*
    ComfyUI is reachable, so the Cloud never routes a generation job to a node
    that can't currently serve it.
    """
    node_models: list[dict] = [
        {"model_id": m, "task": "chat", "runtime": "ollama"} for m in ollama_models
    ]
    if gen_config.gen_enabled() and _comfyui_up(runtimes):
        node_models.extend(image_video_models())

    gpu = detect_gpu()
    block: dict = {
        "platform": platform,
        "runtimes": runtimes,
        "node_models": node_models,
    }
    if gpu is not None:
        block["gpu"] = gpu
    return block


def _comfyui_up(runtimes: list[dict]) -> bool:
    return any(r.get("kind") == "comfyui" and r.get("status") == "up" for r in runtimes)
