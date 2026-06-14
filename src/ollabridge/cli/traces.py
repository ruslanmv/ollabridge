"""`ollabridge traces` — inspect request traces (metadata only, no content)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

traces_app = typer.Typer(
    no_args_is_help=True, help="🔍 Inspect request traces (no prompt content)."
)
console = Console()


@traces_app.command("list")
def traces_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of traces to show"),
    as_json: bool = typer.Option(False, "--json"),
):
    """List recent request traces."""
    from ollabridge.tracing import get_trace_store

    traces = get_trace_store().list(limit=limit)
    if as_json:
        import json

        print(json.dumps([t.model_dump() for t in traces], indent=2))
        return
    if not traces:
        console.print(
            "No traces recorded yet. Traces are written by the running gateway."
        )
        return
    table = Table(title=f"Last {len(traces)} requests")
    for col in ("request_id", "ts", "model", "backend", "relay", "ms", "ok"):
        table.add_column(col)
    for t in traces:
        backend = t.provider or (f"device:{t.device}" if t.device else "-")
        table.add_row(
            t.request_id[:16] + "…",
            t.ts,
            t.resolved_model or t.requested_model or "-",
            backend,
            "yes" if t.cloud_relay else "no",
            str(t.latency_ms or "-"),
            "✅" if t.ok else f"❌ {t.error_category or ''}",
        )
    console.print(table)
    console.print("[dim]Details:  ollabridge traces show <request_id>[/dim]")


@traces_app.command("show")
def traces_show(request_id: str = typer.Argument(...)):
    """Show the full metadata trace for one request."""
    from ollabridge.tracing import get_trace_store

    store = get_trace_store()
    trace = store.get(request_id)
    if trace is None:
        # convenience: allow the truncated prefix shown by `traces list`
        for t in store.list(limit=500):
            if t.request_id.startswith(request_id.rstrip("…")):
                trace = t
                break
    if trace is None:
        console.print(f"[red]No trace with request_id {request_id!r}.[/red]")
        raise typer.Exit(1)
    print(trace.to_json())
