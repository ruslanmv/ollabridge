"""The "Set up Ollama" wizard backend (``/admin/ollama-setup/*``).

The wizard's whole promise is that its first screen is the right one: it
must say "connect", "start", "install" or "do it by hand" from what the
machine actually looks like, run only the fixed official installer command,
and never claim Ollama is up before it answers.
"""

from __future__ import annotations

import sys
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ollabridge.api import ollama_setup_routes as osr
from ollabridge.core import runtime_settings as rts
from ollabridge.core.settings import settings

AUTH = {"Authorization": "Bearer test-key-abc"}
URL = "http://localhost:11434"


def _down(url: str, timeout: float = 0) -> dict:
    return {"url": url.rstrip("/"), "reachable": False, "models": [], "message": "Connection refused"}


def _up(models=("llama3.2:3b",)):
    def probe(url: str, timeout: float = 0) -> dict:
        return {"url": url.rstrip("/"), "reachable": True, "models": list(models), "message": "ok"}

    return probe


def _up_only_at(good: str, models=("llama3.2:3b",)):
    async def probe(url: str, timeout: float = 0) -> dict:
        return _up(models)(url) if url.rstrip("/") == good else _down(url)

    return probe


def _async(fn):
    async def wrapper(url: str, timeout: float = 0) -> dict:
        return fn(url, timeout)

    return wrapper


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", URL)
    monkeypatch.setattr(settings, "API_KEYS", "test-key-abc")
    monkeypatch.setattr(settings, "AUTH_MODE", "required")
    monkeypatch.setenv("API_KEYS", "test-key-abc")
    monkeypatch.setenv("AUTH_MODE", "required")
    # Never touch the real machine: no binary, no package managers, plain Linux.
    monkeypatch.setattr(osr, "_which_ollama", lambda: None)
    monkeypatch.setattr(osr, "_platform", lambda: "linux")
    monkeypatch.setattr(osr, "_platform_label", lambda: "Ubuntu 22.04")
    monkeypatch.setattr(osr, "_in_wsl", lambda: False)
    monkeypatch.setattr(osr, "_in_docker", lambda: False)
    monkeypatch.setattr(osr, "_can_sudo_without_password", lambda: False)
    yield
    monkeypatch.setattr(rts, "_cache", None)


@pytest.fixture
def client():
    from ollabridge.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _status(client) -> dict:
    r = client.get("/admin/ollama-setup/status", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# --- candidates --------------------------------------------------------------


def test_localhost_gets_an_ipv4_twin_and_wsl_gets_the_windows_host(monkeypatch):
    assert osr._candidate_urls(URL, in_wsl=False, in_docker=False) == [
        {"url": "http://127.0.0.1:11434", "label": "IPv4 loopback"}
    ]
    monkeypatch.setattr(osr, "_wsl_host_ip", lambda: "172.29.80.1")
    urls = [c["url"] for c in osr._candidate_urls(URL, in_wsl=True, in_docker=False)]
    assert urls == ["http://127.0.0.1:11434", "http://172.29.80.1:11434"]
    # The configured address itself is never a candidate.
    assert osr._candidate_urls("http://127.0.0.1:11434", in_wsl=False, in_docker=False) == []


def test_default_gateway_is_parsed_from_proc_net_route():
    # Two rows as /proc/net/route prints them: the default route first.
    table = 'Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\neth0\t00000000\t01501DAC\t0003\t0\t0\t0\t00000000\t0\t0\t0\neth0\t00501DAC\t00000000\t0001\t0\t0\t0\t00F0FFFF\t0\t0\t0\n'
    assert osr._parse_default_gateway(table) == "172.29.80.1"
    assert osr._parse_default_gateway('Iface\tDestination\n') is None


# --- the first screen --------------------------------------------------------


def test_requires_api_key(client):
    assert client.get("/admin/ollama-setup/status").status_code == 401


def test_nothing_installed_and_no_sudo_means_manual(client, monkeypatch):
    monkeypatch.setattr(osr, "_probe", _async(_down))
    s = _status(client)
    assert s["recommended"] == "manual"
    assert s["binary"] == {"found": False, "path": None, "version": None}
    assert s["service"]["reachable"] is False
    assert s["install"]["can_run_here"] is False
    assert "administrator password" in s["install"]["reason"]
    assert s["install"]["display_command"] == osr.LINUX_INSTALL_SCRIPT
    assert s["install"]["download_url"] == osr.DOWNLOAD_PAGE["linux"]
    assert "_argv" not in s["install"] and "_shell" not in s["install"]


def test_windows_with_winget_recommends_install(client, monkeypatch):
    monkeypatch.setattr(osr, "_platform", lambda: "windows")
    monkeypatch.setattr(osr, "_probe", _async(_down))
    monkeypatch.setattr(osr.shutil, "which", lambda name: r"C:\winget.exe" if name == "winget" else None)
    s = _status(client)
    assert s["recommended"] == "install"
    assert s["install"]["method"] == "winget"
    assert s["install"]["can_run_here"] is True


def test_inside_a_container_never_offers_to_install(client, monkeypatch):
    monkeypatch.setattr(osr, "_in_docker", lambda: True)
    monkeypatch.setattr(osr, "_probe", _async(_down))
    s = _status(client)
    assert s["install"]["can_run_here"] is False
    assert "container" in s["install"]["reason"]
    assert [c["url"] for c in s["candidates"]][:1] == ["http://127.0.0.1:11434"]
    assert "http://host.docker.internal:11434" in [c["url"] for c in s["candidates"]]


def test_binary_present_but_silent_recommends_start(client, monkeypatch):
    monkeypatch.setattr(osr, "_which_ollama", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(osr, "_binary_version", lambda path: "0.6.2")
    monkeypatch.setattr(osr, "_probe", _async(_down))
    s = _status(client)
    assert s["recommended"] == "start"
    assert s["binary"] == {"found": True, "path": "/usr/local/bin/ollama", "version": "0.6.2"}


def test_running_elsewhere_recommends_connect(client, monkeypatch):
    """The observed case: Ollama answers on 127.0.0.1 while the gateway is
    pointed at localhost (IPv6 first)."""
    monkeypatch.setattr(osr, "_probe", _up_only_at("http://127.0.0.1:11434"))
    s = _status(client)
    assert s["recommended"] == "connect"
    assert s["service"]["reachable"] is False
    assert s["candidates"] == [
        {"url": "http://127.0.0.1:11434", "label": "IPv4 loopback", "reachable": True,
         "models": 1, "message": "ok"}
    ]


def test_reachable_with_no_models_recommends_pull_then_ready(client, monkeypatch):
    monkeypatch.setattr(osr, "_probe", _async(_up(models=())))
    s = _status(client)
    assert s["recommended"] == "pull"
    assert s["service"]["models"] == 0
    assert s["suggested_models"][0]["note"] == "Your configured default model"
    assert {m["id"] for m in s["suggested_models"]} >= {"llama3.2:3b", "qwen2.5:7b", "deepseek-r1:8b"}

    monkeypatch.setattr(osr, "_probe", _async(_up(models=("llama3.2:3b", "qwen2.5:7b"))))
    s = _status(client)
    assert s["recommended"] == "ready"
    assert s["service"]["model_names"] == ["llama3.2:3b", "qwen2.5:7b"]


def test_status_follows_the_saved_runtime_url(client, monkeypatch):
    rts.update({"ollama_base_url": "http://172.29.80.1:11434"})
    monkeypatch.setattr(osr, "_probe", _async(_down))
    s = _status(client)
    assert s["service"]["url"] == "http://172.29.80.1:11434"
    assert s["settings"]["ollama_base_url"] == "http://172.29.80.1:11434"


# --- install job ---------------------------------------------------------------


def test_install_is_refused_when_the_process_cannot_do_it(client):
    r = client.post("/admin/ollama-setup/install", headers=AUTH)
    assert r.status_code == 422
    assert "administrator password" in r.json()["detail"]


def test_install_is_refused_when_already_installed(client, monkeypatch):
    monkeypatch.setattr(osr, "_which_ollama", lambda: "/usr/local/bin/ollama")
    r = client.post("/admin/ollama-setup/install", headers=AUTH)
    assert r.status_code == 409


def _wait_for_job(client, job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/admin/ollama-setup/jobs/{job_id}", headers=AUTH)
        assert r.status_code == 200
        job = r.json()
        if job["status"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_install_job_streams_output_and_reports_the_exit_code(client, monkeypatch):
    """The real command is swapped for a harmless script; the job plumbing
    (background thread, log lines, exit code, polling) is what is under test."""
    fake_argv = [sys.executable, "-u", "-c", "import sys; print('downloading'); print('installed', file=sys.stderr)"]
    monkeypatch.setattr(
        osr, "_install_plan",
        lambda **kw: {"method": "script", "display_command": "fake install", "download_url": "",
                      "can_run_here": True, "reason": "", "_argv": fake_argv, "_shell": None},
    )
    r = client.post("/admin/ollama-setup/install", headers=AUTH)
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["status"] == "running" and started["command"] == "fake install"

    job = _wait_for_job(client, started["job_id"])
    assert job["status"] == "succeeded"
    assert job["exit_code"] == 0
    assert job["lines"] == ["downloading", "installed"]  # stderr merged, in order
    assert job["finished_at"]

    failing = [sys.executable, "-u", "-c", "print('no space left'); raise SystemExit(3)"]
    monkeypatch.setattr(
        osr, "_install_plan",
        lambda **kw: {"method": "script", "display_command": "fake install", "download_url": "",
                      "can_run_here": True, "reason": "", "_argv": failing, "_shell": None},
    )
    job = _wait_for_job(client, client.post("/admin/ollama-setup/install", headers=AUTH).json()["job_id"])
    assert job["status"] == "failed" and job["exit_code"] == 3
    assert job["lines"] == ["no space left"]


def test_unknown_job_is_404(client):
    assert client.get("/admin/ollama-setup/jobs/nope", headers=AUTH).status_code == 404


# --- start -------------------------------------------------------------------


def test_start_without_a_binary_is_refused(client, monkeypatch):
    monkeypatch.setattr(osr, "_probe", _async(_down))
    r = client.post("/admin/ollama-setup/start", headers=AUTH)
    assert r.status_code == 422


def test_start_spawns_serve_and_waits_until_it_answers(client, monkeypatch):
    monkeypatch.setattr(osr, "_which_ollama", lambda: "/usr/local/bin/ollama")
    spawned: list[list[str]] = []
    monkeypatch.setattr(osr, "_spawn_detached", lambda argv: spawned.append(argv))
    calls = {"n": 0}

    async def probe(url: str, timeout: float = 0) -> dict:
        calls["n"] += 1
        return _up()(url) if calls["n"] >= 3 else _down(url)  # down, down, then up

    monkeypatch.setattr(osr, "_probe", probe)
    r = client.post("/admin/ollama-setup/start", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["reachable"] is True
    assert body["already_running"] is False
    assert body["url"] == URL
    assert spawned == [["/usr/local/bin/ollama", "serve"]]


def test_start_is_a_no_op_when_already_up(client, monkeypatch):
    monkeypatch.setattr(osr, "_probe", _async(_up()))
    monkeypatch.setattr(osr, "_spawn_detached", lambda argv: pytest.fail("must not spawn"))
    body = client.post("/admin/ollama-setup/start", headers=AUTH).json()
    assert body == {"ok": True, "reachable": True, "url": URL, "already_running": True,
                    "models": 1, "waited_ms": 0}


# --- pull --------------------------------------------------------------------


def test_pull_uses_the_catalog_manager_against_the_runtime_url(client, monkeypatch):
    class FakePulls:
        def __init__(self):
            self.started = []
            self._p = None

        async def start(self, *, node_id, external_model_id, client):
            from types import SimpleNamespace

            self.started.append((node_id, external_model_id, client.base_url))
            self._p = SimpleNamespace(external_model_id=external_model_id, status="running",
                                      progress_pct=12.5, total_bytes=100, completed_bytes=12, error=None)
            return self._p

        def get(self, node_id, external_model_id):
            return self._p if self._p and self._p.external_model_id == external_model_id else None

    rts.update({"ollama_base_url": "http://172.29.80.1:11434/"})
    fake = FakePulls()
    client.app.state.local_catalog_pulls = fake

    r = client.post("/admin/ollama-setup/pull", headers=AUTH, json={"model": "llama3.2:3b"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running" and r.json()["progress_pct"] == 12.5
    assert fake.started == [(settings.LOCAL_NODE_ID or "local", "llama3.2:3b", "http://172.29.80.1:11434")]

    r = client.get("/admin/ollama-setup/pull/llama3.2:3b", headers=AUTH)
    assert r.status_code == 200 and r.json()["model"] == "llama3.2:3b"
    assert client.get("/admin/ollama-setup/pull/other", headers=AUTH).status_code == 404


def test_pull_without_catalog_is_503_with_a_terminal_fallback(client):
    client.app.state.local_catalog_pulls = None
    r = client.post("/admin/ollama-setup/pull", headers=AUTH, json={"model": "llama3.2:3b"})
    assert r.status_code == 503
    assert "ollama pull" in r.json()["detail"]
