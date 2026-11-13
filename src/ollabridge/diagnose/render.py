"""The report as text. The JSON form (``--json``) is the report dict itself."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table


def _s(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f} s" if value < 10 else f"{value:.1f} s"


def _n(value: Any, unit: str = "") -> str:
    if value is None:
        return "—"
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{text}{unit}"


def _rows(console: Console, title: str, rows: list[tuple[str, str]]) -> None:
    shown = [(k, v) for k, v in rows if v and v != "—"]
    if not shown:
        return
    console.print(f"\n[bold]{title}[/bold]")
    width = max(len(k) for k, _ in shown)
    for key, value in shown:
        console.print(f"  {key:<{width}}  {value}", highlight=False)


def _levels(console: Console, levels: list[dict[str, Any]], ended: str) -> None:
    if not levels:
        if ended:
            console.print(f"\n[bold]Concurrency[/bold]\n  {ended}", highlight=False)
        return
    table = Table(title=None, show_edge=False, pad_edge=False, box=None, header_style="bold")
    for column in ("in flight", "requests", "ok", "p50", "p95", "per minute", "result"):
        table.add_column(column, justify="left" if column == "result" else "right")
    for lv in levels:
        errors = ", ".join(f"{n} {kind.replace('_', ' ')}" for kind, n in lv["errors"].items())
        table.add_row(
            str(lv["concurrency"]),
            str(lv["requests"]),
            str(lv["ok"]),
            _s(lv["p50_s"]),
            _s(lv["p95_s"]),
            _n(lv["per_minute"]),
            errors or "clean",
        )
    console.print("\n[bold]Concurrency[/bold]")
    console.print(table)
    console.print(f"  {ended}", highlight=False)


def _rate_text(rate: dict[str, Any]) -> str:
    if rate["per_minute"] is None:
        return rate["note"]
    exact = "" if rate["exact"] else "about "
    parts = [f"{exact}{rate['per_minute']:g} requests a minute ({rate['source']}): {rate['note']}"]
    if rate["signalled_as"]:
        parts.append(f"refusals arrive as {rate['signalled_as']}")
    if rate["retry_after_sent"] is True:
        parts.append(f"Retry-After is sent ({rate['retry_after_s']:g} s)")
    elif rate["retry_after_sent"] is False:
        parts.append("no Retry-After is sent")
    if rate["recovers_after_s"] is not None:
        parts.append(f"a request is accepted again after {rate['recovers_after_s']:g} s")
    return "; ".join(parts)


def render(report: dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()
    target, safety = report["target"], report["safety"]
    base, upper = report.get("baseline") or {}, report["limits"]["upper"]
    advice, rate = report["recommendations"], report["rate_limit"]
    is_chat = report["kind"] == "chat"

    what = f"model {target['model']}" if is_chat else f"MCP server {target.get('server') or 'unnamed'}"
    console.print(f"[bold]Endpoint diagnosis[/bold] · {report['kind']} · {target['url']} · {what}", highlight=False)
    console.print(
        f"  {safety['http_requests']} HTTP request(s) in {report['duration_s']:g} s "
        f"(allowed: {safety['max_requests']} requests, {safety['max_seconds']:g} s) · mode {safety['mode']}",
        highlight=False,
    )
    if safety.get("tools_run"):
        console.print(f"  tools run: {', '.join(safety['tools_run'])}", highlight=False)
    if safety["stopped"]:
        console.print(f"  [yellow]ended early:[/yellow] {safety['stopped']}", highlight=False)
    if not base:
        return

    if is_chat:
        _rows(
            console,
            "Lower limits (no setting makes a call faster than this)",
            [
                ("fastest answer", _s(base.get("fastest_s"))),
                ("connection setup", _s(base.get("connection_setup_s")) + "  (paid again by every call that does not reuse a connection)"
                 if base.get("connection_setup_s") else ""),
                ("first token", _s(base.get("first_token_s"))),
                ("generation speed", _n(base.get("tokens_per_s"), " tokens/s")),
            ],
        )
    else:
        _rows(
            console,
            "Lower limits (no setting makes a call faster than this)",
            [
                ("handshake (2 requests)", _s(base.get("handshake_s"))),
                (f"fastest {base.get('probe_method', 'ping')}", _s(base.get("fastest_s"))),
                ("tools/list", _s(base.get("tools_list_s")) + (f"  ({base['tools']} tools)" if base.get("tools") is not None else "")),
                (
                    "call with its own session",
                    _s(base.get("own_session_call_s")) + f"  ({base.get('own_session_requests')} HTTP requests)"
                    if base.get("own_session_call_s") is not None
                    else "",
                ),
                (f"tool {base.get('tool')}", _s(base.get("tool_call_s")) if base.get("tool") else ""),
            ],
        )

    sizes = report.get("prompt_sizes") or []
    if sizes:
        console.print("\n[bold]Prompt size[/bold]")
        for row in sizes:
            line = f"  ~{row['target_tokens']} tokens"
            if row.get("tokens_in"):
                line += f" (counted {row['tokens_in']})"
            line += f": {_s(row['seconds'])}" if row["outcome"] == "ok" else f": {row['outcome']} after {_s(row['seconds'])} {row['detail']}"
            if row.get("first_token_s") is not None:
                line += f", first token {_s(row['first_token_s'])}"
            if row.get("projected_s") is not None:
                line += f", about {_s(row['projected_s'])} with a {advice['output_tokens_assumed']}-token answer"
            if row.get("fits_client_timeout") is False:
                line += "  [red]over the caller's timeout[/red]"
            console.print(line, highlight=False)

    _levels(console, report["levels"], report["sweep_ended"])

    _rows(
        console,
        "Upper limits",
        [
            (
                "peak throughput",
                f"{upper['peak_per_minute']:g} a minute at {upper['best_concurrency']} in flight"
                if upper["peak_per_minute"] is not None
                else "",
            ),
            ("highest clean concurrency", _n(upper["max_clean_concurrency"])),
            (
                "first failure",
                f"at {upper['first_failing_concurrency']} in flight: {upper['first_failure']}"
                if upper["first_failing_concurrency"] is not None
                else "",
            ),
            ("request limit", _rate_text(rate)),
            ("slowest answer", _s(upper["slowest_answer_s"])),
            ("timeouts", str(upper["timeouts"]) if upper["timeouts"] else ""),
        ],
    )

    if is_chat:
        client = advice["client"]
        _rows(
            console,
            "Recommended",
            [
                ("parallel calls", _n(advice["concurrency"])),
                ("requests a minute", _n(advice["requests_per_minute"]) if advice["requests_per_minute"] else "no pace needed"),
                ("caller timeout per try", _n(client["timeout_per_try_s"], " s")),
                (
                    "through OllaBridge, callers wait at least",
                    _n(client["outlast_the_queue_s"], " s  (max wait + answer time)"),
                ),
                ("retry", client["retry"]),
            ],
        )
        console.print("\n  OllaBridge → Settings → Rate limits, for the provider behind this endpoint:", highlight=False)
        console.print("  " + json.dumps(advice["provider_limit"]), highlight=False)
    else:
        calls, parallel, tasks = advice["tool_calls_per_minute"], advice["parallel_calls"], advice["parallel_tasks"]
        per_call = advice["requests_per_call"]
        _rows(
            console,
            "Recommended",
            [
                (
                    "HTTP requests per tool call",
                    f"{per_call['new_session_each_call']} with a session per call, {per_call['reused_session']} on a kept session",
                ),
                (
                    "tool calls a minute",
                    f"{calls['new_session_each_call']} with a session per call, {calls['reused_session']} on a kept session"
                    if calls
                    else "",
                ),
                (
                    "parallel tool calls",
                    f"{parallel['new_session_each_call']} with a session per call, {parallel['reused_session']} on a kept session "
                    f"(a call takes {parallel['call_seconds']:g} s)"
                    if parallel
                    else "",
                ),
                (
                    "parallel tasks",
                    f"{tasks['new_session_each_call']} with a session per call, {tasks['reused_session']} on kept sessions"
                    if tasks
                    else "",
                ),
                ("retry", advice["client"]["retry"]),
            ],
        )

    for line in advice["why"]:
        console.print(f"  • {line}", highlight=False)
    for note in report.get("notes") or []:
        console.print(f"  [dim]note: {note}[/dim]", highlight=False)


def render_plan(kind: str, target: dict[str, Any], plan: dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()
    console.print(f"[bold]Plan[/bold] · {kind} · {target['url']} · nothing is sent", highlight=False)
    for key, value in plan.items():
        console.print(f"  {key.replace('_', ' ')}: {json.dumps(value) if not isinstance(value, str) else value}", highlight=False)


def render_audit(findings: list[dict[str, str]], console: Console | None = None) -> None:
    console = console or Console()
    icon = {"ok": "[green]ok  [/green]", "warn": "[yellow]warn[/yellow]", "info": "[dim]info[/dim]"}
    console.print("[bold]Local settings, read for many calls at once[/bold]")
    for item in findings:
        console.print(f"  {icon.get(item['level'], item['level'])}  {item['subject']}: {item['detail']}", highlight=False)
        if item.get("fix"):
            console.print(f"        → {item['fix']}", highlight=False)
