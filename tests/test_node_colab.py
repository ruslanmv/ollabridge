"""PR 4 — Colab node preset helpers.

Covers the decisions the notebook delegates to ``node.colab``: runtime→env,
model selection-before-download, identity reuse across ephemeral runtimes,
capability manifest, log/heartbeat parsing, clean termination, and the
pair/connect command builders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ollabridge.node import colab


# ---- runtime selection ----------------------------------------------------

def test_plan_runtime_chat_uses_ollama_not_gen():
    plan = colab.plan_runtime("chat")
    assert plan.uses_ollama and not plan.uses_comfyui
    assert plan.gen_enabled is False
    assert plan.env["OLLABRIDGE_NODE_GEN_ENABLED"] == "false"


def test_plan_runtime_image_enables_comfyui_gen():
    plan = colab.plan_runtime("image", comfyui_url="http://127.0.0.1:8188/", workflows_dir="/wf")
    assert plan.uses_comfyui and plan.gen_enabled is True
    assert plan.env["OLLABRIDGE_NODE_GEN_ENABLED"] == "true"
    assert plan.env["OLLABRIDGE_COMFYUI_URL"] == "http://127.0.0.1:8188"
    assert plan.env["OLLABRIDGE_COMFYUI_WORKFLOWS_DIR"] == "/wf"


def test_apply_runtime_env_isolated():
    env: dict[str, str] = {}
    colab.apply_runtime_env(colab.plan_runtime("video"), environ=env)
    assert env["OLLABRIDGE_NODE_GEN_ENABLED"] == "true"


def test_invalid_runtime_rejected():
    with pytest.raises(ValueError):
        colab.plan_runtime("audio")


# ---- model selection ------------------------------------------------------

def test_select_chat_models_passthrough_dedup():
    sel = colab.select_models("chat", ["llama3.2:3b", "llama3.2:3b", " gemma3:4b "])
    assert sel.chat_models == ["llama3.2:3b", "gemma3:4b"]
    assert sel.ok


def test_select_image_models_validates_against_catalog():
    sel = colab.select_models("image", ["flux-schnell", "not-a-real-checkpoint", "ltx-video"])
    assert sel.gen_models == ["flux-schnell"]        # ltx-video is video, not image
    assert "not-a-real-checkpoint" in sel.unknown
    assert "ltx-video" in sel.unknown
    assert not sel.ok


def test_pull_chat_models_uses_injected_installer():
    pulled: list[str] = []
    out = colab.pull_chat_models(["a", "b"], ensure=lambda m: pulled.append(m))
    assert out == ["a", "b"] and pulled == ["a", "b"]


# ---- identity reuse -------------------------------------------------------

def _write_creds(path: Path) -> None:
    path.write_text(json.dumps({
        "cloud_url": "https://app.ollabridge.com",
        "device_id": "dev-1", "device_token": "tok",
    }))


def test_identity_status_and_stash_restore(tmp_path):
    local = tmp_path / "cloud_device.json"
    drive = tmp_path / "drive"

    assert colab.identity_status(path=local)["paired"] is False

    _write_creds(local)
    st = colab.identity_status(path=local)
    assert st["paired"] and st["device_id"] == "dev-1"

    # Stash to "drive", delete local, restore → same identity reused.
    assert colab.stash_identity(drive, path=local) == drive / "cloud_device.json"
    local.unlink()
    restored = colab.restore_identity(drive, path=local)
    assert restored == local
    assert colab.identity_status(path=local)["device_id"] == "dev-1"


def test_restore_never_overwrites_existing(tmp_path):
    local = tmp_path / "cloud_device.json"
    drive = tmp_path / "drive"
    drive.mkdir()
    _write_creds(drive / "cloud_device.json")
    _write_creds(local)
    # An existing local identity is preserved (returns None, no overwrite).
    assert colab.restore_identity(drive, path=local) is None


# ---- capability manifest --------------------------------------------------

def test_manifest_chat_lists_models():
    m = colab.capability_manifest("chat", chat_models=["llama3.2:3b"], node_id="colab-x")
    assert m["runtime"] == "chat" and m["capabilities"] == ["chat"]
    assert m["models"][0]["model_id"] == "llama3.2:3b"
    assert m["ephemeral"] is True


def test_manifest_image_uses_workflow_catalog():
    m = colab.capability_manifest("image", node_id="colab-x")
    # The bundled workflow set always advertises sd-txt2img as an image model.
    ids = {x["model_id"] for x in m["models"]}
    assert "sd-txt2img" in ids
    assert m["capabilities"] == ["image"]


# ---- logs / heartbeat -----------------------------------------------------

def test_tail_log_and_state(tmp_path):
    log = tmp_path / "connect.log"
    log.write_text("booting\nCloud device online\n")
    assert "online" in colab.tail_log(log, n=1).lower()
    assert colab.connection_state(log.read_text()) == "online"
    assert colab.connection_state("retry in 4s\nbackoff") == "reconnecting"
    assert colab.tail_log(tmp_path / "missing.log") == ""


# ---- clean termination ----------------------------------------------------

class _FakeProc:
    def __init__(self, alive=True, hang=False):
        self._alive = alive
        self._hang = hang
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        if not self._hang:
            self._alive = False

    def wait(self, timeout=None):
        if self._hang:
            raise TimeoutError()
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


def test_terminate_stops_live_and_kills_hung():
    live = _FakeProc(alive=True)
    hung = _FakeProc(alive=True, hang=True)
    dead = _FakeProc(alive=False)
    colab.terminate([live, hung, dead, None])
    assert live.terminated and not live.killed
    assert hung.killed          # escalated to SIGKILL on wait timeout
    assert not dead.terminated  # already-dead is left alone


# ---- command builders -----------------------------------------------------

def test_pair_and_connect_commands():
    assert colab.pair_command("https://app.ollabridge.com/") == [
        "ollabridge-node", "cloud-pair",
        "--cloud", "https://app.ollabridge.com", "--runtime", "http://127.0.0.1:11434",
    ]
    assert colab.connect_command() == [
        "ollabridge-node", "cloud-connect", "--runtime", "http://127.0.0.1:11434",
    ]
    assert "--cloud" in colab.connect_command("https://c")
    with pytest.raises(ValueError):
        colab.pair_command("")
