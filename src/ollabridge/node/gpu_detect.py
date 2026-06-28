"""
Best-effort GPU detection (Wave A — Batch 2 / LN-1).

Returns ``{vendor, name, vram_mb}`` for the primary GPU, or ``None`` when no GPU
is detected. Pure best-effort: never raises, never blocks for long — a failure
just means the ``hello`` ``node`` block omits the GPU detail and the Cloud router
treats VRAM as unknown (neutral) rather than punishing the device.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional, TypedDict


class GpuInfo(TypedDict):
    vendor: str
    name: str
    vram_mb: Optional[int]


def detect_gpu() -> Optional[GpuInfo]:
    """Detect the primary GPU. Tries NVIDIA first, then Apple Silicon."""
    return _detect_nvidia() or _detect_apple()


def _detect_nvidia() -> Optional[GpuInfo]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    # First GPU line: "NVIDIA GeForce RTX 4090, 24564"
    first = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    name = parts[0] if parts else "NVIDIA GPU"
    vram_mb: Optional[int] = None
    if len(parts) > 1:
        try:
            vram_mb = int(float(parts[1]))
        except ValueError:
            vram_mb = None
    return {"vendor": "nvidia", "name": name, "vram_mb": vram_mb}


def _detect_apple() -> Optional[GpuInfo]:
    import platform

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    # Apple Silicon shares system RAM as unified memory; we report the chip
    # name and leave VRAM unknown rather than guessing a split.
    name = "Apple Silicon GPU"
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            name = out.stdout.strip()
    except Exception:
        pass
    return {"vendor": "apple", "name": name, "vram_mb": None}
