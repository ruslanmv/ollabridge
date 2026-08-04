"""
Colab node preset helpers (PR 4).

The Google Colab notebook is thin — the decisions it makes are here, as small
pure functions we can unit-test without a GPU, an Ollama, or a live Cloud:

  * choose the runtime (chat → Ollama, image/video → ComfyUI) and the env it
    implies (reusing ``gen_config``'s flags, no new CLI surface);
  * select models *before* downloading, validating generation models against the
    workflow catalog so a typo fails fast instead of after a 6 GB pull;
  * reuse a node identity across ephemeral runtimes by stashing/restoring the
    paired ``cloud_device.json`` (e.g. to Google Drive);
  * report a capability manifest for display/advertisement;
  * expose logs + a heartbeat read-out;
  * terminate background processes cleanly.

The notebook pairs and connects by shelling out to the existing
``ollabridge-node cloud-pair`` / ``cloud-connect`` CLI; ``pair_command`` /
``connect_command`` build those argv lists so the invocation is testable too.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ollabridge.cloud.device_config import (
    CloudDeviceCredentials,
    _default_path,
    load_cloud_device_credentials,
)
from ollabridge.node import gen_config

RUNTIMES = ("chat", "image", "video")
_DEFAULT_RUNTIME_URL = "http://127.0.0.1:11434"


# --------------------------------------------------------------------------- #
# 1. Runtime selection
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RuntimePlan:
    runtime: str          # "chat" | "image" | "video"
    uses_ollama: bool
    uses_comfyui: bool
    gen_enabled: bool
    env: dict[str, str] = field(default_factory=dict)


def normalize_runtime(runtime: str) -> str:
    r = (runtime or "").strip().lower()
    if r not in RUNTIMES:
        raise ValueError(f"runtime must be one of {RUNTIMES}, got {runtime!r}")
    return r


def plan_runtime(
    runtime: str,
    *,
    comfyui_url: Optional[str] = None,
    workflows_dir: Optional[str] = None,
) -> RuntimePlan:
    """Resolve the runtime and the environment it needs. Chat runs on Ollama;
    image/video run on ComfyUI and set the generation opt-in flag."""
    r = normalize_runtime(runtime)
    if r == "chat":
        return RuntimePlan(
            runtime=r, uses_ollama=True, uses_comfyui=False, gen_enabled=False,
            env={"OLLABRIDGE_NODE_GEN_ENABLED": "false"},
        )
    env = {"OLLABRIDGE_NODE_GEN_ENABLED": "true"}
    if comfyui_url:
        env["OLLABRIDGE_COMFYUI_URL"] = comfyui_url.rstrip("/")
    if workflows_dir:
        env["OLLABRIDGE_COMFYUI_WORKFLOWS_DIR"] = str(workflows_dir)
    return RuntimePlan(
        runtime=r, uses_ollama=False, uses_comfyui=True, gen_enabled=True, env=env,
    )


def apply_runtime_env(plan: RuntimePlan, environ: Optional[dict] = None) -> None:
    """Apply the plan's env (mutates ``os.environ`` unless another dict is given)."""
    import os
    target = environ if environ is not None else os.environ
    target.update(plan.env)


# --------------------------------------------------------------------------- #
# 2. Model selection (before downloading)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ModelSelection:
    runtime: str
    chat_models: list[str]         # to pull via Ollama
    gen_models: list[str]          # recognised generation models (workflow known)
    unknown: list[str]             # requested generation models with no workflow

    @property
    def ok(self) -> bool:
        return not self.unknown


def select_models(runtime: str, requested: Iterable[str]) -> ModelSelection:
    """Split the requested models by runtime and validate generation models
    against the workflow catalog — *without* downloading anything."""
    r = normalize_runtime(runtime)
    reqs = [m.strip() for m in requested if m and m.strip()]
    # de-dup, preserve order
    seen: set[str] = set()
    reqs = [m for m in reqs if not (m in seen or seen.add(m))]

    if r == "chat":
        return ModelSelection(runtime=r, chat_models=reqs, gen_models=[], unknown=[])

    known = set(gen_config.MODEL_WORKFLOWS)
    want_task = "image" if r == "image" else "video"
    gen, unknown = [], []
    for m in reqs:
        entry = gen_config.MODEL_WORKFLOWS.get(m)
        if entry is None or entry[1] != want_task:
            unknown.append(m)
        else:
            gen.append(m)
    return ModelSelection(runtime=r, chat_models=[], gen_models=gen, unknown=unknown)


def pull_chat_models(
    models: Iterable[str], *, ensure: Optional[Callable[[str], object]] = None
) -> list[str]:
    """Download the selected chat models (Ollama). ``ensure`` is injectable so
    tests don't hit the network; defaults to the real installer."""
    if ensure is None:
        from ollabridge.utils.installer import ensure_model as ensure
    pulled = []
    for m in models:
        ensure(m)
        pulled.append(m)
    return pulled


# --------------------------------------------------------------------------- #
# 3. Node identity reuse (across ephemeral Colab runtimes)
# --------------------------------------------------------------------------- #

def identity_status(*, path: Optional[Path] = None) -> dict:
    creds = load_cloud_device_credentials(path)
    return {
        "paired": creds is not None,
        "device_id": creds.device_id if creds else None,
        "cloud_url": creds.cloud_url if creds else None,
    }


def stash_identity(dest_dir: str | Path, *, path: Optional[Path] = None) -> Optional[Path]:
    """Copy the paired credential to a persistent location (e.g. Drive) so the
    next runtime can reuse the same device instead of re-pairing. Returns the
    destination path, or None if there's nothing to stash."""
    src = path or _default_path()
    if not Path(src).exists():
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "cloud_device.json"
    shutil.copy2(src, dest)
    try:
        dest.chmod(0o600)
    except Exception:
        pass
    return dest


def restore_identity(src_dir: str | Path, *, path: Optional[Path] = None) -> Optional[Path]:
    """Restore a stashed credential into place if none exists locally. Returns
    the restored path, or None if there was nothing to restore / one already
    exists (existing identity is never overwritten)."""
    dest = path or _default_path()
    if Path(dest).exists():
        return None
    src = Path(src_dir) / "cloud_device.json"
    if not src.exists():
        return None
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    try:
        Path(dest).chmod(0o600)
    except Exception:
        pass
    return Path(dest)


# --------------------------------------------------------------------------- #
# 4. Capability manifest (for display / advertisement)
# --------------------------------------------------------------------------- #

def capability_manifest(
    runtime: str,
    *,
    chat_models: Optional[Iterable[str]] = None,
    node_id: Optional[str] = None,
    platform: str = "colab",
) -> dict:
    """A human-readable manifest of what this node will advertise. Mirrors the
    ``node`` block the agent sends on connect (see ``capability_report``)."""
    r = normalize_runtime(runtime)
    if node_id is None:
        from ollabridge.node.agent import default_node_id
        node_id = default_node_id()

    if r == "chat":
        models = [
            {"model_id": m, "task": "chat", "runtime": "ollama"}
            for m in (chat_models or [])
        ]
    else:
        # Only generation models whose workflow file is actually present.
        want_task = "image" if r == "image" else "video"
        models = [
            m for m in _catalog_models() if m["task"] == want_task
        ]

    capabilities = sorted({m["task"] for m in models}) or [
        "chat" if r == "chat" else r
    ]
    return {
        "node_id": node_id,
        "platform": platform,
        "runtime": r,
        "ephemeral": True,
        "capabilities": capabilities,
        "models": models,
    }


def _catalog_models() -> list[dict]:
    """Generation models with a present workflow file (delegates to the node's
    own capability report so the two never drift)."""
    from ollabridge.node import capability_report
    return capability_report.image_video_models()


# --------------------------------------------------------------------------- #
# 5. Logs + heartbeat
# --------------------------------------------------------------------------- #

def tail_log(path: str | Path, n: int = 50) -> str:
    """Last ``n`` lines of a log file (empty string if missing/unreadable)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    return "\n".join(lines[-max(0, n):])


def connection_state(log_text: str) -> str:
    """Coarse connection state parsed from the connect log — for a heartbeat
    read-out in the notebook. Latest signal wins."""
    state = "starting"
    for line in log_text.splitlines():
        low = line.lower()
        if "cloud device online" in low or "online" in low and "offline" not in low:
            state = "online"
        elif "reconnect" in low or "backoff" in low or "retry" in low:
            state = "reconnecting"
        elif "disconnected" in low or "offline" in low:
            state = "offline"
    return state


# --------------------------------------------------------------------------- #
# 6. Clean termination
# --------------------------------------------------------------------------- #

def terminate(procs: Iterable[object], *, timeout: float = 5.0) -> None:
    """Terminate background processes cleanly (SIGTERM, then SIGKILL on timeout).
    Accepts anything with ``terminate``/``wait``/``kill`` (``subprocess.Popen``);
    exceptions from already-dead processes are ignored."""
    live = [p for p in procs if p is not None]
    for p in live:
        try:
            if getattr(p, "poll", lambda: None)() is None:
                p.terminate()
        except Exception:
            pass
    for p in live:
        try:
            p.wait(timeout=timeout)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# 7. Pair / connect command builders
# --------------------------------------------------------------------------- #

def pair_command(cloud: str, *, runtime_base_url: str = _DEFAULT_RUNTIME_URL) -> list[str]:
    """argv for ``ollabridge-node cloud-pair`` (device-code pairing)."""
    if not cloud:
        raise ValueError("cloud URL is required")
    return [
        "ollabridge-node", "cloud-pair",
        "--cloud", cloud.rstrip("/"),
        "--runtime", runtime_base_url,
    ]


def connect_command(
    cloud: Optional[str] = None, *, runtime_base_url: str = _DEFAULT_RUNTIME_URL
) -> list[str]:
    """argv for ``ollabridge-node cloud-connect`` (uses saved identity unless
    ``cloud`` is given to override)."""
    argv = ["ollabridge-node", "cloud-connect", "--runtime", runtime_base_url]
    if cloud:
        argv += ["--cloud", cloud.rstrip("/")]
    return argv
