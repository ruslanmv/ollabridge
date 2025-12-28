from __future__ import annotations

import os
import secrets
from pathlib import Path

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

from ollabridge.core.settings import settings
from ollabridge.utils.installer import (
    ensure_model,
    ensure_ollama_server_running,
    install_ollama,
    is_ollama_installed,
)
from ollabridge.utils.tunnel import start_tunnel

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _write_env_key_if_needed(key: str):
    """Persist API key in .env so restarts keep the same key."""
    env_path = Path(".env")
    existing = env_path.read_text(encoding="utf-8", errors="ignore") if env_path.exists() else ""
    lines = []
    replaced = False
    for line in existing.splitlines():
        if line.startswith("API_KEYS="):
            lines.append(f"API_KEYS={key}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        if existing.strip():
            lines.append("")
        lines.append(f"API_KEYS={key}")
    env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _dashboard(host: str, port: int, public_url: str | None, key: str, model: str, workers: int):
    local_url = f"http://localhost:{port}"
    msg = f"""
[bold green]✅ OllaBridge is Online[/bold green]

[bold]Model:[/bold]        {model}
[bold]Workers:[/bold]      {workers}
[bold]Local API:[/bold]    {local_url}/v1
[bold]Health:[/bold]       {local_url}/health
[bold]Key:[/bold]          {key}
[dim]Send as X-API-Key or Authorization: Bearer ...[/dim]
"""

    if public_url:
        msg += f"""
[bold yellow]🌍 Public URL:[/bold yellow]   [link={public_url}]{public_url}[/link]
[dim]Use {public_url}/v1 as your OpenAI base_url[/dim]
"""

    console.print(Panel(msg, title="🚀 Gateway Ready", border_style="blue"))


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(11435, help="Bind port"),
    share: bool = typer.Option(False, "--share", help="Get a public URL (ngrok best-effort)"),
    workers: int = typer.Option(1, "--workers", help="Worker processes (scalability hook)"),
    model: str = typer.Option("deepseek-r1", "--model", help="Default chat model to ensure/use"),
):
    """🚀 Start OllaBridge (self-healing: installs Ollama + pulls model)."""

    # 1) Self-healing: install Ollama
    if not is_ollama_installed():
        install_ollama()

    # 2) Start Ollama server (best effort)
    ensure_ollama_server_running()

    # 3) Ensure model exists
    ensure_model(model)

    # 4) Auth: auto-generate key if default is unsafe
    key = (settings.API_KEYS or "").split(",")[0].strip() if settings.API_KEYS else ""
    if (not key) or ("change-me" in key) or ("dev-key" in key):
        key = f"sk-ollabridge-{secrets.token_urlsafe(12)}"
        _write_env_key_if_needed(key)
        os.environ["API_KEYS"] = key  # ensure current process uses it

    # 5) Optional tunnel
    public_url = None
    if share:
        console.print("[green]🌍 Opening tunnel to public internet...[/green]")
        try:
            public_url = start_tunnel(port)
        except Exception as e:
            console.print(f"[red]Tunnel failed:[/red] {e}")
            console.print("[yellow]Tip:[/yellow] For production use Cloudflare Tunnel or Tailscale.")

    _dashboard(host, port, public_url, key, model, workers)

    uvicorn.run(
        "ollabridge.api.main:app",
        host=host,
        port=port,
        workers=workers,
        log_level="warning",
    )


@app.command()
def up(
    share: bool = typer.Option(False, "--share", help="Alias of `start --share` (backwards compatible)."),
):
    """Backwards-compatible alias for older docs."""
    start(share=share)


if __name__ == "__main__":
    app()
