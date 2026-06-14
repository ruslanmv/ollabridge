"""`ollabridge providers` — secure BYOK provider management.

Keys are stored in the encrypted SecretStore (``~/.ollabridge/secrets.enc``);
``providers.yaml`` carries metadata only. Full keys are never printed, logged,
or exported.
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from ollabridge.core.redact import redact_secret
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    STORAGE_MODES,
    ProviderRecord,
    get_record,
    load_providers,
    remove_record,
    upsert_record,
)

providers_app = typer.Typer(
    no_args_is_help=True, help="🔑 Manage BYOK provider credentials."
)
console = Console()

_STORAGE_PROMPT = """Where should this provider secret live?

[1] Local only — safest, usable when this device is online
[2] Cloud encrypted vault — usable from your devices
[3] Organization vault — usable by your team according to policy
"""


def _resolve_storage_mode(choice: str) -> str:
    mapping = {
        "1": "local_only",
        "2": "cloud_encrypted_vault",
        "3": "organization_vault",
    }
    if choice in mapping:
        return mapping[choice]
    if choice in STORAGE_MODES:
        return choice
    raise typer.BadParameter(f"choose 1-3 or one of {STORAGE_MODES}")


def _vault_notice(mode: str) -> None:
    if mode == "local_only":
        return
    from ollabridge.cloud.device_config import load_cloud_device_credentials
    from ollabridge.cloud.sync_config import load_sync_config

    sync = load_sync_config()
    paired = load_cloud_device_credentials() is not None
    console.print(f"[yellow]Storage mode {mode!r} recorded.[/yellow]")
    if not paired:
        console.print(
            "[yellow]⚠ Not paired with OllaBridge Cloud — the key stays "
            "LOCAL-ONLY until you run `ollabridge login`.[/yellow]"
        )
    elif not sync.provider_secrets_cloud_vault:
        console.print(
            "[yellow]⚠ Cloud vault sync is opt-in and currently disabled — the key "
            "stays LOCAL-ONLY until you run:\n"
            "  ollabridge sync config provider_secrets_cloud_vault true[/yellow]"
        )
    else:
        console.print(
            "[yellow]⚠ The paired cloud has not enabled its vault API yet — the key "
            "stays LOCAL-ONLY (intent recorded; nothing was uploaded).[/yellow]"
        )


@providers_app.command("list")
def providers_list(as_json: bool = typer.Option(False, "--json")):
    """List configured providers (keys redacted)."""
    from ollabridge.provider_ops import get_secret

    records = load_providers()
    if as_json:
        from ollabridge.provider_ops import export_redacted

        print(json.dumps(export_redacted(), indent=2))
        return
    if not records:
        console.print(
            "No providers configured. Add one with:  ollabridge providers add <provider>"
        )
        console.print(f"[dim]Supported: {', '.join(sorted(PROVIDER_CATALOG))}[/dim]")
        return
    table = Table(title="BYOK providers")
    for col in ("Provider", "Kind", "Storage", "Key", "Last test"):
        table.add_column(col)
    for rec in records:
        key = get_secret(rec.name)
        test = "-"
        if rec.last_test_ok is not None:
            test = ("✅ " if rec.last_test_ok else "❌ ") + (rec.last_test_at or "")
        table.add_row(
            rec.name,
            rec.kind or rec.name,
            rec.storage_mode,
            redact_secret(key) if key else "[red](missing)[/red]",
            test,
        )
    console.print(table)


@providers_app.command("add")
def providers_add(
    provider: str = typer.Argument(
        ..., help=f"One of: {', '.join(sorted(PROVIDER_CATALOG))}"
    ),
    api_key: str = typer.Option(
        "", "--api-key", help="Key (omit to be prompted securely)"
    ),
    storage: str = typer.Option(
        "",
        "--storage",
        help="1|2|3 or local_only|cloud_encrypted_vault|organization_vault",
    ),
    base_url: str = typer.Option(
        "", "--base-url", help="Override/required for azure-openai and custom"
    ),
):
    """Add a provider credential (stored encrypted, never printed)."""
    from ollabridge.provider_ops import set_secret

    name = provider.lower().strip()
    spec = PROVIDER_CATALOG.get(name)
    if spec is None:
        console.print(
            f"[red]Unknown provider {name!r}.[/red] "
            f"Supported: {', '.join(sorted(PROVIDER_CATALOG))}"
        )
        raise typer.Exit(1)

    if not storage:
        console.print(_STORAGE_PROMPT)
        storage = typer.prompt("Choice", default="1")
    mode = _resolve_storage_mode(storage.strip())

    key = api_key or typer.prompt(f"{spec.label} API key", hide_input=True)
    key = key.strip()
    if not key:
        console.print("[red]Empty key — aborted.[/red]")
        raise typer.Exit(1)
    if spec.key_prefix and not key.startswith(spec.key_prefix):
        console.print(
            f"[yellow]⚠ Key does not start with the usual {spec.key_prefix!r} "
            f"prefix for {spec.label} — storing anyway.[/yellow]"
        )

    resolved_base = base_url.strip() or spec.base_url
    if name in ("azure-openai", "custom") and not resolved_base:
        console.print("[red]--base-url is required for this provider.[/red]")
        raise typer.Exit(1)

    set_secret(name, key)
    upsert_record(
        ProviderRecord(name=name, kind=name, storage_mode=mode, base_url=resolved_base)
    )

    from ollabridge.addons.providers.secret_store import SecretStore

    encrypted = SecretStore().is_encrypted
    console.print(
        f"[green]✅ {spec.label} key stored[/green] "
        f"({'encrypted at rest' if encrypted else 'plaintext 0o600 — set OLLA_SECRET!'}) "
        f"as {redact_secret(key)}"
    )
    if not encrypted:
        console.print(
            "[yellow]⚠ Set OLLA_SECRET and re-add the key to enable encryption.[/yellow]"
        )
    _vault_notice(mode)
    console.print(f"[dim]Test it:  ollabridge providers test {name}[/dim]")


@providers_app.command("remove")
def providers_remove(
    provider: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
):
    """Remove a provider and delete its stored key."""
    from ollabridge.provider_ops import delete_secret

    name = provider.lower().strip()
    if not yes and not typer.confirm(
        f"Remove provider {name!r} and delete its key?", default=False
    ):
        raise typer.Exit(0)
    removed_meta = remove_record(name)
    removed_key = delete_secret(name)
    if removed_meta or removed_key:
        console.print(f"[green]✅ Removed {name} (key deleted: {removed_key}).[/green]")
    else:
        console.print(f"[yellow]Provider {name!r} was not configured.[/yellow]")


@providers_app.command("test")
def providers_test(provider: str = typer.Argument(...)):
    """Check the provider key and endpoint health (no prompt content sent)."""
    from ollabridge.provider_ops import test_provider

    name = provider.lower().strip()
    ok, detail = test_provider(name)
    if ok:
        console.print(f"[green]✅ {name}: {detail}[/green]")
    else:
        console.print(f"[red]❌ {name}: {detail}[/red]")
        raise typer.Exit(1)


@providers_app.command("rotate")
def providers_rotate(
    provider: str = typer.Argument(...),
    api_key: str = typer.Option(
        "", "--api-key", help="New key (omit to be prompted securely)"
    ),
):
    """Replace a provider key and record the rotation time."""
    from ollabridge.provider_ops import get_secret, rotate_secret, test_provider

    name = provider.lower().strip()
    if not get_secret(name) and get_record(name) is None:
        console.print(
            f"[red]{name!r} is not configured — use `ollabridge providers add {name}`.[/red]"
        )
        raise typer.Exit(1)
    key = (api_key or typer.prompt(f"New {name} API key", hide_input=True)).strip()
    if not key:
        console.print("[red]Empty key — aborted.[/red]")
        raise typer.Exit(1)
    rec = rotate_secret(name, key)
    console.print(
        f"[green]✅ Rotated {name} key[/green] ({redact_secret(key)}), "
        f"rotated_at={rec.rotated_at}"
    )
    ok, detail = test_provider(name)
    console.print(f"{'[green]✅' if ok else '[red]❌'} post-rotation test: {detail}[/]")


@providers_app.command("status")
def providers_status(as_json: bool = typer.Option(False, "--json")):
    """Summary of provider configuration and storage security."""
    from ollabridge.addons.providers.secret_store import SecretStore
    from ollabridge.providers_meta import configured_provider_names

    store = SecretStore()
    configured = sorted(configured_provider_names(store))
    data = {
        "configured": configured,
        "encrypted_at_rest": store.is_encrypted,
        "storage_path": str(store.path),
    }
    if as_json:
        print(json.dumps(data, indent=2))
        return
    console.print(f"Configured providers: {', '.join(configured) or '(none)'}")
    console.print(
        f"Encrypted at rest: {'✅ yes' if store.is_encrypted else '❌ no — set OLLA_SECRET'}"
    )
    console.print(f"[dim]Secret store: {store.path}[/dim]")


@providers_app.command("export")
def providers_export(
    redacted: bool = typer.Option(
        False, "--redacted", help="Required: exports are always redacted."
    ),
):
    """Export provider configuration with keys redacted (JSON)."""
    from ollabridge.provider_ops import export_redacted

    if not redacted:
        console.print(
            "[yellow]Exports never include full keys. Re-run with --redacted "
            "to acknowledge, e.g.:  ollabridge providers export --redacted[/yellow]"
        )
        raise typer.Exit(1)
    print(json.dumps(export_redacted(), indent=2))
