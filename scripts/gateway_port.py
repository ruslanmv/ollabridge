#!/usr/bin/env python3
"""Port helper for `make start` / `make stop` / `make restart`.

    gateway_port.py pick [PORT]   print PORT when it is free, else the next free port (PORT+1 …
                                  PORT+20); says on stderr who holds PORT, and how to free it
    gateway_port.py stop [PORT]   stop the OllaBridge gateway listening on PORT — only an
                                  OllaBridge process, never another program — and wait for it
    gateway_port.py who  [PORT]   print "<pid> <command>" of the listener on PORT (empty if free)

Standard library only (no psutil): `ss` or `lsof` on Linux, macOS and WSL; `netstat` on Windows.
"""
from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time

DEFAULT_PORT = 11435
SEARCH = 20


def port_free(port: int) -> bool:
    """True when nothing listens on ``port`` (on any interface, as the gateway binds 0.0.0.0)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def listener_pids(port: int) -> list[int]:
    """Process ids listening on ``port`` (best effort; empty when none or unknown)."""
    pids: set[int] = set()
    out = _run(["ss", "-ltnpH", f"sport = :{port}"])
    pids.update(int(p) for p in re.findall(r"pid=(\d+)", out))
    if not pids:
        out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
        pids.update(int(p) for p in out.split() if p.isdigit())
    if not pids and os.name == "nt":
        for line in _run(["netstat", "-ano", "-p", "TCP"]).splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING" and parts[4].isdigit():
                pids.add(int(parts[4]))
    return sorted(pids)


def command_of(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        pass
    out = _run(["ps", "-o", "command=", "-p", str(pid)]).strip()
    if out:
        return out
    if os.name == "nt":
        return _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]).strip()
    return ""


def is_ollabridge(cmd: str) -> bool:
    return "ollabridge" in cmd.lower()


def who(port: int) -> list[tuple[int, str]]:
    return [(pid, command_of(pid)) for pid in listener_pids(port)]


def pick(port: int) -> int:
    if port_free(port):
        print(port)
        return 0
    holders = who(port)
    gateway = [p for p, c in holders if is_ollabridge(c)]
    for candidate in range(port + 1, port + SEARCH + 1):
        if port_free(candidate):
            if gateway:
                print(f"  ↪ OllaBridge is already running on port {port} (pid {', '.join(map(str, gateway))}); "
                      f"this one starts on {candidate}. To use {port} instead: make stop && make start  (or: make restart)",
                      file=sys.stderr)
            else:
                who_txt = "; ".join(f"pid {p}: {c[:80]}" for p, c in holders) or "another program"
                print(f"  ↪ Port {port} is in use ({who_txt}); OllaBridge starts on {candidate} instead. "
                      f"Point clients at http://localhost:{candidate}/v1, or set OLLABRIDGE_PORT.", file=sys.stderr)
            print(candidate)
            return 0
    print(f"  ✗ Ports {port}–{port + SEARCH} are all in use; free one or set OLLABRIDGE_PORT.", file=sys.stderr)
    return 1


def stop(port: int, wait_s: float = 10.0) -> int:
    holders = who(port)
    if not holders:
        print(f"  Nothing is listening on port {port}." if port_free(port)
              else f"  Port {port} is in use, but its process could not be identified.")
        return 0
    others = [(p, c) for p, c in holders if not is_ollabridge(c)]
    gateway = [p for p, c in holders if is_ollabridge(c)]
    for pid, cmd in others:
        print(f"  ✗ Port {port} belongs to another program (pid {pid}: {cmd[:100]}); not stopping it.")
    if not gateway:
        return 1 if others else 0
    for pid in gateway:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  ✗ Not allowed to stop pid {pid}.")
            return 1
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and not port_free(port):
        time.sleep(0.25)
    if not port_free(port):
        for pid in gateway:
            try:
                os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1.0)
    if port_free(port):
        print(f"  ✓ Stopped OllaBridge on port {port} (pid {', '.join(map(str, gateway))}).")
        return 0
    print(f"  ✗ Port {port} is still in use.")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("pick", "stop", "who"):
        print(__doc__, file=sys.stderr)
        return 2
    port = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else int(os.environ.get("OLLABRIDGE_PORT") or DEFAULT_PORT)
    if argv[1] == "pick":
        return pick(port)
    if argv[1] == "stop":
        return stop(port)
    for pid, cmd in who(port):
        print(pid, cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
