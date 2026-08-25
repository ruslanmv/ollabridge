from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections import deque

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

console = Console()

#: The official one-liner. Ollama's own script is Linux-only.
INSTALL_SCRIPT_CMD = "curl -fsSL https://ollama.com/install.sh | sh"

#: Binaries Ollama's install script shells out to. ``zstd`` became mandatory
#: when upstream switched the release tarballs to zstd compression, and it is
#: NOT preinstalled on Debian/Ubuntu (including stock WSL images), so the
#: script aborts with "This version requires zstd for extraction".
LINUX_PREREQS: tuple[str, ...] = ("curl", "tar", "zstd")

#: Supported package managers, in probe order, with the commands needed to
#: install packages. ``{pkgs}`` is expanded in place. Package names for curl,
#: tar and zstd happen to be identical across all of these distros.
_PACKAGE_MANAGERS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("apt-get", (("apt-get", "update"), ("apt-get", "install", "-y", "{pkgs}"))),
    ("dnf", (("dnf", "install", "-y", "{pkgs}"),)),
    ("yum", (("yum", "install", "-y", "{pkgs}"),)),
    ("zypper", (("zypper", "--non-interactive", "install", "{pkgs}"),)),
    ("pacman", (("pacman", "-Sy", "--noconfirm", "{pkgs}"),)),
    ("apk", (("apk", "add", "--no-cache", "{pkgs}"),)),
)

#: Copy/paste hints shown when we cannot install the prerequisites ourselves.
_MANUAL_PKG_HINTS: tuple[tuple[str, str], ...] = (
    ("Debian/Ubuntu/WSL", "sudo apt-get update && sudo apt-get install -y {pkgs}"),
    ("RHEL/CentOS/Fedora", "sudo dnf install -y {pkgs}"),
    ("openSUSE", "sudo zypper install {pkgs}"),
    ("Arch", "sudo pacman -S {pkgs}"),
    ("Alpine", "sudo apk add {pkgs}"),
)

#: Places the install script may drop the binary that are not always on PATH
#: (notably for non-login shells and freshly provisioned WSL distros).
_FALLBACK_OLLAMA_PATHS: tuple[str, ...] = (
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
    "/opt/ollama/bin/ollama",
)


class OllamaInstallError(RuntimeError):
    """Raised internally when an installation attempt fails."""


def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def find_ollama_binary() -> str | None:
    """Locate the ollama binary, including common paths missing from PATH."""
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in _FALLBACK_OLLAMA_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def detect_package_manager() -> str | None:
    """Return the first available system package manager, if any."""
    for binary, _ in _PACKAGE_MANAGERS:
        if shutil.which(binary):
            return binary
    return None


def missing_prerequisites(commands: tuple[str, ...] = LINUX_PREREQS) -> list[str]:
    """Return the subset of ``commands`` that is not on PATH."""
    return [cmd for cmd in commands if shutil.which(cmd) is None]


def _sudo_prefix(non_interactive: bool) -> list[str]:
    """Prefix needed to gain root, or an empty list if we already have it."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        return []
    if shutil.which("sudo") is None:
        return []
    # `-n` keeps headless/MCP runs from blocking forever on a password prompt.
    return ["sudo", "-n"] if non_interactive else ["sudo"]


def package_install_commands(
    manager: str,
    packages: list[str],
    *,
    non_interactive: bool = False,
) -> list[list[str]]:
    """Build the argv list(s) that install ``packages`` with ``manager``."""
    templates = dict(_PACKAGE_MANAGERS)[manager]
    prefix = _sudo_prefix(non_interactive)
    commands: list[list[str]] = []
    for template in templates:
        cmd: list[str] = list(prefix)
        for part in template:
            if part == "{pkgs}":
                cmd.extend(packages)
            else:
                cmd.append(part)
        commands.append(cmd)
    return commands


def _run_streaming(cmd, *, shell: bool = False, tail: int = 40) -> tuple[int, str]:
    """Run a command, echoing its output live, and return (exit code, tail).

    We keep the last few lines so callers can inspect *why* a command failed
    (e.g. the upstream "requires zstd" message) without hiding progress from
    the user.
    """
    recent: deque[str] = deque(maxlen=tail)
    try:
        proc = subprocess.Popen(
            cmd,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:  # e.g. binary vanished between which() and here
        return 127, str(exc)

    if proc.stdout is not None:
        for line in proc.stdout:
            line = line.rstrip("\n")
            recent.append(line)
            console.print(f"[dim]{escape(line)}[/dim]")
    proc.wait()
    return proc.returncode, "\n".join(recent)


def _print_manual_package_help(packages: list[str]) -> None:
    pkgs = " ".join(packages)
    console.print(
        f"[yellow]Please install {pkgs} manually, then re-run OllaBridge:[/yellow]"
    )
    for label, template in _MANUAL_PKG_HINTS:
        console.print(f"  [dim]{label}:[/dim] {template.format(pkgs=pkgs)}")


def install_system_packages(packages: list[str], assume_yes: bool = False) -> bool:
    """Install OS packages with the detected package manager.

    Returns True only if every package is available afterwards.
    """
    if not packages:
        return True

    manager = detect_package_manager()
    if manager is None:
        console.print(
            "[yellow]⚠️  No supported package manager found "
            "(apt-get/dnf/yum/zypper/pacman/apk).[/yellow]"
        )
        _print_manual_package_help(packages)
        return False

    pkgs = " ".join(packages)
    if not assume_yes:
        if not Confirm.ask(
            f"Install the missing dependenc{'y' if len(packages) == 1 else 'ies'} "
            f"[bold]{pkgs}[/bold] with {manager}? (may prompt for your sudo password)",
            default=True,
        ):
            _print_manual_package_help(packages)
            return False

    for cmd in package_install_commands(manager, packages, non_interactive=assume_yes):
        console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
        code, output = _run_streaming(cmd)
        if code != 0:
            console.print(
                f"[yellow]⚠️  `{' '.join(cmd)}` failed (exit {code}).[/yellow]"
            )
            if "sudo" in cmd[:2] and "password" in output.lower():
                console.print(
                    "[dim]sudo needs a password but is running non-interactively.[/dim]"
                )
            _print_manual_package_help(packages)
            return False

    still_missing = missing_prerequisites(tuple(packages))
    if still_missing:
        console.print(
            f"[yellow]⚠️  Still missing after install: {' '.join(still_missing)}[/yellow]"
        )
        _print_manual_package_help(still_missing)
        return False

    console.print(f"[bold green]✅ Installed {pkgs}.[/bold green]")
    return True


def _install_ollama_linux(assume_yes: bool) -> None:
    """Install Ollama on Linux, healing missing installer prerequisites."""
    missing = missing_prerequisites()
    if missing:
        console.print(
            "[yellow]⚠️  The Ollama installer needs "
            f"{', '.join(missing)}, which {'is' if len(missing) == 1 else 'are'} "
            "not installed.[/yellow]"
        )
        installed = install_system_packages(missing, assume_yes=assume_yes)
        if not installed and shutil.which("curl") is None:
            # Without curl we cannot even fetch the install script.
            raise OllamaInstallError(
                "curl is required to download the Ollama installer"
            )

    console.print(f"[dim]Running: {INSTALL_SCRIPT_CMD}[/dim]")
    code, output = _run_streaming(INSTALL_SCRIPT_CMD, shell=True)

    if code != 0 and "zstd" in output.lower():
        # Upstream refuses to extract without zstd. Install it and retry once.
        console.print(
            "[yellow]⚠️  The installer requires zstd for extraction. "
            "Installing it and retrying...[/yellow]"
        )
        if install_system_packages(["zstd"], assume_yes=assume_yes):
            console.print(f"[dim]Retrying: {INSTALL_SCRIPT_CMD}[/dim]")
            code, output = _run_streaming(INSTALL_SCRIPT_CMD, shell=True)

    if code != 0:
        raise OllamaInstallError(f"`{INSTALL_SCRIPT_CMD}` exited with status {code}")


def _install_ollama_macos(assume_yes: bool) -> None:
    """Install Ollama on macOS.

    Ollama's install.sh is Linux-only, so use Homebrew when present and fall
    back to the official download page otherwise.
    """
    if shutil.which("brew") is not None:
        if assume_yes or Confirm.ask(
            "Install Ollama with Homebrew (`brew install ollama`)?", default=True
        ):
            console.print("[dim]Running: brew install ollama[/dim]")
            code, _ = _run_streaming(["brew", "install", "ollama"])
            if code == 0:
                return
            console.print(
                f"[yellow]⚠️  `brew install ollama` failed (exit {code}).[/yellow]"
            )
    else:
        console.print(
            "[yellow]⚠️  Homebrew not found; macOS needs the official installer.[/yellow]"
        )

    console.print("[dim]Opening the Ollama download page... (install and re-run)[/dim]")
    import webbrowser

    webbrowser.open("https://ollama.com/download/mac")
    sys.exit(0)


def install_ollama(assume_yes: bool = False):
    """Detects OS and installs Ollama (where possible).

    Linux: runs the official install script, first installing any missing
      prerequisites (``curl``, ``tar``, ``zstd``) with the system package
      manager so the script does not abort mid-way.
    macOS: uses Homebrew when available, otherwise opens the download page.
    Windows: opens download page (manual install).

    Args:
        assume_yes: If True, skip interactive confirmation (for MCP/headless mode).
    """
    system = platform.system().lower()
    console.print(
        f"[bold cyan]🔍 Ollama not found. Detected OS: {system.capitalize()}[/bold cyan]"
    )

    if not assume_yes:
        if not Confirm.ask("Would you like OllaBridge to install Ollama for you?"):
            console.print("[red]❌ Aborted. You need Ollama to run this gateway.[/red]")
            sys.exit(1)

    try:
        if system == "linux":
            _install_ollama_linux(assume_yes)
        elif system == "darwin":
            _install_ollama_macos(assume_yes)
        elif system == "windows":
            console.print("[yellow]⚠️  Windows requires a manual installer.[/yellow]")
            console.print(
                "[dim]Opening Ollama download page... (install and re-run)[/dim]"
            )
            import webbrowser

            webbrowser.open("https://ollama.com/download/windows")
            sys.exit(0)
        else:
            console.print(
                "[red]Unsupported OS. Please install Ollama manually: "
                "https://ollama.com/download[/red]"
            )
            sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        console.print(f"[bold red]❌ Installation failed:[/bold red] {e}")
        console.print("Please install manually: https://ollama.com/download")
        sys.exit(1)

    binary = find_ollama_binary()
    if binary is None:
        console.print(
            "[bold red]❌ Installation finished but the `ollama` binary was not "
            "found.[/bold red]"
        )
        console.print("Please install manually: https://ollama.com/download")
        sys.exit(1)

    if shutil.which("ollama") is None:
        console.print(
            f"[yellow]⚠️  Ollama installed at {binary} but it is not on your "
            "PATH.[/yellow]"
        )
        console.print(
            f'[dim]Add it with: export PATH="{os.path.dirname(binary)}:$PATH"[/dim]'
        )

    console.print("[bold green]✅ Ollama installed successfully![/bold green]")


def ensure_ollama_server_running():
    """Best-effort: start `ollama serve` in background. Harmless if already running."""
    binary = find_ollama_binary() or "ollama"
    try:
        subprocess.Popen(
            [binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


def ensure_model(model_name: str):
    """Checks if a model exists; if not, pulls it."""
    console.print(f"[dim]Checking for model '{model_name}'...[/dim]")
    binary = find_ollama_binary() or "ollama"
    try:
        result = subprocess.run([binary, "list"], capture_output=True, text=True)
        if model_name not in (result.stdout or ""):
            console.print(
                f"[yellow]⚠️  Model '{model_name}' not found. Pulling now...[/yellow]"
            )
            subprocess.check_call([binary, "pull", model_name])
            console.print(f"[bold green]✅ Model '{model_name}' ready.[/bold green]")
        else:
            console.print(f"[bold green]✅ Model '{model_name}' ready.[/bold green]")
    except Exception:
        console.print(
            "[yellow]⚠️  Could not verify model (is Ollama running?).[/yellow]"
        )
