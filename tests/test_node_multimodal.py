"""Wave A / Batches 2 + 4 (node) — capability report, ComfyUI adapter, runner."""

from __future__ import annotations

import base64

import pytest

from ollabridge.node import capability_report, gen_config
from ollabridge.node.comfyui_adapter import ComfyUIAdapter, inject_params, load_workflow
from ollabridge.node.job_runner import is_generation_op, run_generation


# ---- Batch 2: capability report ------------------------------------------

def test_bundled_workflow_advertises_sd_txt2img():
    models = capability_report.image_video_models()
    assert {"model_id": "sd-txt2img", "task": "image", "runtime": "comfyui"} in models


def test_node_block_includes_image_models_when_enabled(monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_NODE_GEN_ENABLED", "1")
    runtimes = [{"kind": "comfyui", "endpoint": "http://127.0.0.1:8188", "status": "up"}]
    block = capability_report.build_node_block(["llama3"], runtimes, "linux")

    tasks = {(m["model_id"], m["task"]) for m in block["node_models"]}
    assert ("llama3", "chat") in tasks
    assert ("sd-txt2img", "image") in tasks
    assert capability_report.extra_capabilities(runtimes) == ["image"]


def test_node_block_chat_only_when_disabled(monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_NODE_GEN_ENABLED", "0")
    runtimes = [{"kind": "comfyui", "endpoint": "http://127.0.0.1:8188", "status": "up"}]
    block = capability_report.build_node_block(["llama3"], runtimes, "linux")

    tasks = {m["task"] for m in block["node_models"]}
    assert tasks == {"chat"}  # no image/video advertised when disabled
    assert capability_report.extra_capabilities(runtimes) == []


def test_image_models_not_advertised_when_comfyui_down(monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_NODE_GEN_ENABLED", "1")
    runtimes = [{"kind": "comfyui", "endpoint": "x", "status": "down"}]
    assert capability_report.extra_capabilities(runtimes) == []


# ---- Batch 4: workflow injection -----------------------------------------

def test_inject_params_types_and_text():
    wf = load_workflow("sd-txt2img")
    out = inject_params(wf, {"prompt": "a red fox", "seed": 42, "width": 512, "steps": 10})

    sampler = out["3"]["inputs"]
    assert sampler["seed"] == 42 and isinstance(sampler["seed"], int)
    assert sampler["steps"] == 10
    assert isinstance(sampler["cfg"], float)  # default applied + typed
    assert out["5"]["inputs"]["width"] == 512
    assert out["6"]["inputs"]["text"] == "a red fox"
    assert out["7"]["inputs"]["text"] == ""  # negative prompt default


def test_inject_params_assigns_random_seed_when_missing():
    wf = load_workflow("sd-txt2img")
    out = inject_params(wf, {"prompt": "x"})
    assert isinstance(out["3"]["inputs"]["seed"], int)


# ---- Batch 4: adapter against a fake ComfyUI -----------------------------

class FakeComfyClient:
    def __init__(self):
        self.calls = 0

    async def post_prompt(self, workflow):
        assert workflow["6"]["inputs"]["text"] == "a cat"  # injected prompt arrived
        return "pid1"

    async def get_history(self, prompt_id):
        self.calls += 1
        if self.calls < 2:
            return {}  # not ready yet → exercises the polling/progress path
        return {prompt_id: {"outputs": {"9": {"images": [
            {"filename": "out.png", "subfolder": "", "type": "output"}]}}}}

    async def get_view(self, filename, subfolder, type_):
        return b"PNGDATA", "image/png"


@pytest.mark.asyncio
async def test_adapter_generate_returns_base64_artifact():
    progress = []
    adapter = ComfyUIAdapter(client=FakeComfyClient(), poll_interval=0.0)
    artifact = await adapter.generate(
        model="sd-txt2img",
        params={"prompt": "a cat", "seed": 7},
        on_progress=lambda pct, msg: progress.append(pct),
    )
    assert base64.b64decode(artifact["b64"]) == b"PNGDATA"
    assert artifact["content_type"] == "image/png"
    assert artifact["filename"] == "out.png"
    assert progress and progress[-1] == 100 and progress == sorted(progress)


# ---- Batch 4: job runner --------------------------------------------------

class FakeAdapter:
    async def generate(self, *, model, params, on_progress=None):
        if on_progress:
            on_progress(50, "half")
        return {"b64": base64.b64encode(b"X").decode(), "content_type": "image/png"}


def test_is_generation_op():
    assert is_generation_op("images.generate")
    assert is_generation_op("videos.generate")
    assert not is_generation_op("chat")


@pytest.mark.asyncio
async def test_run_generation_wraps_artifacts():
    data = await run_generation("images.generate", {"model": "sd-txt2img", "prompt": "x"},
                                adapter=FakeAdapter())
    assert "artifacts" in data and len(data["artifacts"]) == 1
    assert data["artifacts"][0]["content_type"] == "image/png"


@pytest.mark.asyncio
async def test_run_generation_requires_model():
    with pytest.raises(ValueError):
        await run_generation("images.generate", {"prompt": "x"}, adapter=FakeAdapter())
