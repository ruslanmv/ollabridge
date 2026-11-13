"""`ollabridge diagnose` — measure one endpoint and say how hard to drive it.

    ollabridge diagnose chat --model <model>                 # through this gateway
    ollabridge diagnose chat --base-url https://host/v1 --model <model> --api-key-env MY_KEY
    ollabridge diagnose mcp --url https://host/mcp --api-key-env MY_KEY --assume-limit 60
    ollabridge diagnose settings                             # audit, changes nothing

Safe by default: read-only requests, a hard budget of HTTP requests and
seconds, an early stop at the first refusal. ``--plan`` shows what would be
sent without sending it. Three things need an explicit flag: reaching the
rate limit on purpose (``--find-limit``), running a tool on an MCP server
(``--tool``), and writing a setting (``--apply``).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console

diagnose_app = typer.Typer(
    no_args_is_help=True,
    help="🔬 Measure one chat or MCP endpoint: its limits and the concurrency it takes.",
)

_out = Console()
_err = Console(stderr=True)


def _say(message: str) -> None:
    _err.print(f"[dim]{message}[/dim]", highlight=False)


def _levels(raw: str) -> list[int]:
    try:
        levels = sorted({int(part) for part in raw.replace(" ", "").split(",") if part})
    except ValueError:
        raise typer.BadParameter("use a comma-separated list of whole numbers, e.g. 1,2,4,8") from None
    if not levels or levels[0] < 1 or levels[-1] > 256:
        raise typer.BadParameter("concurrency levels must be between 1 and 256")
    return levels


def _secret(env_name: Optional[str]) -> str | None:
    if not env_name:
        return None
    value = os.environ.get(env_name, "").strip()
    if not value:
        _err.print(f"[red]The environment variable {env_name} is empty or not set.[/red]")
        raise typer.Exit(2)
    return value


def _headers(pairs: list[str]) -> dict[str, str]:
    """``NAME=ENVVAR`` → header NAME with the value of ENVVAR, so a secret is
    never typed on the command line."""
    out: dict[str, str] = {}
    for pair in pairs:
        name, sep, env_name = pair.partition("=")
        if not sep or not name.strip() or not env_name.strip():
            raise typer.BadParameter("--header takes NAME=ENVVAR, e.g. X-API-Key=MY_KEY_VARIABLE")
        out[name.strip()] = _secret(env_name.strip()) or ""
    return out


def _confirm(question: str, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        _err.print(f"[red]{question}[/red]\nRun again with --yes to go ahead.")
        raise typer.Exit(2)
    if not typer.confirm(question, default=False, err=True):
        raise typer.Exit(1)


def _emit(report: dict[str, Any], as_json: bool, save: Optional[Path]) -> None:
    from ollabridge.diagnose.render import render

    if save is not None:
        save.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _say(f"report saved to {save}")
    if as_json:
        typer.echo(json.dumps(report, indent=2))
    else:
        render(report, _out)


def _local_gateway(port: int) -> tuple[str, str | None]:
    from ollabridge.doctor.checks import _local_api_key

    return f"http://127.0.0.1:{port}", (_local_api_key() or None)


_CONCURRENCY = typer.Option("1,2,4,8", "--concurrency", "-c", help="Levels to try, lowest first.")
_PER_LEVEL = typer.Option(6, "--requests-per-level", min=1, max=500, help="Requests per level (at least two rounds are run).")
_MAX_SECONDS = typer.Option(300.0, "--max-seconds", min=5, help="Hard stop for the whole run.")
_QUICK = typer.Option(False, "--quick", help="Baseline only: no concurrency sweep.")
_FIND_LIMIT = typer.Option(
    False,
    "--find-limit",
    help="Also send until the first rate-limit answer, then time the recovery. Uses up this key's allowance for a minute.",
)
_YES = typer.Option(False, "--yes", "-y", help="Do not ask before --find-limit, --tool or --apply.")
_ASSUME = typer.Option(None, "--assume-limit", min=1, help="The endpoint's known limit, in requests a minute.")
_LIMIT_CONC = typer.Option(None, "--limit-concurrency", min=1, max=64, help="In-flight requests for --find-limit.")
_PLAN = typer.Option(False, "--plan", help="Show what would be sent, send nothing.")
_JSON = typer.Option(False, "--json", help="Print the report as JSON.")
_SAVE = typer.Option(None, "--save", help="Also write the JSON report to this file.")


@diagnose_app.command("chat")
def diagnose_chat_cmd(
    model: str = typer.Option(..., "--model", "-m", help="Model id as the endpoint knows it."),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="OpenAI-compatible base, e.g. https://host/v1. Default: this machine's OllaBridge."
    ),
    port: int = typer.Option(11435, help="OllaBridge port (for the default base URL and --apply)."),
    api_key_env: Optional[str] = typer.Option(
        None, "--api-key-env", help="Name of the environment variable that holds the API key."
    ),
    chat_path: str = typer.Option("/chat/completions", "--chat-path", help="Path under the base URL."),
    concurrency: str = _CONCURRENCY,
    requests_per_level: int = _PER_LEVEL,
    max_requests: Optional[int] = typer.Option(
        None, "--max-requests", min=3, help="Hard cap on HTTP requests (default 60; 200 with --find-limit)."
    ),
    max_seconds: float = _MAX_SECONDS,
    timeout: float = typer.Option(60.0, "--timeout", min=1, help="Seconds one request may take in this run."),
    quick: bool = _QUICK,
    find_limit: bool = _FIND_LIMIT,
    yes: bool = _YES,
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Measure time to first token with one streamed answer."),
    prompt_tokens: str = typer.Option(
        "", "--prompt-tokens", help="Also time prompts of about these sizes, e.g. 2000,8000,24000 (they cost tokens)."
    ),
    client_timeout: Optional[float] = typer.Option(
        None, "--client-timeout", min=1, help="Your caller's limit per try, in seconds: the report checks answers against it."
    ),
    output_tokens: Optional[int] = typer.Option(
        None, "--output-tokens", min=1, help="Typical answer length, to project the time of a long answer."
    ),
    assume_limit: Optional[float] = _ASSUME,
    limit_concurrency: Optional[int] = _LIMIT_CONC,
    apply: Optional[str] = typer.Option(
        None, "--apply", help="Save the recommended limits for this provider id (as in Settings → Rate limits)."
    ),
    plan: bool = _PLAN,
    as_json: bool = _JSON,
    save: Optional[Path] = _SAVE,
):
    """Measure a chat endpoint: fastest answer, speed, best concurrency, rate limit."""
    from ollabridge.diagnose.render import render_plan
    from ollabridge.diagnose.runner import ChatOptions, chat_plan, diagnose_chat
    from ollabridge.diagnose.targets import ChatTarget

    gateway, local_key = _local_gateway(port)
    api_key = _secret(api_key_env) or (local_key if base_url is None else None)
    sizes = _levels(prompt_tokens) if prompt_tokens.strip() else []
    opts = ChatOptions(
        levels=_levels(concurrency),
        per_level=requests_per_level,
        max_requests=max_requests or (200 if find_limit else 60),
        max_seconds=max_seconds,
        quick=quick,
        find_limit=find_limit,
        stream=stream,
        prompt_tokens=sizes,
        client_timeout=client_timeout,
        output_tokens=output_tokens,
        assume_limit=assume_limit,
        limit_concurrency=limit_concurrency,
    )
    target = ChatTarget(base_url or f"{gateway}/v1", model, api_key=api_key, chat_path=chat_path, timeout=timeout)

    if plan:
        if as_json:
            typer.echo(json.dumps({"target": target.describe(), "plan": chat_plan(opts)}, indent=2))
        else:
            render_plan("chat", target.describe(), chat_plan(opts), _out)
        return
    if find_limit:
        _confirm(
            "--find-limit sends requests until the endpoint refuses one. That uses up this key's allowance "
            "for about a minute, for every client that shares the key. Go ahead?",
            yes,
        )

    async def run() -> dict[str, Any]:
        async with target:
            return await diagnose_chat(target, opts, say=_say)

    report = asyncio.run(run())
    _emit(report, as_json, save)
    if not report["baseline"]:
        raise typer.Exit(1)

    if apply:
        from ollabridge.diagnose.audit import ApplyError, apply_provider_limit

        limit = report["recommendations"]["provider_limit"]
        if not limit["max_concurrent"] and not limit["requests_per_minute"]:
            _err.print("[red]Nothing to apply: neither a concurrency nor a request limit was measured.[/red]")
            raise typer.Exit(1)
        _confirm(f"Save these limits for provider {apply!r}? {json.dumps(limit)}", yes)
        try:
            done = apply_provider_limit(apply, limit, gateway=gateway, api_key=local_key)
        except ApplyError as exc:
            _err.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from None
        _err.print(
            f"Saved for {apply} in {done['where']}.\n  before: {json.dumps(done['before'])}\n  after:  {json.dumps(done['after'])}",
            highlight=False,
        )


@diagnose_app.command("mcp")
def diagnose_mcp_cmd(
    url: str = typer.Option(..., "--url", help="The MCP server's Streamable HTTP endpoint."),
    api_key_env: Optional[str] = typer.Option(
        None, "--api-key-env", help="Name of the environment variable whose value is sent as a Bearer token."
    ),
    header: list[str] = typer.Option(
        [], "--header", help="Extra header as NAME=ENVVAR (the value is read from that environment variable)."
    ),
    concurrency: str = typer.Option("1,2,4", "--concurrency", "-c", help="Levels to try, lowest first."),
    requests_per_level: int = _PER_LEVEL,
    max_requests: Optional[int] = typer.Option(
        None, "--max-requests", min=8, help="Hard cap on HTTP requests (default 40; 200 with --find-limit)."
    ),
    max_seconds: float = typer.Option(180.0, "--max-seconds", min=5, help="Hard stop for the whole run."),
    timeout: float = typer.Option(30.0, "--timeout", min=1, help="Seconds one request may take in this run."),
    quick: bool = _QUICK,
    find_limit: bool = _FIND_LIMIT,
    yes: bool = _YES,
    tool: Optional[str] = typer.Option(
        None, "--tool", help="Run this tool to time a real call. Only name a tool that reads; none runs otherwise."
    ),
    args: str = typer.Option("{}", "--args", help="The tool's arguments, as JSON."),
    tool_calls: int = typer.Option(1, "--tool-calls", min=1, max=20, help="How many times to run --tool."),
    call_seconds: Optional[float] = typer.Option(
        None, "--call-seconds", min=0.01, help="How long a typical tool call takes, when no --tool is run."
    ),
    calls_per_task: Optional[int] = typer.Option(None, "--calls-per-task", min=1, help="Tool calls one task (ticket, job) makes."),
    task_seconds: Optional[float] = typer.Option(None, "--task-seconds", min=1, help="How long one task runs."),
    assume_limit: Optional[float] = _ASSUME,
    limit_concurrency: Optional[int] = _LIMIT_CONC,
    plan: bool = _PLAN,
    as_json: bool = _JSON,
    save: Optional[Path] = _SAVE,
):
    """Measure an MCP server's HTTP edge: what a call costs, its limit, safe parallelism."""
    from ollabridge.diagnose.render import render_plan
    from ollabridge.diagnose.runner import McpOptions, diagnose_mcp, mcp_plan
    from ollabridge.diagnose.targets import McpTarget

    try:
        tool_args = json.loads(args)
    except ValueError:
        raise typer.BadParameter("--args must be JSON, e.g. '{\"domain\": \"example.com\"}'") from None
    if not isinstance(tool_args, dict):
        raise typer.BadParameter("--args must be a JSON object")

    headers = _headers(header)
    token = _secret(api_key_env)
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")
    opts = McpOptions(
        levels=_levels(concurrency),
        per_level=requests_per_level,
        max_requests=max_requests or (200 if find_limit else 40),
        max_seconds=max_seconds,
        quick=quick,
        find_limit=find_limit,
        tool=tool,
        tool_args=tool_args,
        tool_calls=tool_calls,
        call_seconds=call_seconds,
        calls_per_task=calls_per_task,
        task_seconds=task_seconds,
        assume_limit=assume_limit,
        limit_concurrency=limit_concurrency,
    )
    target = McpTarget(url, headers=headers, timeout=timeout)

    if plan:
        if as_json:
            typer.echo(json.dumps({"target": target.describe(), "plan": mcp_plan(opts)}, indent=2))
        else:
            render_plan("mcp", target.describe(), mcp_plan(opts), _out)
        return
    if tool:
        _confirm(
            f"--tool runs {tool!r} on the server {tool_calls} time(s) with {json.dumps(tool_args)}. "
            "Only do this for a tool that reads. Go ahead?",
            yes,
        )
    if find_limit:
        _confirm(
            "--find-limit sends pings until the server's edge refuses one. That uses up this key's allowance "
            "for about a minute, for every client that shares the key. Go ahead?",
            yes,
        )

    async def run() -> dict[str, Any]:
        async with target:
            return await diagnose_mcp(target, opts, say=_say)

    report = asyncio.run(run())
    _emit(report, as_json, save)
    if not report["baseline"].get("handshake_s"):
        raise typer.Exit(1)


@diagnose_app.command("settings")
def diagnose_settings_cmd(
    port: int = typer.Option(11435, help="OllaBridge port"),
    as_json: bool = _JSON,
):
    """Read the current settings for many calls at once. Changes nothing."""
    import httpx

    from ollabridge.diagnose.audit import audit_settings, configured_source_ids
    from ollabridge.diagnose.render import render_audit

    gateway, key = _local_gateway(port)
    view = None
    try:
        got = httpx.get(
            f"{gateway}/admin/rate-limits",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            timeout=5.0,
        )
        if got.status_code == 200:
            view = got.json()
        else:
            _say(f"the gateway answered HTTP {got.status_code} to /admin/rate-limits; reading the saved settings instead")
    except httpx.HTTPError:
        pass
    findings = audit_settings(view=view, source_ids=None if view is not None else configured_source_ids())
    if as_json:
        typer.echo(json.dumps({"gateway_running": view is not None, "findings": findings}, indent=2))
    else:
        render_audit(findings, _out)
    if any(item["level"] == "warn" for item in findings):
        raise typer.Exit(1)
