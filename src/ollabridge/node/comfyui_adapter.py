"""
ComfyUI adapter (Wave A — Batch 4 / LN-2).

Runs a routed ``images.generate`` / ``videos.generate`` job on a local ComfyUI
by submitting a workflow template, waiting for the result, and returning the
rendered bytes as a base64 ``Artifact`` (docs/contracts/jobs-protocol.md §1).

It adds **no new generation logic** — it invokes ComfyUI workflow JSON. The
small injection convention below lets the same templates HomePilot ships be
parameterised per request:

    Placeholder tokens (string values inside the workflow JSON):
        {{prompt}} {{negative_prompt}}            → text (substring substitution)
        {{seed}} {{width}} {{height}} {{steps}}   → integers (whole-value)
        {{num_frames}} {{fps}}                     → integers (whole-value)
        {{cfg}}                                     → float (whole-value)
        {{image}}                                   → input image ref (whole-value)

The HTTP/poll/fetch calls go through a small injectable ``client`` so the adapter
is unit-testable without a running ComfyUI.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from ollabridge.node import gen_config

logger = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[int, str], Any]]

_INT_KEYS = {"seed", "width", "height", "steps", "num_frames", "fps"}
_FLOAT_KEYS = {"cfg"}
_TEXT_KEYS = {"prompt", "negative_prompt", "image"}

_DEFAULTS: dict[str, Any] = {
    "negative_prompt": "",
    "width": 1024,
    "height": 1024,
    "steps": 20,
    "cfg": 7.0,
    "num_frames": 25,
    "fps": 8,
}


# ---------------------------------------------------------------------------
# Pure workflow loading + parameter injection (unit-testable)
# ---------------------------------------------------------------------------

def resolve_workflow_path(model: str) -> Path:
    entry = gen_config.MODEL_WORKFLOWS.get(model)
    if entry is None:
        raise ValueError(f"No workflow mapping for model '{model}'")
    path = gen_config.workflows_dir() / entry[0]
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found for model '{model}': {path}")
    return path


def load_workflow(model: str) -> dict:
    return json.loads(resolve_workflow_path(model).read_text())


def inject_params(workflow: Any, params: dict[str, Any]) -> Any:
    """Recursively substitute ``{{token}}`` placeholders with typed values.

    A string that is *exactly* a typed placeholder (e.g. ``"{{seed}}"``) becomes
    the typed value (int/float). Text placeholders substitute in place so they
    can appear inside a larger string.
    """
    merged = {**_DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    if "seed" not in merged or merged.get("seed") is None:
        merged["seed"] = random.randint(0, 2**31 - 1)
    return _walk(workflow, merged)


def _walk(node: Any, params: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: _walk(v, params) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, params) for v in node]
    if isinstance(node, str):
        return _substitute(node, params)
    return node


def _substitute(value: str, params: dict[str, Any]) -> Any:
    stripped = value.strip()
    # Whole-value typed placeholder, e.g. "{{seed}}" → int.
    if stripped.startswith("{{") and stripped.endswith("}}"):
        key = stripped[2:-2].strip()
        if key in _INT_KEYS:
            return int(params.get(key, 0))
        if key in _FLOAT_KEYS:
            return float(params.get(key, 0.0))
        if key in _TEXT_KEYS or key in params:
            return params.get(key, "")
    # Text substitution within a larger string.
    out = value
    for key in _TEXT_KEYS:
        token = "{{" + key + "}}"
        if token in out:
            out = out.replace(token, str(params.get(key, "")))
    return out


# ---------------------------------------------------------------------------
# Low-level ComfyUI HTTP client (the injectable seam)
# ---------------------------------------------------------------------------

class ComfyUIHttpClient:
    """Thin wrapper over ComfyUI's HTTP API (/prompt, /history, /view)."""

    def __init__(self, base_url: str, client_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id or f"ollabridge-{random.randint(1000, 9999)}"

    async def post_prompt(self, workflow: dict) -> str:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": self.client_id},
            )
            r.raise_for_status()
            return r.json()["prompt_id"]

    async def get_history(self, prompt_id: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base_url}/history/{prompt_id}")
            r.raise_for_status()
            return r.json()

    async def get_view(self, filename: str, subfolder: str, type_: str) -> tuple[bytes, str]:
        params = {"filename": filename, "subfolder": subfolder, "type": type_}
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(f"{self.base_url}/view", params=params)
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "application/octet-stream")


# ---------------------------------------------------------------------------
# High-level adapter
# ---------------------------------------------------------------------------

class ComfyUIAdapter:
    def __init__(self, client: ComfyUIHttpClient | None = None, *, poll_interval: float = 1.0):
        self.client = client or ComfyUIHttpClient(gen_config.comfyui_url())
        self.poll_interval = poll_interval

    async def generate(
        self, *, model: str, params: dict[str, Any], on_progress: ProgressCb = None,
        max_wait: float = 1800.0,
    ) -> dict:
        """Run a generation and return one ``Artifact`` dict (base64)."""
        await _emit(on_progress, 3, "loading workflow")
        workflow = inject_params(load_workflow(model), params)

        await _emit(on_progress, 8, "submitting to ComfyUI")
        prompt_id = await self.client.post_prompt(workflow)

        outputs = await self._await_outputs(prompt_id, on_progress, max_wait)
        image_ref = _first_image_ref(outputs)
        if image_ref is None:
            raise RuntimeError("ComfyUI produced no image/video output")

        await _emit(on_progress, 95, "fetching result")
        raw, ctype = await self.client.get_view(
            image_ref["filename"], image_ref.get("subfolder", ""), image_ref.get("type", "output"),
        )
        await _emit(on_progress, 100, "done")
        return {
            "b64": base64.b64encode(raw).decode(),
            "content_type": ctype,
            "filename": image_ref["filename"],
            "seed": params.get("seed"),
        }

    async def _await_outputs(self, prompt_id: str, on_progress: ProgressCb, max_wait: float) -> dict:
        deadline = time.monotonic() + max_wait
        pct = 10
        while time.monotonic() < deadline:
            history = await self.client.get_history(prompt_id)
            entry = history.get(prompt_id)
            if entry and entry.get("outputs"):
                return entry["outputs"]
            # Coarse progress while we wait (real ComfyUI /ws progress can be
            # wired in later without changing this contract).
            pct = min(90, pct + 5)
            await _emit(on_progress, pct, "generating")
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"ComfyUI job {prompt_id} did not complete within {max_wait}s")


def _first_image_ref(outputs: dict) -> dict | None:
    for node_output in outputs.values():
        for key in ("images", "gifs", "videos"):
            items = node_output.get(key)
            if items:
                return items[0]
    return None


async def _emit(on_progress: ProgressCb, pct: int, message: str) -> None:
    if on_progress is None:
        return
    try:
        result = on_progress(pct, message)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:  # noqa: BLE001
        logger.debug("progress callback raised: %s", exc)
