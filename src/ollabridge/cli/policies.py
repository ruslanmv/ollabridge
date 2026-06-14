"""`ollabridge policies` and `ollabridge route` — explainable policy routing."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from ollabridge.core import paths
from ollabridge.policies import (
    RouteExplanation,
    explain_route,
    find_policy,
    load_policies,
    validate_policies_file,
)

policies_app = typer.Typer(no_args_is_help=True, help="📜 Manage routing policies.")
route_app = typer.Typer(
    no_args_is_help=True, help="🧭 Explain how a model/alias would route."
)
console = Console()


@policies_app.command("validate")
def policies_validate():
    """Validate ~/.ollabridge/policies.yaml."""
    p = paths.policies_file()
    problems = validate_policies_file()
    if not p.exists():
        console.print(
            f"[yellow]No user policy file at {p} — built-in policies apply.[/yellow]"
        )
        return
    if problems:
        console.print(f"[red]❌ {p} has {len(problems)} problem(s):[/red]")
        for prob in problems:
            console.print(f"  • {prob}")
        raise typer.Exit(1)
    console.print(f"[green]✅ {p} is valid.[/green]")


@policies_app.command("list")
def policies_list(as_json: bool = typer.Option(False, "--json")):
    """List active policies (user-defined override built-ins)."""
    pols = load_policies()
    if as_json:
        print(json.dumps([p.model_dump() for p in pols], indent=2))
        return
    builtin_names = {p.name for p in load_policies(include_builtin=True)} - {
        p.name for p in load_policies(include_builtin=False)
    }
    table = Table(title="Routing policies")
    for col in ("Policy", "Matches", "Prefer", "Fallback", "Prompt logging", "Source"):
        table.add_column(col)
    for p in pols:
        match = p.match.alias or p.match.model or ""
        prefer = (
            " → ".join(
                t.provider + (f":{t.model}" if t.model else "") for t in p.route.prefer
            )
            or "(gateway default)"
        )
        table.add_row(
            p.name,
            match,
            prefer,
            "yes" if p.route.fallback else "no",
            "[red]on[/red]" if p.logging.prompt_logging else "off",
            "built-in" if p.name in builtin_names else "user",
        )
    console.print(table)
    console.print(f"[dim]User policy file: {paths.policies_file()}[/dim]")


def _render_explanation(exp: RouteExplanation) -> None:
    console.print(f"[bold]Requested:[/bold] {exp.requested}")
    if exp.policy_name:
        console.print(f"[bold]Policy:[/bold] {exp.policy_name}")
    if exp.selected_backend == "local_device":
        console.print(
            f"[bold]Selected backend:[/bold] local device {exp.selected_device!r}"
        )
    elif exp.selected_backend:
        console.print(f"[bold]Selected backend:[/bold] {exp.selected_backend}")
    else:
        console.print("[bold red]Selected backend:[/bold red] none")
    if exp.selected_model:
        console.print(f"[bold]Selected model:[/bold] {exp.selected_model}")
    if exp.reasons:
        console.print("[bold]Reason:[/bold]")
        for r in exp.reasons:
            console.print(f"  - {r}")
    if exp.fallbacks:
        console.print(f"[bold]Fallbacks:[/bold] {' → '.join(exp.fallbacks)}")
    console.print(
        f"[bold]Prompt logging:[/bold] {'enabled' if exp.prompt_logging else 'disabled'}"
    )
    console.print(f"[bold]Cloud relay:[/bold] {'yes' if exp.cloud_relay else 'no'}")
    console.print(f"[bold]Provider used:[/bold] {exp.selected_provider or 'none'}")
    if exp.estimated_cost_usd_per_1k_tokens is not None:
        cost = exp.estimated_cost_usd_per_1k_tokens
        console.print(
            f"[bold]Estimated cost:[/bold] "
            f"{'$0' if cost == 0 else f'~${cost}/1k tokens'}"
        )
    if exp.error:
        console.print(f"[yellow]Note: {exp.error}[/yellow]")


@policies_app.command("explain")
def policies_explain(
    alias: str = typer.Argument(..., help="Alias or policy name"),
    as_json: bool = typer.Option(False, "--json"),
):
    """Explain which backend a policy/alias would select right now."""
    if find_policy(alias) is None:
        console.print(
            f"[red]No policy matches {alias!r}.[/red] " "See:  ollabridge policies list"
        )
        raise typer.Exit(1)
    exp = explain_route(alias)
    if as_json:
        print(exp.model_dump_json(indent=2))
        return
    _render_explanation(exp)


@route_app.command("explain")
def route_explain(
    model_or_alias: str = typer.Argument(
        ..., help="Model id or alias (e.g. coding, local-private)"
    ),
    as_json: bool = typer.Option(False, "--json"),
):
    """Explain how a request for this model/alias would be routed right now."""
    exp = explain_route(model_or_alias)
    if as_json:
        print(exp.model_dump_json(indent=2))
        return
    _render_explanation(exp)
