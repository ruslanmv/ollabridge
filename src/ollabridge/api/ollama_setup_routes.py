"""``/admin/ollama-setup/*`` — backend for the dashboard's "Set up Ollama" wizard.

Additive: nothing here changes how the gateway talks to Ollama. It answers the
questions a browser cannot answer about the machine the gateway runs on:

* **status** — is the ``ollama`` binary present, is the service listening at
  the configured URL (and if not there, somewhere nearby such as
  ``127.0.0.1`` instead of ``localhost``, or the Windows host seen from WSL),
  and can *this* process install or start it.
* **install** — run the platform's official installer as a background job
  with a live log (``winget`` on Windows, Homebrew on macOS, the official
  ``install.sh`` on Linux). Only these fixed commands are ever run.
* **start** — launch ``ollama serve`` detached and wait until it answers.
* **pull** — fetch a first model through the local catalog's pull manager,
  against the URL the runtime actually uses.

Everything sits behind ``require_api_key`` like every other admin route. The
wizard never installs anything without a click from the dashboard, and when
the process cannot do it (inside a container, no passwordless sudo, no
package manager) the status says why and hands over the exact command.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ollabridge.core import runtime_settings as rts
from ollabridge.core.security import require_api_key
from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge.ollama_setup")

router = APIRouter(prefix="/admin/ollama-setup", tags=["ollama-setup"])

OLLAMA_PORT = 11434
DOWNLOAD_PAGE = {
    "windows": "https://ollama.com/download/windows",
    "darwin": "https://ollama.com/download/mac",
    "linux": "https://ollama.com/download/linux",
}
LINUX_INSTALL_SCRIPT = "curl -fsSL https://ollama.com/install.sh | sh"
WINGET_INSTALL = [
    "winget", "install", "--id", "Ollama.Ollama", "-e", "--silent",
    "--accept-source-agreements", "--accept-package-agreements",
]
BREW_INSTALL = "brew install ollama && brew services start ollama"

#: Small, well-known models a first-time user can pull in minutes. Sizes are
#: the published download sizes, rounded; shown as guidance, never enforced.
SUGGESTED_MODELS = [
    {"id": "llama3.2:3b", "label": "Llama 3.2 3B", "size": "2.0 GB",
     "note": "Fast on any laptop; a good first model"},
    {"id": "qwen2.5:7b", "label": "Qwen2.5 7B", "size": "4.7 GB",
     "note": "Strong general assistant, multilingual"},
    {"id": "deepseek-r1:8b", "label": "DeepSeek-R1 8B", "size": "4.9 GB",
     "note": "Step-by-step reasoning"},
]

#: Install locations checked when ``ollama`` is not on this process's PATH —
#: a gateway started before the install never sees the updated PATH.
KNOWN_BINARY_PATHS = {
    "windows": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe",
    ],
    "darwin": [
        Path("/opt/homebrew/bin/ollama"),
        Path("/usr/local/bin/ollama"),
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
    ],
    "linux": [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")],
}

JOB_TIMEOUT_S = 30 * 60
START_WAIT_S = 12.0


# ── environment ────────────────────────────────────────────────────────────


def _platform() -> str:
    name = platform.system().lower()
    return name if name in ("windows", "darwin", "linux") else name or "unknown"


def _platform_label() -> str:
    name = _platform()
    if name == "windows":
        return "Windows"
    if name == "darwin":
        return "macOS"
    if name == "linux":
        label = "Linux"
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if line.startswith("PRETTY_NAME="):
                    label = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
        return f"{label} (WSL)" if _in_wsl() else label
    return name


def _in_wsl() -> bool:
    if _platform() != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return "microsoft" in platform.release().lower()


def _in_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return "docker" in cgroup or "containerd" in cgroup or "kubepods" in cgroup


def _parse_default_gateway(proc_net_route: str) -> Optional[str]:
    """IPv4 default gateway from ``/proc/net/route`` (little-endian hex)."""
    for line in proc_net_route.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            try:
                raw = int(parts[2], 16)
            except ValueError:
                continue
            return ".".join(str((raw >> shift) & 0xFF) for shift in (0, 8, 16, 24))
    return None


def _wsl_host_ip() -> Optional[str]:
    """The Windows host as seen from a WSL2 VM.

    The default gateway is the host's vEthernet address. The resolver in
    ``/etc/resolv.conf`` used to be the same address, but with DNS tunnelling
    (WSL 2.x) it is a tunnel endpoint such as 10.255.255.254, so it is only
    the fallback.
    """
    try:
        gw = _parse_default_gateway(Path("/proc/net/route").read_text(encoding="utf-8"))
        if gw:
            return gw
    except OSError:
        pass
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver" and parts[1] not in ("127.0.0.1", "::1"):
                return parts[1]
    except OSError:
        pass
    return None


def _which_ollama() -> Optional[str]:
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in KNOWN_BINARY_PATHS.get(_platform(), []):
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _binary_version(path: str) -> Optional[str]:
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=8
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip()
    # "ollama version is 0.6.2" / "Warning: ... \nollama version is 0.6.2"
    for token in reversed(text.replace("\n", " ").split()):
        if token and token[0].isdigit():
            return token
    return text or None


def _can_sudo_without_password() -> bool:
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # type: ignore[attr-defined]
        return True
    if not shutil.which("sudo"):
        return False
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _candidate_urls(configured: str, *, in_wsl: bool, in_docker: bool) -> list[dict[str, str]]:
    """Addresses worth trying when the configured one does not answer.

    ``localhost`` can resolve to ``::1`` while Ollama listens on IPv4 only;
    from a WSL2 VM the Windows host is the resolver address; from a container
    it is ``host.docker.internal`` or the bridge gateway.
    """
    out: list[dict[str, str]] = []
    seen = {configured.rstrip("/")}

    def add(url: str, label: str) -> None:
        if url not in seen:
            seen.add(url)
            out.append({"url": url, "label": label})

    if "localhost" in configured:
        add(configured.replace("localhost", "127.0.0.1").rstrip("/"), "IPv4 loopback")
    if in_wsl:
        ip = _wsl_host_ip()
        if ip:
            add(f"http://{ip}:{OLLAMA_PORT}", "Windows host (from WSL)")
    if in_docker:
        add(f"http://host.docker.internal:{OLLAMA_PORT}", "Container host")
        add(f"http://172.17.0.1:{OLLAMA_PORT}", "Docker bridge gateway")
    return out


async def _probe(url: str, timeout: float = 2.5) -> dict[str, Any]:
    """``GET /api/tags`` — the cheapest call that proves Ollama is Ollama."""
    base = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{base}/api/tags")
    except httpx.ConnectError:
        return {"url": base, "reachable": False, "models": [], "message": "Connection refused"}
    except httpx.TimeoutException:
        return {"url": base, "reachable": False, "models": [], "message": "Timed out"}
    except httpx.HTTPError as exc:
        return {"url": base, "reachable": False, "models": [], "message": str(exc)}
    if r.status_code != 200:
        return {"url": base, "reachable": False, "models": [], "message": f"HTTP {r.status_code}"}
    try:
        names = [m.get("name") for m in (r.json().get("models") or []) if m.get("name")]
    except ValueError:
        return {"url": base, "reachable": False, "models": [], "message": "Not an Ollama server"}
    return {"url": base, "reachable": True, "models": names, "message": f"{len(names)} model(s)"}


def _install_plan(*, system: str, in_docker: bool) -> dict[str, Any]:
    """What installing looks like here, and whether this process may do it."""
    plan: dict[str, Any] = {
        "method": "download",
        "display_command": "",
        "download_url": DOWNLOAD_PAGE.get(system, "https://ollama.com/download"),
        "can_run_here": False,
        "reason": "",
        "_argv": None,
        "_shell": None,
    }
    if in_docker:
        plan["reason"] = (
            "This gateway runs inside a container. Install Ollama on the host and "
            "point the gateway at it (for example http://host.docker.internal:11434)."
        )
        return plan
    if system == "windows":
        plan["display_command"] = "winget install --id Ollama.Ollama -e"
        if shutil.which("winget"):
            plan.update(method="winget", can_run_here=True, _argv=WINGET_INSTALL)
        else:
            plan["reason"] = "winget is not available to this process; use the installer download."
        return plan
    if system == "darwin":
        plan["display_command"] = BREW_INSTALL
        if shutil.which("brew"):
            plan.update(method="brew", can_run_here=True, _shell=BREW_INSTALL)
        else:
            plan["reason"] = "Homebrew is not installed; use the macOS download."
        return plan
    if system == "linux":
        plan["display_command"] = LINUX_INSTALL_SCRIPT
        if not shutil.which("curl"):
            plan["reason"] = "curl is not installed; run the command in a terminal after installing it."
        elif not _can_sudo_without_password():
            plan["reason"] = (
                "The installer needs an administrator password, which this process "
                "cannot type. Run the command in a terminal; it takes under a minute."
            )
        else:
            plan.update(method="script", can_run_here=True, _shell=LINUX_INSTALL_SCRIPT)
        return plan
    plan["reason"] = "Unsupported platform; install Ollama manually."
    return plan


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


# ── background jobs ───────────────────────────────────────────────────────


@dataclass
class SetupJob:
    id: str
    kind: str
    display_command: str
    status: str = "running"  # running | succeeded | failed
    exit_code: Optional[int] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    lines: deque = field(default_factory=lambda: deque(maxlen=400))

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "command": self.display_command,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "lines": list(self.lines),
        }


def _jobs(request: Request) -> dict[str, SetupJob]:
    store = getattr(request.app.state, "ollama_setup_jobs", None)
    if store is None:
        store = {}
        request.app.state.ollama_setup_jobs = store
    return store


def _run_job(job: SetupJob, *, argv: Optional[list[str]], shell: Optional[str]) -> None:
    """Thread body: stream merged stdout/stderr into the job, then finish it.

    A plain thread rather than an asyncio subprocess so it behaves the same
    under uvicorn's loop, Windows' Proactor loop and the test client's portal.
    """
    popen_kwargs: dict[str, Any] = dict(
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
    )
    try:
        if shell is not None:
            proc = subprocess.Popen(shell, shell=True, **popen_kwargs)
        else:
            proc = subprocess.Popen(argv or [], **popen_kwargs)
    except OSError as exc:
        job.status, job.error = "failed", f"could not start: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        return

    deadline = time.monotonic() + JOB_TIMEOUT_S
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if line:
                job.lines.append(line)
            if time.monotonic() > deadline:
                proc.kill()
                job.error = f"timed out after {JOB_TIMEOUT_S // 60} minutes"
                break
        code = proc.wait(timeout=60)
    except Exception as exc:  # noqa: BLE001 - the job records its own failure
        job.error = str(exc)
        code = -1
    job.exit_code = code
    job.status = "succeeded" if code == 0 and not job.error else "failed"
    job.finished_at = datetime.now(timezone.utc)
    log.info("ollama-setup %s job %s finished: %s (exit %s)", job.kind, job.id, job.status, code)


def _start_job(store: dict[str, SetupJob], *, kind: str, display: str,
               argv: Optional[list[str]] = None, shell: Optional[str] = None) -> SetupJob:
    for other in store.values():
        if other.status == "running":
            raise HTTPException(409, f"A {other.kind} job is already running ({other.id}).")
    job = SetupJob(id=uuid.uuid4().hex[:12], kind=kind, display_command=display)
    store[job.id] = job
    threading.Thread(
        target=_run_job, args=(job,), kwargs={"argv": argv, "shell": shell},
        name=f"ollama-setup-{job.id}", daemon=True,
    ).start()
    return job


def _spawn_detached(argv: list[str]) -> None:
    """Start a long-lived process that outlives this request (and the gateway)."""
    kwargs: dict[str, Any] = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)


# ── routes ────────────────────────────────────────────────────────────────


class PullBody(BaseModel):
    model: str


@router.get("/status")
async def setup_status(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """Everything the wizard needs to pick its first screen."""
    system = _platform()
    in_wsl, in_docker = _in_wsl(), _in_docker()
    configured = rts.ollama_base_url()

    binary_path = await asyncio.to_thread(_which_ollama)
    version = await asyncio.to_thread(_binary_version, binary_path) if binary_path else None

    candidates_meta = _candidate_urls(configured, in_wsl=in_wsl, in_docker=in_docker)
    probes = await asyncio.gather(_probe(configured), *(_probe(c["url"]) for c in candidates_meta))
    service, candidate_probes = probes[0], probes[1:]
    candidates = [
        {**meta, "reachable": p["reachable"], "models": len(p["models"]), "message": p["message"]}
        for meta, p in zip(candidates_meta, candidate_probes)
    ]
    plan = await asyncio.to_thread(_install_plan, system=system, in_docker=in_docker)

    if service["reachable"]:
        recommended = "ready" if service["models"] else "pull"
    elif any(c["reachable"] for c in candidates):
        recommended = "connect"
    elif binary_path:
        recommended = "start"
    elif plan["can_run_here"]:
        recommended = "install"
    else:
        recommended = "manual"

    default_model = rts.get("default_model", settings.DEFAULT_MODEL)
    suggested = list(SUGGESTED_MODELS)
    if default_model and default_model not in {m["id"] for m in suggested}:
        suggested.insert(0, {"id": default_model, "label": default_model, "size": "",
                             "note": "Your configured default model"})

    return {
        "platform": system,
        "platform_label": _platform_label(),
        "in_wsl": in_wsl,
        "in_docker": in_docker,
        "binary": {"found": bool(binary_path), "path": binary_path, "version": version},
        "service": {**service, "models": len(service["models"]),
                    "model_names": service["models"][:50]},
        "candidates": candidates,
        "install": _public_plan(plan),
        "recommended": recommended,
        "settings": {
            "ollama_base_url": configured,
            "local_runtime_enabled": bool(rts.get("local_runtime_enabled", True)),
            "default_model": default_model,
        },
        "suggested_models": suggested,
    }


@router.post("/install")
async def setup_install(request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
    """Run the official installer for this platform as a background job."""
    if await asyncio.to_thread(_which_ollama):
        raise HTTPException(409, "Ollama is already installed; start it instead.")
    plan = await asyncio.to_thread(_install_plan, system=_platform(), in_docker=_in_docker())
    if not plan["can_run_here"]:
        raise HTTPException(422, plan["reason"] or "This process cannot install Ollama here.")
    job = _start_job(_jobs(request), kind="install", display=plan["display_command"],
                     argv=plan["_argv"], shell=plan["_shell"])
    log.info("ollama-setup install job %s started: %s", job.id, plan["display_command"])
    return job.snapshot()


@router.get("/jobs/{job_id}")
async def setup_job(job_id: str, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job.snapshot()


@router.post("/start")
async def setup_start(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """Launch ``ollama serve`` detached and wait for it to answer."""
    url = rts.ollama_base_url()
    first = await _probe(url)
    if first["reachable"]:
        return {"ok": True, "reachable": True, "url": url, "already_running": True,
                "models": len(first["models"]), "waited_ms": 0}
    binary_path = await asyncio.to_thread(_which_ollama)
    if not binary_path:
        raise HTTPException(422, "Ollama is not installed on this machine.")
    try:
        await asyncio.to_thread(_spawn_detached, [binary_path, "serve"])
    except OSError as exc:
        raise HTTPException(500, f"Could not start Ollama: {exc}") from exc

    t0 = time.monotonic()
    probe = first
    while time.monotonic() - t0 < START_WAIT_S:
        await asyncio.sleep(0.5)
        probe = await _probe(url, timeout=1.5)
        if probe["reachable"]:
            break
    waited = int((time.monotonic() - t0) * 1000)
    return {
        "ok": probe["reachable"],
        "reachable": probe["reachable"],
        "url": url,
        "already_running": False,
        "models": len(probe["models"]),
        "waited_ms": waited,
        "message": "Ollama is up" if probe["reachable"] else
        f"Started `ollama serve` but {url} did not answer within {int(START_WAIT_S)}s: {probe['message']}",
    }


def _pull_manager(request: Request):
    pulls = getattr(request.app.state, "local_catalog_pulls", None)
    if pulls is None:
        raise HTTPException(503, "Local catalog not initialised; pull from a terminal with `ollama pull <model>`.")
    return pulls


def _progress_dict(progress: Any) -> dict[str, Any]:
    return {
        "model": progress.external_model_id,
        "status": progress.status,
        "progress_pct": progress.progress_pct,
        "total_bytes": progress.total_bytes,
        "completed_bytes": progress.completed_bytes,
        "error": progress.error,
    }


@router.post("/pull")
async def setup_pull(body: PullBody, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
    """Pull a first model against the URL the runtime actually uses."""
    from ollabridge.addons.local_catalog.client import LocalRuntimeClient

    model = (body.model or "").strip()
    if not model:
        raise HTTPException(422, "model is required")
    pulls = _pull_manager(request)
    client = LocalRuntimeClient(base_url=rts.ollama_base_url())
    progress = await pulls.start(node_id=settings.LOCAL_NODE_ID or "local",
                                 external_model_id=model, client=client)
    return _progress_dict(progress)


@router.get("/pull/{model:path}")
async def setup_pull_status(model: str, request: Request, _key: str = Depends(require_api_key)) -> dict[str, Any]:
    pulls = _pull_manager(request)
    progress = pulls.get(settings.LOCAL_NODE_ID or "local", model)
    if progress is None:
        raise HTTPException(404, "No pull in progress for this model")
    return _progress_dict(progress)
