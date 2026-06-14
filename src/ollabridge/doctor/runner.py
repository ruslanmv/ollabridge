"""Render doctor reports for humans (rich) and machines (JSON)."""

from __future__ import annotations

from rich.console import Console

from ollabridge.doctor.models import CheckStatus, DoctorReport, SectionReport

console = Console()


def render_section(sec: SectionReport) -> None:
    console.print(f"\n[bold]{sec.name}:[/bold]")
    for c in sec.checks:
        line = f"  {c.status.icon} {c.name}"
        if c.detail:
            line += f" — {c.detail}"
        style = {
            CheckStatus.OK: "green",
            CheckStatus.WARN: "yellow",
            CheckStatus.FAIL: "red",
            CheckStatus.SKIP: "dim",
        }[c.status]
        console.print(f"[{style}]{line}[/{style}]")
        if c.hint and c.status in (
            CheckStatus.WARN,
            CheckStatus.FAIL,
            CheckStatus.SKIP,
        ):
            console.print(f"      [dim]{c.hint}[/dim]")
    for note in sec.notes:
        console.print(f"  [dim]ℹ {note}[/dim]")


def render_report(report: DoctorReport, *, as_json: bool = False) -> None:
    if as_json:
        # Plain print: JSON output must stay machine-parseable.
        print(report.to_json())
        return
    console.print("[bold]OllaBridge Doctor[/bold]")
    for sec in report.sections:
        render_section(sec)
    console.print()
    if report.ok:
        console.print("[bold green]No blocking problems found.[/bold green]")
    else:
        console.print("[bold red]Some checks failed — see hints above.[/bold red]")
