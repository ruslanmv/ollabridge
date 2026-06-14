"""`ollabridge doctor` — diagnostics for local, cloud, relay, providers, security, e2e.

Running `ollabridge doctor` with no subcommand runs every applicable section
(backwards compatible with the old single doctor command, including its
--port/--ollama-base flags).
"""

from __future__ import annotations

import typer

from ollabridge.doctor.models import DoctorReport

doctor_app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="🩺 Diagnose local gateway, cloud pairing, relay, providers, and security.",
)

_JSON_OPT = typer.Option(
    False, "--json", help="Emit machine-readable JSON instead of text."
)


def _emit(report: DoctorReport, as_json: bool) -> None:
    from ollabridge.doctor.runner import render_report

    render_report(report, as_json=as_json)
    if not report.ok:
        raise typer.Exit(1)


@doctor_app.callback()
def doctor_all(
    ctx: typer.Context,
    port: int = typer.Option(11435, help="OllaBridge port"),
    ollama_base: str = typer.Option("http://localhost:11434", help="Ollama base URL"),
    as_json: bool = _JSON_OPT,
):
    """Run all applicable checks (local, cloud, relay, providers, security)."""
    if ctx.invoked_subcommand is not None:
        return
    from ollabridge.cloud.device_config import load_cloud_device_credentials
    from ollabridge.doctor import checks

    report = DoctorReport()
    report.sections.append(checks.check_local(port=port, ollama_base=ollama_base))
    cloud_section = checks.check_cloud()
    report.sections.append(cloud_section)
    if load_cloud_device_credentials() is not None:
        report.sections.append(checks.check_relay())
    report.sections.append(checks.check_providers())
    report.sections.append(checks.check_security())
    _emit(report, as_json)


@doctor_app.command("local")
def doctor_local(
    port: int = typer.Option(11435, help="OllaBridge port"),
    ollama_base: str = typer.Option("http://localhost:11434", help="Ollama base URL"),
    as_json: bool = _JSON_OPT,
):
    """Check the local gateway, config, API key, and Ollama."""
    from ollabridge.doctor import checks

    _emit(
        DoctorReport(sections=[checks.check_local(port=port, ollama_base=ollama_base)]),
        as_json,
    )


@doctor_app.command("cloud")
def doctor_cloud(as_json: bool = _JSON_OPT):
    """Check cloud credentials, reachability, pairing, and sync posture."""
    from ollabridge.doctor import checks

    _emit(DoctorReport(sections=[checks.check_cloud()]), as_json)


@doctor_app.command("relay")
def doctor_relay(
    timeout: float = typer.Option(10.0, help="Per-step timeout in seconds"),
    as_json: bool = _JSON_OPT,
):
    """Verify the WebSocket relay: connect, register, ping/pong, reconnect."""
    from ollabridge.doctor import checks

    _emit(DoctorReport(sections=[checks.check_relay(timeout=timeout)]), as_json)


@doctor_app.command("providers")
def doctor_providers(
    probe: bool = typer.Option(
        False, "--probe", help="Also call each provider's health endpoint."
    ),
    as_json: bool = _JSON_OPT,
):
    """Check which BYOK providers are configured (optionally probe them)."""
    from ollabridge.doctor import checks

    _emit(DoctorReport(sections=[checks.check_providers(probe=probe)]), as_json)


@doctor_app.command("security")
def doctor_security(as_json: bool = _JSON_OPT):
    """Check secret storage, file permissions, auth, CORS, and logging posture."""
    from ollabridge.doctor import checks

    _emit(DoctorReport(sections=[checks.check_security()]), as_json)


@doctor_app.command("e2e")
def doctor_e2e(
    port: int = typer.Option(11435, help="OllaBridge port"),
    model: str = typer.Option("", help="Model to test (default: first local model)"),
    timeout: float = typer.Option(120.0, help="Request timeout in seconds"),
    as_json: bool = _JSON_OPT,
):
    """Send a test request through the full path and measure latency."""
    from ollabridge.doctor.e2e import check_e2e

    _emit(
        DoctorReport(sections=[check_e2e(port=port, model=model, timeout=timeout)]),
        as_json,
    )
