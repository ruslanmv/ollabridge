"""Unit tests for the self-healing Ollama installer.

Regression coverage for the WSL/Debian failure where Ollama's official
install script aborts with::

    ERROR: This version requires zstd for extraction.

because ``zstd`` is not part of a stock Debian/Ubuntu image. OllaBridge now
detects the missing prerequisites up front, installs them with the system
package manager, and retries the script once if upstream still complains.

Everything here is hermetic: no network, no package manager, no subprocess.
``shutil.which`` and the streaming runner are monkeypatched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.utils import installer  # noqa: E402


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def fake_which(available: set[str]):
    """Build a ``shutil.which`` replacement backed by a set of binaries."""

    def _which(cmd, *args, **kwargs):
        return f"/usr/bin/{cmd}" if cmd in available else None

    return _which


class RunRecorder:
    """Stand-in for ``installer._run_streaming``.

    ``results`` maps a substring of the rendered command to a
    ``(exit_code, output)`` pair; anything unmatched succeeds silently. Each
    entry may hold a list of pairs to model "fails first, then succeeds".
    """

    def __init__(self, results: dict[str, object] | None = None, *, installs=None):
        self.results = results or {}
        self.calls: list[str] = []
        # Binaries that appear on PATH once their install command has run.
        self.installs = installs or {}
        self.available: set[str] = set()

    def __call__(self, cmd, *, shell=False, tail=40):
        rendered = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.calls.append(rendered)

        for binary, marker in self.installs.items():
            if marker in rendered:
                self.available.add(binary)

        for marker, outcome in self.results.items():
            if marker in rendered:
                if isinstance(outcome, list):
                    return outcome.pop(0) if len(outcome) > 1 else outcome[0]
                return outcome
        return (0, "")


@pytest.fixture(autouse=True)
def _no_confirm(monkeypatch):
    """Answer every interactive prompt with "yes" unless a test overrides it."""
    monkeypatch.setattr(installer.Confirm, "ask", lambda *a, **k: True)


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    # Run as root so no sudo prefix noise leaks into the assertions.
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)


# --------------------------------------------------------------------------
# prerequisite + package-manager detection
# --------------------------------------------------------------------------
def test_zstd_is_a_declared_prerequisite():
    assert "zstd" in installer.LINUX_PREREQS
    assert "curl" in installer.LINUX_PREREQS


def test_missing_prerequisites_reports_only_absent_binaries(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which({"curl", "tar"}))
    assert installer.missing_prerequisites() == ["zstd"]


def test_missing_prerequisites_empty_when_all_present(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which({"curl", "tar", "zstd"}))
    assert installer.missing_prerequisites() == []


@pytest.mark.parametrize(
    "available, expected",
    [
        ({"apt-get"}, "apt-get"),
        ({"dnf"}, "dnf"),
        ({"yum"}, "yum"),
        ({"zypper"}, "zypper"),
        ({"pacman"}, "pacman"),
        ({"apk"}, "apk"),
        # apt-get wins the probe order on distros shipping both.
        ({"apt-get", "dnf"}, "apt-get"),
        (set(), None),
    ],
)
def test_detect_package_manager(monkeypatch, available, expected):
    monkeypatch.setattr(installer.shutil, "which", fake_which(available))
    assert installer.detect_package_manager() == expected


def test_apt_commands_update_before_install(monkeypatch):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)
    cmds = installer.package_install_commands("apt-get", ["zstd"])
    assert cmds == [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "zstd"],
    ]


def test_commands_gain_sudo_when_not_root(monkeypatch):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"sudo"}))
    cmds = installer.package_install_commands("dnf", ["zstd", "curl"])
    assert cmds == [["sudo", "dnf", "install", "-y", "zstd", "curl"]]


def test_headless_sudo_is_non_interactive(monkeypatch):
    """MCP/headless runs must never hang on a sudo password prompt."""
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"sudo"}))
    cmds = installer.package_install_commands("apt-get", ["zstd"], non_interactive=True)
    assert all(cmd[:2] == ["sudo", "-n"] for cmd in cmds)


def test_no_sudo_prefix_when_sudo_unavailable(monkeypatch):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))
    cmds = installer.package_install_commands("apk", ["zstd"])
    assert cmds == [["apk", "add", "--no-cache", "zstd"]]


# --------------------------------------------------------------------------
# install_system_packages
# --------------------------------------------------------------------------
def test_install_system_packages_succeeds(monkeypatch):
    runner = RunRecorder(installs={"zstd": "install -y zstd"})
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(
        installer.shutil,
        "which",
        lambda cmd, *a, **k: (
            f"/usr/bin/{cmd}" if cmd == "apt-get" or cmd in runner.available else None
        ),
    )

    assert installer.install_system_packages(["zstd"]) is True
    assert runner.calls == ["apt-get update", "apt-get install -y zstd"]


def test_install_system_packages_without_package_manager(monkeypatch):
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))

    assert installer.install_system_packages(["zstd"]) is False
    assert runner.calls == []


def test_install_system_packages_declined_by_user(monkeypatch):
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"apt-get"}))
    monkeypatch.setattr(installer.Confirm, "ask", lambda *a, **k: False)

    assert installer.install_system_packages(["zstd"], assume_yes=False) is False
    assert runner.calls == []


def test_install_system_packages_detects_silent_failure(monkeypatch):
    """A zero exit code is not enough — the binary must actually show up."""
    runner = RunRecorder()  # no `installs`, so zstd never appears on PATH
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"apt-get"}))

    assert installer.install_system_packages(["zstd"]) is False


def test_install_system_packages_noop_for_empty_list(monkeypatch):
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    assert installer.install_system_packages([]) is True
    assert runner.calls == []


# --------------------------------------------------------------------------
# the reported bug: zstd missing on Linux/WSL
# --------------------------------------------------------------------------
def test_missing_zstd_is_installed_before_the_script_runs(monkeypatch, linux):
    """The regression: install zstd first, then run install.sh exactly once."""
    runner = RunRecorder(installs={"zstd": "install -y zstd"})
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(
        installer.shutil,
        "which",
        lambda cmd, *a, **k: (
            f"/usr/bin/{cmd}"
            if cmd in {"curl", "tar", "apt-get", "ollama"} | runner.available
            else None
        ),
    )

    installer.install_ollama(assume_yes=True)

    assert runner.calls == [
        "apt-get update",
        "apt-get install -y zstd",
        installer.INSTALL_SCRIPT_CMD,
    ]


def test_script_is_retried_once_after_a_zstd_error(monkeypatch, linux):
    """Prereqs looked fine, but upstream still demanded zstd — heal and retry."""
    zstd_error = (
        "ERROR: This version requires zstd for extraction. "
        "Please install zstd and try again:"
    )
    runner = RunRecorder(
        results={installer.INSTALL_SCRIPT_CMD: [(1, zstd_error), (0, "")]},
        installs={"zstd": "install -y zstd"},
    )
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(
        installer.shutil,
        "which",
        lambda cmd, *a, **k: (
            f"/usr/bin/{cmd}"
            # zstd is "present" up front (stale PATH cache in the real world),
            # so the pre-flight check passes and the script still fails.
            if cmd in {"curl", "tar", "zstd", "apt-get", "ollama"}
            else None
        ),
    )

    installer.install_ollama(assume_yes=True)

    assert runner.calls == [
        installer.INSTALL_SCRIPT_CMD,
        "apt-get update",
        "apt-get install -y zstd",
        installer.INSTALL_SCRIPT_CMD,
    ]


def test_script_is_not_retried_for_unrelated_failures(monkeypatch, linux):
    runner = RunRecorder(
        results={installer.INSTALL_SCRIPT_CMD: (1, "curl: (6) Could not resolve host")}
    )
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(
        installer.shutil, "which", fake_which({"curl", "tar", "zstd", "apt-get"})
    )

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 1
    assert runner.calls == [installer.INSTALL_SCRIPT_CMD]


def test_missing_curl_that_cannot_be_installed_aborts(monkeypatch, linux):
    """Without curl we cannot even fetch the script, so fail fast."""
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"tar", "zstd"}))

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 1
    assert installer.INSTALL_SCRIPT_CMD not in runner.calls


def test_failed_prereq_install_still_attempts_the_script(monkeypatch, linux):
    """zstd install failed but curl exists — give the script a chance anyway."""
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(
        installer.shutil,
        "which",
        fake_which({"curl", "tar", "apt-get", "ollama"}),
    )

    installer.install_ollama(assume_yes=True)

    assert installer.INSTALL_SCRIPT_CMD in runner.calls


def test_missing_binary_after_a_successful_script_is_reported(monkeypatch, linux):
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"curl", "tar", "zstd"}))
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: False)

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 1


def test_binary_outside_path_is_accepted(monkeypatch, linux):
    """WSL sometimes leaves /usr/local/bin off a non-login shell's PATH."""
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"curl", "tar", "zstd"}))
    monkeypatch.setattr(
        installer.os.path, "isfile", lambda p: p == "/usr/local/bin/ollama"
    )
    monkeypatch.setattr(installer.os, "access", lambda p, mode: True)

    installer.install_ollama(assume_yes=True)  # must not raise


def test_user_declining_the_install_aborts(monkeypatch, linux):
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.Confirm, "ask", lambda *a, **k: False)

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=False)

    assert exc.value.code == 1
    assert runner.calls == []


# --------------------------------------------------------------------------
# other platforms
# --------------------------------------------------------------------------
def test_macos_uses_homebrew_not_the_linux_only_script(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    runner = RunRecorder()
    monkeypatch.setattr(installer, "_run_streaming", runner)
    monkeypatch.setattr(installer.shutil, "which", fake_which({"brew", "ollama"}))

    installer.install_ollama(assume_yes=True)

    assert runner.calls == ["brew install ollama"]


def test_macos_without_homebrew_opens_the_download_page(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))
    opened: list[str] = []
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 0
    assert opened == ["https://ollama.com/download/mac"]


def test_windows_opens_the_download_page(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Windows")
    opened: list[str] = []
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 0
    assert opened == ["https://ollama.com/download/windows"]


def test_unsupported_os_exits_with_guidance(monkeypatch):
    monkeypatch.setattr(installer.platform, "system", lambda: "Plan9")

    with pytest.raises(SystemExit) as exc:
        installer.install_ollama(assume_yes=True)

    assert exc.value.code == 1


# --------------------------------------------------------------------------
# binary resolution used by the rest of the CLI
# --------------------------------------------------------------------------
def test_find_ollama_binary_prefers_path(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which({"ollama"}))
    assert installer.find_ollama_binary() == "/usr/bin/ollama"


def test_find_ollama_binary_falls_back_to_known_locations(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))
    monkeypatch.setattr(
        installer.os.path, "isfile", lambda p: p == "/usr/local/bin/ollama"
    )
    monkeypatch.setattr(installer.os, "access", lambda p, mode: True)
    assert installer.find_ollama_binary() == "/usr/local/bin/ollama"


def test_find_ollama_binary_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))
    monkeypatch.setattr(installer.os.path, "isfile", lambda p: False)
    assert installer.find_ollama_binary() is None


def test_ensure_server_uses_the_resolved_binary(monkeypatch):
    monkeypatch.setattr(installer.shutil, "which", fake_which(set()))
    monkeypatch.setattr(
        installer.os.path, "isfile", lambda p: p == "/usr/local/bin/ollama"
    )
    monkeypatch.setattr(installer.os, "access", lambda p, mode: True)

    spawned: list[list[str]] = []
    monkeypatch.setattr(
        installer.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd)
    )

    installer.ensure_ollama_server_running()
    assert spawned == [["/usr/local/bin/ollama", "serve"]]


def test_run_streaming_captures_exit_code_and_output():
    """Exercise the real runner once, with a trivial shell command."""
    code, output = installer._run_streaming(
        "echo requires zstd for extraction; exit 3", shell=True
    )
    assert code == 3
    assert "zstd" in output
