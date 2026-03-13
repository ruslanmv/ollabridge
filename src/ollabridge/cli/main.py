from __future__ import annotations

import os
import socket
from pathlib import Path

import httpx
import secrets
import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ollabridge.core.enrollment import create_join_token
from ollabridge.core.security import generate_pairing_code
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


def _get_lan_ip() -> str | None:
    """Detect LAN IP address for showing to other devices on the network."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no traffic required; just selects route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _read_api_keys_from_dotenv() -> str | None:
    """Best-effort read of API_KEYS from a local .env file.

    We intentionally do this here (instead of only relying on Settings(env_file=".env"))
    because CLI commands may be executed from various working directories, and
    Settings is instantiated at import time.
    """
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("API_KEYS="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _write_env_key_if_missing(key: str) -> None:
    """Write API_KEYS to .env only if missing/empty.

    This prevents overwriting a user-provided API_KEYS in .env.
    NOTE: This is only called when the user explicitly passes --write-env.
    """
    env_path = Path(".env")
    existing = env_path.read_text(encoding="utf-8", errors="ignore") if env_path.exists() else ""

    # If API_KEYS is already present and non-empty, do nothing.
    existing_key = _read_api_keys_from_dotenv()
    if existing_key and existing_key.strip():
        return

    lines: list[str] = []
    replaced = False
    for line in existing.splitlines():
        if line.strip().startswith("API_KEYS="):
            lines.append(f"API_KEYS={key}")
            replaced = True
        else:
            lines.append(line)

    if not replaced:
        if existing.strip():
            lines.append("")
        lines.append(f"API_KEYS={key}")

    env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _dashboard(
    host: str,
    port: int,
    public_url: str | None,
    key: str,
    model: str,
    workers: int,
    join_token: str,
    auth_mode: str = "required",
    pairing_code: str | None = None,
):
    local_url = f"http://localhost:{port}"

    if auth_mode == "pairing":
        code_display = pairing_code or key
        msg = f"""
[bold green]✅ OllaBridge is Online  —  Pairing Mode[/bold green]

[bold]Pairing Code:[/bold]

    [bold yellow on #1a1a2e]  {code_display}  [/bold yellow on #1a1a2e]

[dim]Use this code as the API key to connect.[/dim]
[dim]Send as: X-API-Key: {code_display}  or  Authorization: Bearer {code_display}[/dim]

[bold]Model:[/bold]        {model}
[bold]Workers:[/bold]      {workers}
[bold]Auth mode:[/bold]    {auth_mode}
[bold]Local API:[/bold]    {local_url}/v1
[bold]Health:[/bold]       {local_url}/health
"""
        if key and "change-me" not in key and "dev-key" not in key and key != code_display:
            msg += f"""[bold]Static Key:[/bold]    {key}
[dim]Static keys always work alongside pairing tokens.[/dim]
"""
    else:
        msg = f"""
[bold green]✅ OllaBridge is Online[/bold green]

[bold]Model:[/bold]        {model}
[bold]Workers:[/bold]      {workers}
[bold]Auth mode:[/bold]    {auth_mode}
[bold]Local API:[/bold]    {local_url}/v1
[bold]Health:[/bold]       {local_url}/health
[bold]Key:[/bold]          {key}
[dim]Send as X-API-Key or Authorization: Bearer ...[/dim]
"""

    msg += f"""
[bold]Node join token:[/bold]  {join_token}
[dim]Example node command:[/dim]
[dim]  ollabridge-node join --control {local_url} --token {join_token}[/dim]
"""

    if public_url:
        msg += f"""
[bold yellow]🌍 Public URL:[/bold yellow]   [link={public_url}]{public_url}[/link]
[dim]Use {public_url}/v1 as your OpenAI base_url[/dim]
"""

    title = "🔗 Pairing Ready" if auth_mode == "pairing" else "🚀 Gateway Ready"
    console.print(Panel(msg, title=title, border_style="yellow" if auth_mode == "pairing" else "blue"))


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(11435, help="Bind port"),
    share: bool = typer.Option(False, "--share", help="Expose a public URL (best-effort)"),
    lan: bool = typer.Option(False, "--lan", help="Print LAN URL for other devices"),
    workers: int = typer.Option(1, "--workers", help="Worker processes (scalability hook)"),
    model: str = typer.Option("", "--model", help="Default chat model to ensure/use (empty = use .env or skip)"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
    log_level: str = typer.Option(
        "warning",
        "--log-level",
        help="Uvicorn log level (debug, info, warning, error, critical)",
    ),
    write_env: bool = typer.Option(
        False,
        "--write-env",
        help="If API_KEYS is missing, write a generated key to .env (off by default for safety).",
    ),
    auth_mode: str = typer.Option(
        "",
        "--auth-mode",
        help="Auth mode: required (static keys), local-trust (loopback bypass), pairing (device code exchange). Empty = use .env.",
    ),
    no_setup: bool = typer.Option(
        False,
        "--no-setup",
        help="Skip Ollama install/start/model-pull. Just start the gateway server.",
    ),
):
    """🚀 Start OllaBridge gateway.

    By default, auto-installs Ollama and pulls the default model.
    Use --no-setup to skip and configure backends from the UI instead.
    """

    # Resolve model: CLI flag → env → settings → default
    if not model:
        model = (os.getenv("DEFAULT_MODEL") or "").strip() or settings.DEFAULT_MODEL or "deepseek-r1"

    # Resolve auth_mode: CLI flag → env → settings
    if not auth_mode:
        auth_mode = (os.getenv("AUTH_MODE") or "").strip() or settings.AUTH_MODE or "required"

    if not no_setup:
        # 1) Self-healing: install Ollama
        if not is_ollama_installed():
            install_ollama()

        # 2) Start Ollama server (best effort)
        ensure_ollama_server_running()

        # 3) Ensure model exists
        ensure_model(model)
    else:
        console.print("[dim]Skipping Ollama setup (--no-setup). Configure backends from the UI.[/dim]")
        # When --no-setup, don't auto-register local Ollama unless the user
        # has already saved settings from the UI (runtime_settings.json exists).
        from ollabridge.core.runtime_settings import has_saved_settings
        if not has_saved_settings():
            os.environ["LOCAL_RUNTIME_ENABLED"] = "false"
            settings.LOCAL_RUNTIME_ENABLED = False

    # 4) Auth mode
    is_pairing = auth_mode.lower().strip() == "pairing"

    if is_pairing:
        # Pairing mode: generate a short human-readable code as the API key
        key = generate_pairing_code()
        configured_keys = key
    else:
        # Standard key mode: env var → .env → settings → auto-generate
        configured_keys = (os.getenv("API_KEYS") or "").strip()
        if not configured_keys:
            configured_keys = (_read_api_keys_from_dotenv() or "").strip()
        if not configured_keys:
            configured_keys = (settings.API_KEYS or "").strip()

        key = (configured_keys.split(",")[0].strip() if configured_keys else "")

        # Treat common defaults as "not configured"
        if (not key) or ("change-me" in key) or ("dev-key" in key):
            key = f"sk-ollabridge-{secrets.token_urlsafe(18)}"
            configured_keys = key
            if write_env:
                _write_env_key_if_missing(key)

    # Ensure the running process + singleton settings see the effective key
    os.environ["API_KEYS"] = configured_keys
    settings.API_KEYS = configured_keys

    # 4b) Set auth mode in settings
    auth_mode = auth_mode.lower().strip()
    os.environ["AUTH_MODE"] = auth_mode
    settings.AUTH_MODE = auth_mode

    # 4c) Generate pairing code if auth_mode=pairing (using PairingManager if available)
    pairing_code = None
    if is_pairing:
        try:
            from ollabridge.core.pairing import PairingManager
            mgr = PairingManager()
            pc = mgr.generate_code()
            pairing_code = pc.code
            # Pass the code to the app via env var so create_app()'s
            # PairingManager can recognise it (uvicorn reimports the module).
            os.environ["_OLLABRIDGE_INITIAL_PAIRING_CODE"] = pc.code
        except (ImportError, Exception):
            # Fallback: use the generated key as the pairing code
            pairing_code = key

    # 5) Enrollment token: compute nodes join the control plane with this short-lived credential.
    join_token = create_join_token().token

    # 6) Optional public access URL
    public_url = None
    if share:
        console.print("[green]🌍 Opening tunnel to public internet...[/green]")
        try:
            public_url = start_tunnel(port)
        except Exception as e:
            console.print(f"[red]Public link failed:[/red] {e}")
            console.print("[yellow]Tip:[/yellow] For production, use a managed edge or private overlay.")

    # Dev convenience: Uvicorn reload cannot be combined with multiple workers
    if reload and workers != 1:
        console.print("[yellow]⚠️  --reload forces --workers 1 (Uvicorn limitation).[/yellow]")
        workers = 1

    _dashboard(host, port, public_url, key, model, workers, join_token, auth_mode=auth_mode, pairing_code=pairing_code)

    # LAN mode: print URLs for other devices on the network
    if lan:
        lan_ip = _get_lan_ip()
        if lan_ip:
            console.print()
            console.print("[bold cyan]🌐 LAN Access[/bold cyan]")
            console.print(f"[bold]LAN API base:[/bold]    http://{lan_ip}:{port}/v1")
            console.print(f"[bold]LAN Health:[/bold]      http://{lan_ip}:{port}/health")
            console.print()
            console.print("[bold]Example (with API key):[/bold]")
            console.print(f"curl -H 'Authorization: Bearer <API_KEY>' http://{lan_ip}:{port}/v1/models")
            console.print()
        else:
            console.print("[yellow]⚠️  Could not detect LAN IP address[/yellow]")

    uvicorn.run(
        "ollabridge.api.main:app",
        host=host,
        port=port,
        workers=workers,
        log_level=log_level,
        reload=reload,
    )


@app.command()
def enroll_create(
    ttl_seconds: int = typer.Option(3600, "--ttl", help="Token TTL in seconds"),
):
    """Create a short-lived enrollment token for nodes to join the Control Plane."""
    tok = create_join_token(ttl_seconds=ttl_seconds)
    console.print(
        Panel(
            f"[bold]Token:[/bold] {tok.token}\n[bold]Expires:[/bold] {tok.expires_at.isoformat()}",
            title="🔑 Enrollment Token",
        )
    )


@app.command()
def up(
    share: bool = typer.Option(False, "--share", help="Alias of `start --share` (backwards compatible)."),
):
    """Backwards-compatible alias for older docs."""
    start(share=share)


@app.command()
def doctor(
    port: int = typer.Option(11435, help="OllaBridge port"),
    ollama_base: str = typer.Option("http://localhost:11434", help="Ollama base URL"),
):
    """🩺 Diagnose local setup (Ollama, OllaBridge, auth, CORS)."""
    table = Table(title="OllaBridge Doctor")
    table.add_column("Check")
    table.add_column("Result")

    # Ollama reachable?
    try:
        r = httpx.get(f"{ollama_base}/api/tags", timeout=3)
        table.add_row("Ollama /api/tags", "✅ OK" if r.status_code == 200 else f"❌ HTTP {r.status_code}")
    except Exception as e:
        table.add_row("Ollama /api/tags", f"❌ {type(e).__name__}")

    # OllaBridge health (no auth required)
    try:
        r = httpx.get(f"http://localhost:{port}/health", timeout=3)
        table.add_row("OllaBridge /health", "✅ OK" if r.status_code == 200 else f"❌ HTTP {r.status_code}")
    except Exception as e:
        table.add_row("OllaBridge /health", f"❌ {type(e).__name__}")

    # Auth + CORS config visibility
    table.add_row("Auth mode", settings.AUTH_MODE or "required")
    table.add_row("API_KEYS configured", "✅ yes" if settings.API_KEYS else "❌ missing")
    table.add_row("CORS_ORIGINS", settings.CORS_ORIGINS or "(disabled)")

    # Show how to call with key
    if (settings.AUTH_MODE or "").lower().strip() == "pairing":
        table.add_row("Auth usage", "Use pairing code via /pair or Authorization: Bearer <token>")
    else:
        table.add_row("Auth usage", "Use Authorization: Bearer <key> or X-API-Key: <key>")

    console.print(table)


@app.command()
def models(
    port: int = typer.Option(11435, help="OllaBridge port"),
    api_key: str = typer.Option(..., help="API key (required)"),
):
    """📦 List available models via OllaBridge (requires API key)."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = httpx.get(f"http://localhost:{port}/v1/models", headers=headers, timeout=15)
        r.raise_for_status()

        warn = r.headers.get("X-OllaBridge-Warning")
        if warn:
            console.print(f"[yellow]Warning:[/yellow] {warn}")

        data = r.json()
        for m in data.get("data", []):
            console.print(m.get("id"))
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP Error {e.response.status_code}:[/red] {e.response.text}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("test-chat")
def test_chat(
    prompt: str = typer.Argument("Say hello in one sentence."),
    port: int = typer.Option(11435, help="OllaBridge port"),
    model: str = typer.Option("", help="Model id (optional)"),
    api_key: str = typer.Option(..., help="API key (required)"),
):
    """💬 Send a test chat completion to OllaBridge (requires API key)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model or None,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }

    try:
        r = httpx.post(f"http://localhost:{port}/v1/chat/completions", headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        j = r.json()
        msg = j["choices"][0]["message"]["content"]
        console.print(Panel(msg, title="Assistant"))
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP Error {e.response.status_code}:[/red] {e.response.text}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command("pair-refresh")
def pair_refresh():
    """🔗 Generate a new pairing code (for AUTH_MODE=pairing)."""
    if (settings.AUTH_MODE or "").lower().strip() != "pairing":
        console.print("[yellow]AUTH_MODE is not 'pairing'. Set AUTH_MODE=pairing first.[/yellow]")
        raise typer.Exit(1)

    from ollabridge.core.pairing import PairingManager
    mgr = PairingManager()
    pc = mgr.generate_code()
    console.print(
        Panel(
            f"[bold]Pairing Code:[/bold] {pc.code}\n[bold]Expires in:[/bold] {pc.ttl}s",
            title="🔗 New Pairing Code",
            border_style="yellow",
        )
    )


if __name__ == "__main__":
    app()
