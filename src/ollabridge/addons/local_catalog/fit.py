"""
"Recommended for this PC": which Ollama models fit this machine.

Optional and off by default. Nothing in this module runs, and nothing is
fetched, until the user turns recommendations on (``set_enabled(True)``).

The data and the arithmetic are FitLab's (https://github.com/ruslanmv/fitlab):

- the model registry is the ``registry.json`` its Hugging Face Space
  publishes weekly, cached here for a day;
- :func:`estimate` is FitLab's deterministic memory estimate (weights + KV
  cache + runtime overhead), kept identical to ``fitlab.estimate.fit`` so a
  verdict here matches the FitLab leaderboard for the same hardware;
- the order is FitLab's: most liked first, among the models that fit.

The hardware is detected on this machine and never leaves it: the only
request is a plain download of the public registry file.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from ollabridge.core.paths import data_dir

logger = logging.getLogger(__name__)

REGISTRY_URLS = (
    "https://ruslanmv-fitlab.static.hf.space/registry.json",
    "https://huggingface.co/spaces/ruslanmv/fitlab/resolve/main/registry.json",
    "https://raw.githubusercontent.com/ruslanmv/fitlab/registry-latest/data/registry.json",
)
REGISTRY_TTL_S = 24 * 3600

# FitLab's constants (fitlab/estimate.py). Change them only together with FitLab.
BITS_PER_WEIGHT = {"Q4_K_M": 4.85, "Q8_0": 8.5}
WEIGHTS_OVERHEAD = 1.03
KV_BYTES = 2
RUNTIME_GB = 0.9
TIGHT, OFFLOAD = 0.92, 1.6

# What an untuned `ollama pull` gives you: the Q4_K_M build. 8K is FitLab's default context.
QUANT = "Q4_K_M"
CONTEXT = 8192
# Without a GPU a model runs from system memory; leave room for everything else.
CPU_MEMORY_SHARE = 0.6

_SETTINGS_FILE = "model_library.json"
_REGISTRY_FILE = "fitlab_registry.json"


# ── The opt-in switch ───────────────────────────────────────────────────


def _settings_path() -> Path:
    return data_dir() / _SETTINGS_FILE


def is_enabled() -> bool:
    """Off unless the user turned it on in the UI, or ``OBRIDGE_FITLAB_RECOMMENDATIONS``
    sets the default for a machine that never chose."""
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
        if isinstance(saved.get("recommendations_enabled"), bool):
            return saved["recommendations_enabled"]
    except (OSError, ValueError, AttributeError):
        pass
    return os.environ.get("OBRIDGE_FITLAB_RECOMMENDATIONS", "").strip().lower() in ("1", "true", "yes", "on")


def set_enabled(enabled: bool) -> bool:
    path = _settings_path()
    path.write_text(json.dumps({"recommendations_enabled": bool(enabled)}, indent=2), encoding="utf-8")
    return bool(enabled)


# ── This machine ──────────────────────────────────────────────────────


def _run(*command: str) -> str:
    try:
        done = subprocess.run(command, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _system_memory_gb() -> float:
    try:
        if platform.system() == "Windows":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
            return round(status.ullTotalPhys / 1e9, 1)
        if platform.system() == "Darwin":
            return round(int(_run("sysctl", "-n", "hw.memsize") or 0) / 1e9, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (OSError, ValueError, AttributeError):
        return 0.0


def detect_hardware() -> dict[str, Any]:
    """This machine as the recommender sees it: ``kind`` (nvidia | apple | cpu),
    its name, and the memory a model has to fit in (``budget_gb``)."""
    ram = _system_memory_gb()
    gpu = _run("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits")
    if gpu:
        try:
            name, memory_mib = (part.strip() for part in gpu.splitlines()[0].split(","))
            vram = round(float(memory_mib) / 1024, 1)
            if vram > 0:
                return {
                    "kind": "nvidia", "name": name, "vram_gb": vram, "ram_gb": ram,
                    "budget_gb": vram, "budget": "GPU memory",
                }
        except ValueError:
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        chip = _run("sysctl", "-n", "machdep.cpu.brand_string") or "Apple Silicon"
        usable = round(ram * 0.7, 1)  # FitLab: Metal can use about 70% of unified memory
        return {
            "kind": "apple", "name": chip, "vram_gb": usable, "ram_gb": ram,
            "budget_gb": usable, "budget": "unified memory",
        }
    return {
        "kind": "cpu", "name": platform.processor() or platform.machine() or "CPU",
        "vram_gb": 0.0, "ram_gb": ram,
        "budget_gb": round(ram * CPU_MEMORY_SHARE, 1), "budget": "system memory (no GPU found)",
    }


# ── FitLab's estimate ───────────────────────────────────────────────────


def estimate(model: dict[str, Any], budget_gb: float, *, quant: str = QUANT, context: int = CONTEXT) -> dict[str, Any]:
    """Memory a model needs and whether it fits ``budget_gb``.

    The verdicts are FitLab's: ``fits``, ``tight`` (within 8% of the limit),
    ``offload`` (spills over, slower), ``no``.
    """
    arch = model["arch"]
    weights = model["params_b"] * BITS_PER_WEIGHT[quant] / 8 * WEIGHTS_OVERHEAD
    kv_cache = 2 * arch["n_layers"] * arch["n_kv_heads"] * arch["head_dim"] * context * KV_BYTES / 1e9
    needed = weights + kv_cache + RUNTIME_GB
    if needed <= budget_gb * TIGHT:
        verdict = "fits"
    elif needed <= budget_gb:
        verdict = "tight"
    elif needed <= budget_gb * OFFLOAD:
        verdict = "offload"
    else:
        verdict = "no"
    return {"est_gb": round(needed, 2), "verdict": verdict}


def recommend(registry: dict[str, Any], hardware: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    """The registry's Ollama models that fit this machine, most liked first."""
    budget = float(hardware.get("budget_gb") or 0)
    if budget <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for model in (registry.get("models") or {}).values():
        tag = model.get("ollama_tag")
        if not tag or model.get("status") == "stale":
            continue
        try:
            fit = estimate(model, budget)
        except (KeyError, TypeError):
            continue  # an entry without the numbers the estimate needs
        if fit["verdict"] not in ("fits", "tight"):
            continue
        stats = model.get("hf_stats") or {}
        rows.append(
            {
                "id": model.get("id"),
                "ollama_tag": tag,
                "hf_id": model.get("hf_id"),
                "params_b": model.get("params_b"),
                "capabilities": model.get("capabilities") or [],
                "license": model.get("license"),
                "likes": int(stats.get("likes") or 0),
                **fit,
            }
        )
    rows.sort(key=lambda row: (-row["likes"], row["est_gb"], row["ollama_tag"]))
    return rows[:limit]


# ── The registry ─────────────────────────────────────────────────────────


def _registry_urls() -> tuple[str, ...]:
    override = os.environ.get("OBRIDGE_FITLAB_REGISTRY_URL", "").strip()
    return (override, *REGISTRY_URLS) if override else REGISTRY_URLS


async def load_registry(
    *, refresh: bool = False, transport: Optional[httpx.AsyncBaseTransport] = None
) -> tuple[dict[str, Any], str]:
    """The FitLab registry and where it came from: ``cache``, ``live`` or ``stale-cache``.

    Raises ``RuntimeError`` when it was never downloaded and cannot be now.
    """
    cached = data_dir() / _REGISTRY_FILE
    if not refresh and cached.exists() and time.time() - cached.stat().st_mtime < REGISTRY_TTL_S:
        try:
            return json.loads(cached.read_text(encoding="utf-8")), "cache"
        except (OSError, ValueError):
            pass
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, transport=transport) as client:
        for url in _registry_urls():
            try:
                response = await client.get(url)
                response.raise_for_status()
                registry = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("fitlab registry %s failed: %s", url, exc)
                continue
            if isinstance(registry, dict) and registry.get("models"):
                cached.write_text(json.dumps(registry), encoding="utf-8")
                return registry, "live"
    if cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8")), "stale-cache"
        except (OSError, ValueError):
            pass
    raise RuntimeError("The FitLab registry could not be downloaded.")
