"""`ollabridge login` / `logout` — optional OllaBridge Cloud pairing.

Login is never required for local mode. The flow is the TV-style device
code exchange the cloud already implements:

    POST /device/start  → user_code + verification URL
    (user approves in the browser)
    POST /device/poll   → device_id + device_token

On success the credentials are stored at ``~/.ollabridge/cloud_device.json``
(mode 0o600) and metadata-only sync is enabled in ``sync.yaml`` — sensitive
categories stay off.
"""

from __future__ import annotations

import os
import time

import typer
from rich.console import Console
from rich.panel import Panel

from ollabridge.cloud.api_client import CloudApiClient
from ollabridge.cloud.device_config import (
    CloudDeviceCredentials,
    _default_path,
    load_cloud_device_credentials,
    save_cloud_device_credentials,
)
from ollabridge.cloud.sync_config import load_sync_config, save_sync_config

console = Console()

DEFAULT_CLOUD_URL = "https://api.ollabridge.com"


def _cloud_url(cli_value: str) -> str:
    return (
        cli_value.strip()
        or os.environ.get("OLLABRIDGE_CLOUD_URL", "").strip()
        or DEFAULT_CLOUD_URL
    )


def login(
    cloud: str = typer.Option(
        "",
        "--cloud",
        help=f"Cloud base URL (default: $OLLABRIDGE_CLOUD_URL or {DEFAULT_CLOUD_URL})",
    ),
    poll_interval: float = typer.Option(3.0, help="Seconds between approval polls"),
    max_wait: float = typer.Option(600.0, help="Give up after this many seconds"),
):
    """🔐 Pair this device with OllaBridge Cloud (optional)."""
    cloud_url = _cloud_url(cloud)

    existing = load_cloud_device_credentials()
    if existing:
        console.print(
            f"[yellow]Already paired as device {existing.device_id} "
            f"with {existing.cloud_url}.[/yellow]"
        )
        if not typer.confirm("Pair again (replaces saved credentials)?", default=False):
            raise typer.Exit(0)

    client = CloudApiClient(cloud_url)
    try:
        try:
            start = client.device_start()
        except Exception as exc:
            console.print(
                f"[red]Could not reach OllaBridge Cloud at {cloud_url}:[/red] {exc}"
            )
            console.print(
                "[dim]Use --cloud or OLLABRIDGE_CLOUD_URL to point at your cloud.[/dim]"
            )
            raise typer.Exit(1)

        console.print(
            Panel(
                f"[bold]Open this URL:[/bold]\n  [link]{start.verification_url}[/link]\n\n"
                f"[bold]Enter code:[/bold]\n  [bold yellow]{start.user_code}[/bold yellow]\n\n"
                f"[dim]Code expires in {start.expires_in or 600}s[/dim]",
                title="🔗 OllaBridge Cloud Login",
                border_style="cyan",
            )
        )
        console.print("Waiting for approval...", style="dim")

        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                poll = client.device_poll(start.device_code)
            except Exception as exc:
                console.print(
                    f"[yellow]Poll error (will retry): {type(exc).__name__}[/yellow]"
                )
                time.sleep(poll_interval)
                continue
            if poll.status == "approved" and poll.approved:
                creds = CloudDeviceCredentials(
                    cloud_url=cloud_url,
                    device_id=poll.approved.device_id,
                    device_token=poll.approved.device_token,
                )
                path = save_cloud_device_credentials(creds)
                _post_login_summary(creds, path)
                return
            if poll.status == "expired":
                console.print(
                    "[red]Pairing code expired before approval.[/red] "
                    "Run `ollabridge login` again."
                )
                raise typer.Exit(1)
            time.sleep(poll_interval)

        console.print("[red]Timed out waiting for approval.[/red]")
        raise typer.Exit(1)
    finally:
        client.close()


def _post_login_summary(creds: CloudDeviceCredentials, path) -> None:
    # Enable metadata-only sync after explicit login; sensitive flags untouched.
    cfg = load_sync_config()
    cfg.enabled = True
    save_sync_config(cfg)

    console.print(f"[green]✅ Device paired:[/green] {creds.device_id}")
    console.print(f"[green]✅ Cloud API ready:[/green] {creds.cloud_url}/v1")
    console.print(f"[dim]Credentials saved to {path} (0600)[/dim]\n")

    console.print(
        "[bold]Cloud sync (metadata only — change with `ollabridge sync`):[/bold]"
    )
    for field, value, sensitive in cfg.summary_rows():
        icon = "✅" if value else "❌"
        suffix = (
            "  [red](sensitive — off by default)[/red]"
            if sensitive and not value
            else ""
        )
        console.print(f"  {icon} {field}{suffix}")
    console.print(
        "\n[dim]Models become visible to your cloud account once the gateway is "
        "running and the relay connects (ollabridge start). Verify with: "
        "ollabridge doctor relay[/dim]"
    )


def logout(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
):
    """🔓 Unpair from OllaBridge Cloud and delete saved credentials."""
    creds = load_cloud_device_credentials()
    if creds is None:
        console.print("[yellow]Not paired — nothing to do.[/yellow]")
        raise typer.Exit(0)
    if not yes and not typer.confirm(
        f"Delete credentials for device {creds.device_id} ({creds.cloud_url})?",
        default=True,
    ):
        raise typer.Exit(0)
    try:
        _default_path().unlink(missing_ok=True)
    except OSError as exc:
        console.print(f"[red]Could not delete credentials:[/red] {exc}")
        raise typer.Exit(1)
    cfg = load_sync_config()
    cfg.enabled = False
    save_sync_config(cfg)
    console.print(
        "[green]✅ Logged out. Cloud sync disabled; local mode unaffected.[/green]"
    )
    console.print(
        "[dim]The device may still be listed in the cloud dashboard — "
        "revoke it there to fully invalidate the token.[/dim]"
    )
