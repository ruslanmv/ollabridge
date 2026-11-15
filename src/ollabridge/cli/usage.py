"""`ollabridge usage` — token and cost usage (metadata only, no content)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import typer
from rich.console import Console
from rich.table import Table

usage_app = typer.Typer(
    no_args_is_help=True, help="📊 Token and cost usage (no prompt content)."
)
console = Console()


def _usd(micro: int | None) -> str:
    return "—" if micro is None else f"${micro / 1_000_000:,.4f}"


@usage_app.command("summary")
def usage_summary(
    days: int = typer.Option(30, "--days", "-d", min=1, max=400, help="Period length in days"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Tokens, cost and top agents for the last N days."""
    from ollabridge.usage import bi_core
    from ollabridge.usage.store import get_usage_store

    store = get_usage_store()
    end = dt.datetime.now(dt.timezone.utc).date()
    start = end - dt.timedelta(days=days - 1)
    prev_start, prev_end = bi_core.previous_period(start, end)
    rows, previous = store.rollup_rows(start, end), store.rollup_rows(prev_start, prev_end)
    overview = bi_core.overview(
        rows, previous, start=start, end=end, budget_limit_micro=store.get_budget_limit(),
        month_rows=store.rollup_rows(end.replace(day=1), end), today=end,
    )
    providers = bi_core.breakdown(rows, by="provider", metric="tokens")
    agents = bi_core.agents(rows, previous, limit=5)
    if as_json:
        print(json.dumps({"overview": overview, "providers": providers, "agents": agents}, indent=2))
        return
    if not overview["requests"]["value"]:
        console.print("[dim]No usage recorded in this period.[/dim]")
        return

    mix = overview["total_tokens"]["measurement_mix"]
    quality = ", ".join(f"{share:.0%} {badge}" for badge, share in mix.items()) or "—"
    console.print(f"[bold]Usage {start} → {end}[/bold]")
    console.print(f"  Tokens            {overview['total_tokens']['value']:,}  [dim]({quality})[/dim]")
    console.print(f"  Requests          {overview['requests']['value']:,}"
                  f"  [dim]({overview['requests']['failed']} failed)[/dim]")
    console.print(f"  Estimated cost    {_usd(overview['estimated_cost_micro']['value'])}  [dim]API usage[/dim]")
    console.print(f"  Billed cost       {_usd(overview['billed_cost_micro']['value'])}  [dim]stated by providers[/dim]")
    equivalent = overview["subscription_equivalent_micro"]["value"]
    if equivalent:
        console.print(f"  Subscription use  {_usd(equivalent)}  [dim]API-equivalent, not a charge[/dim]")
    if overview["estimated_cost_micro"]["unpriced_tokens"]:
        console.print("  [yellow]Some API usage has no price in the catalog; cost is a lower bound.[/yellow]")
    if overview["budget"]:
        console.print(f"  Budget remaining  {_usd(overview['budget']['remaining_micro'])}"
                      f" of {_usd(overview['budget']['limit_micro'])}")

    table = Table(title="By provider")
    table.add_column("Provider"); table.add_column("Tokens", justify="right"); table.add_column("Share", justify="right")
    for item in providers["items"]:
        table.add_row(item["key"], f"{item['value']:,}", f"{item['share']:.1%}")
    console.print(table)

    table = Table(title="Top agents / workflows")
    for column in ("Application", "Agent", "Provider"):
        table.add_column(column)
    table.add_column("Tokens", justify="right"); table.add_column("Cost", justify="right")
    for item in agents["items"]:
        table.add_row(item["application_id"], item["agent_id"], item["top_provider"],
                      f"{item['tokens']:,}", _usd(item["cost_micro"]))
    console.print(table)


@usage_app.command("budget")
def usage_budget(
    usd: float = typer.Argument(None, help="Monthly budget in USD; omit to show, 0 to remove"),
):
    """Show or set the monthly budget."""
    from ollabridge.usage.store import get_usage_store

    store = get_usage_store()
    if usd is not None:
        store.set_budget_limit(int(round(usd * 1_000_000)) if usd > 0 else None)
    console.print(f"Monthly budget: {_usd(store.get_budget_limit())}")


@usage_app.command("claude-code")
def usage_claude_code():
    """Print the environment that sends Claude Code usage to this gateway."""
    from ollabridge.core.settings import settings

    endpoint = f"http://127.0.0.1:{settings.PORT}/otlp"
    console.print("[bold]Add to your shell profile, then restart Claude Code:[/bold]\n")
    # print(), not rich: these lines are meant to be copied verbatim.
    print("export CLAUDE_CODE_ENABLE_TELEMETRY=1")
    print("export OTEL_LOGS_EXPORTER=otlp")
    print("export OTEL_EXPORTER_OTLP_PROTOCOL=http/json")
    print(f"export OTEL_EXPORTER_OTLP_ENDPOINT={endpoint}")
    console.print(
        f"\n[dim]Usage is recorded as '{settings.CLAUDE_CODE_BILLING}' billing "
        "(set CLAUDE_CODE_BILLING=api if Claude Code runs on an API key).\n"
        "Only token counts, model and cost estimate are stored — never prompts.\n"
        "Check arrival with:  ollabridge usage summary[/dim]"
    )


@usage_app.command("sync")
def usage_sync():
    """Upload pending usage metadata to OllaBridge Cloud now (opt-in only)."""
    from ollabridge.usage import outbox

    result = asyncio.run(outbox.sync_once())
    if "skipped" in result:
        console.print(f"[yellow]Nothing uploaded:[/yellow] {result['skipped']}")
        return
    if "error" in result:
        console.print(f"[red]Upload stopped ({result['error']}).[/red] Pending events are kept.")
    console.print(f"Synced {result['synced']}, rejected {result['rejected']}.")


@usage_app.command("prune")
def usage_prune(
    keep_days: int = typer.Option(..., "--keep-days", min=1, help="Delete usage older than this"),
):
    """Delete local usage records older than N days."""
    from ollabridge.usage.store import get_usage_store

    console.print(f"Removed {get_usage_store().prune(keep_days)} usage record(s).")
