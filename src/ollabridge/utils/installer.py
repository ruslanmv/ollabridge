from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from rich.console import Console
from rich.prompt import Confirm

console = Console()


def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def install_ollama(assume_yes: bool = False):
    """Detects OS and runs the official install command (where possible).

    Linux/macOS: runs the official install script.
    Windows: opens download page (manual install).

    Args:
        assume_yes: If True, skip interactive confirmation (for MCP/headless mode).
    """
    system = platform.system().lower()
    console.print(f"[bold cyan]🔍 Ollama not found. Detected OS: {system.capitalize()}[/bold cyan]")

    if not assume_yes:
        if not Confirm.ask("Would you like OllaBridge to install Ollama for you?"):
            console.print("[red]❌ Aborted. You need Ollama to run this gateway.[/red]")
            sys.exit(1)

    try:
        if system in ("linux", "darwin"):
            console.print("[dim]Running: curl -fsSL https://ollama.com/install.sh | sh[/dim]")
            subprocess.check_call("curl -fsSL https://ollama.com/install.sh | sh", shell=True)
            console.print("[bold green]✅ Ollama installed successfully![/bold green]")
        elif system == "windows":
            console.print("[yellow]⚠️  Windows requires a manual installer.[/yellow]")
            console.print("[dim]Opening Ollama download page... (install and re-run)[/dim]")
            import webbrowser
            webbrowser.open("https://ollama.com/download/windows")
            sys.exit(0)
        else:
            console.print("[red]Unsupported OS. Please install Ollama manually: https://ollama.com/download[/red]")
            sys.exit(1)

    except Exception as e:
        console.print(f"[bold red]❌ Installation failed:[/bold red] {e}")
        console.print("Please install manually: https://ollama.com/download")
        sys.exit(1)


def ensure_ollama_server_running():
    """Best-effort: start `ollama serve` in background. Harmless if already running."""
    try:
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def ensure_model(model_name: str):
    """Checks if a model exists; if not, pulls it."""
    console.print(f"[dim]Checking for model '{model_name}'...[/dim]")
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if model_name not in (result.stdout or ""):
            console.print(f"[yellow]⚠️  Model '{model_name}' not found. Pulling now...[/yellow]")
            subprocess.check_call(["ollama", "pull", model_name])
            console.print(f"[bold green]✅ Model '{model_name}' ready.[/bold green]")
    except Exception:
        console.print("[yellow]⚠️  Could not verify model (is Ollama running?).[/yellow]")
