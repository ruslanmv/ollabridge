"""`ollabridge sync` — explicit, transparent cloud sync controls.

Defaults are privacy-first: only safe metadata syncs, and only after the
user enables sync (login enables it with metadata-only settings). Sensitive
categories must be flipped individually and are clearly labelled.
"""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

from ollabridge.cloud.sync_config import (
    METADATA_FIELDS,
    SENSITIVE_FIELDS,
    CloudSyncConfig,
    load_sync_config,
    save_sync_config,
)
from ollabridge.core import paths

sync_app = typer.Typer(
    no_args_is_help=True, help="🔄 Control what syncs to OllaBridge Cloud."
)
console = Console()


def _print_status(cfg: CloudSyncConfig) -> None:
    table = Table(title=f"Cloud sync — {'enabled' if cfg.enabled else 'disabled'}")
    table.add_column("Category")
    table.add_column("Syncs")
    table.add_column("Class")
    for field, value, sensitive in cfg.summary_rows():
        icon = "✅" if (value and cfg.enabled) else "❌"
        table.add_row(field, icon, "[red]sensitive[/red]" if sensitive else "metadata")
    console.print(table)
    console.print(f"[dim]Config file: {paths.sync_file()}[/dim]")
    if not cfg.enabled:
        console.print("[dim]Nothing syncs while sync is disabled.[/dim]")


@sync_app.command("status")
def sync_status(as_json: bool = typer.Option(False, "--json")):
    """Show what syncs to the cloud and what stays local."""
    cfg = load_sync_config()
    from ollabridge.cloud.device_config import load_cloud_device_credentials

    paired = load_cloud_device_credentials() is not None
    if as_json:
        print(json.dumps({"paired": paired, "cloud_sync": cfg.model_dump()}, indent=2))
        return
    if not paired:
        console.print(
            "[yellow]Not paired with OllaBridge Cloud.[/yellow] Run:  ollabridge login"
        )
    _print_status(cfg)


@sync_app.command("enable")
def sync_enable():
    """Enable metadata sync (device status, model names, routing profiles)."""
    cfg = load_sync_config()
    cfg.enabled = True
    save_sync_config(cfg)
    console.print("[green]✅ Cloud sync enabled (metadata only).[/green]")
    risky = cfg.sensitive_enabled()
    if risky:
        console.print(
            f"[red]⚠ Sensitive categories are also enabled: {', '.join(risky)}[/red]"
        )
    _print_status(cfg)


@sync_app.command("disable")
def sync_disable():
    """Disable all cloud sync."""
    cfg = load_sync_config()
    cfg.enabled = False
    save_sync_config(cfg)
    console.print(
        "[green]✅ Cloud sync disabled. Nothing will be sent to the cloud.[/green]"
    )


@sync_app.command("config")
def sync_config(
    field: str = typer.Argument(
        "", help="Field to change (e.g. model_metadata, prompt_logging)"
    ),
    value: str = typer.Argument("", help="true or false"),
):
    """Show or change a single sync setting."""
    cfg = load_sync_config()
    if not field:
        _print_status(cfg)
        return
    valid = ("enabled",) + METADATA_FIELDS + SENSITIVE_FIELDS
    if field not in valid:
        console.print(f"[red]Unknown field {field!r}.[/red] Valid: {', '.join(valid)}")
        raise typer.Exit(1)
    if value.lower() not in ("true", "false", "on", "off", "yes", "no", "1", "0"):
        console.print("[red]Value must be true or false.[/red]")
        raise typer.Exit(1)
    flag = value.lower() in ("true", "on", "yes", "1")
    if field in SENSITIVE_FIELDS and flag:
        console.print(
            f"[yellow]⚠ {field} is sensitive — it will sync to the cloud "
            "only because you explicitly enabled it.[/yellow]"
        )
        if not typer.confirm("Are you sure?", default=False):
            raise typer.Exit(0)
    setattr(cfg, field, flag)
    save_sync_config(cfg)
    console.print(f"[green]✅ {field} = {flag}[/green]")


@sync_app.command("push")
def sync_push():
    """Push the current metadata snapshot to the cloud now."""
    from ollabridge.cloud.device_config import load_cloud_device_credentials

    cfg = load_sync_config()
    creds = load_cloud_device_credentials()
    if creds is None:
        console.print(
            "[red]Not paired with OllaBridge Cloud.[/red] Run:  ollabridge login"
        )
        raise typer.Exit(1)
    if not cfg.enabled:
        console.print(
            "[yellow]Cloud sync is disabled.[/yellow] Run:  ollabridge sync enable"
        )
        raise typer.Exit(1)

    from ollabridge.cloud.preferences_sync import build_payload, push_to_cloud
    from ollabridge.providers_meta import load_providers

    # Metadata-only payload: provider names/kinds + (optionally) model names.
    providers_meta = (
        [
            {
                "id": r.name,
                "name": r.name,
                "kind": r.kind,
                "enabled": True,
                "tier": None,
                "category": None,
                "tags": [],
            }
            for r in load_providers()
        ]
        if cfg.routing_profiles
        else []
    )

    payload = build_payload(
        device_id=creds.device_id,
        providers=providers_meta,
        aliases={},
        hf_status=None,
    )
    try:
        result = asyncio.run(
            push_to_cloud(
                cloud_url=creds.cloud_url,
                device_token=creds.device_token,
                payload=payload,
            )
        )
        console.print(
            f"[green]✅ Pushed metadata snapshot to {creds.cloud_url}[/green]"
        )
        if isinstance(result, dict) and result.get("stored_at"):
            console.print(f"[dim]Stored at: {result['stored_at']}[/dim]")
    except RuntimeError as exc:
        console.print(f"[red]Push failed:[/red] {exc}")
        raise typer.Exit(1)


@sync_app.command("pull")
def sync_pull():
    """Pull synced metadata from the cloud (read-only preview)."""
    import httpx

    from ollabridge.cloud.device_config import load_cloud_device_credentials

    creds = load_cloud_device_credentials()
    if creds is None:
        console.print(
            "[red]Not paired with OllaBridge Cloud.[/red] Run:  ollabridge login"
        )
        raise typer.Exit(1)
    url = f"{creds.cloud_url.rstrip('/')}/api/devices/me/preferences"
    try:
        r = httpx.get(
            url, headers={"Authorization": f"Bearer {creds.device_token}"}, timeout=15
        )
    except httpx.HTTPError as exc:
        console.print(f"[red]Pull failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(1)
    if r.status_code == 404:
        console.print(
            "[yellow]The paired cloud does not support preferences pull yet "
            "(or nothing has been pushed).[/yellow]"
        )
        raise typer.Exit(0)
    if r.status_code >= 400:
        console.print(f"[red]Cloud returned HTTP {r.status_code}.[/red]")
        raise typer.Exit(1)
    print(json.dumps(r.json(), indent=2))
