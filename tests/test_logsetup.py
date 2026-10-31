"""Gateway logging: one handler, three renderings, redaction, thresholds, uvicorn.

Pins the contract in docs/LOGGING_DESIGN.md (Phase 1):

- the console layout (time · level · component · message · key=value fields)
  and the JSON keys log shippers parse;
- credential shapes are scrubbed from every line, whichever logger wrote it
  and whatever type the arguments are;
- CLI flag > OLLABRIDGE_LOG_* > .env > default, and the CLI hands the result
  to uvicorn's child processes through the environment;
- uvicorn's records render in the same format, its lifecycle chatter is DEBUG,
  and "Uvicorn running on" becomes the gateway's Ready line.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from datetime import date, datetime, timezone

import pytest

from ollabridge.core import logsetup
from ollabridge.core.logsetup import (
    ENV_FORMAT,
    ENV_LEVEL,
    ENV_LEVELS,
    ENV_UTC,
    LogConfig,
    component_for,
    format_duration,
    short_request_id,
    validate_cli_levels,
)
from ollabridge.core.logsetup.filters import ContextFilter
from ollabridge.core.logsetup.formatters import JsonFormatter, PlainFormatter, PrettyFormatter
from ollabridge.core.logsetup import uvicorn_logs
from ollabridge.core.logsetup.uvicorn_logs import UvicornFilter, take_over

FIXED = datetime(2026, 10, 29, 8, 41, 2, 337000, tzinfo=timezone.utc).timestamp()
SECRET = "sk-ant-" + "q" * 24  # built at runtime so no source line contains it
UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi")
_ENV_KEYS = (ENV_LEVEL, ENV_LEVELS, ENV_FORMAT, ENV_UTC, "LOG_LEVEL", logsetup.ENV_PARENT_PID)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """A root logger with no handlers and a clean environment; all restored after."""
    for key in _ENV_KEYS + ("NO_COLOR", "FORCE_COLOR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)  # no ./.env from the repository

    root = logging.getLogger()
    saved_root = (list(root.handlers), root.level)
    names = list(logsetup.NOISY_LOGGERS) + list(UVICORN)
    saved = {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers), logging.getLogger(n).propagate) for n in names}
    saved_active = logsetup._active
    for h in saved_root[0]:
        root.removeHandler(h)
    logsetup._once.reset()
    try:
        yield root
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_root[0]:
            root.addHandler(h)
        root.setLevel(saved_root[1])
        for n, (lvl, handlers, propagate) in saved.items():
            lg = logging.getLogger(n)
            lg.setLevel(lvl)
            lg.handlers = handlers
            lg.propagate = propagate
        logsetup._active = saved_active
        logsetup._once.reset()


def make_record(name="ollabridge", level=logging.INFO, msg="hello", args=(), exc_info=None, func=None, **extra):
    record = logging.LogRecord(name, level, __file__, 1, msg, args, exc_info, func=func)
    record.created, record.msecs = FIXED, 337.0
    for key, value in extra.items():
        setattr(record, key, value)
    ContextFilter().filter(record)
    return record


def pretty(color=False):
    fmt = PrettyFormatter(color=color, utc=True, width=80)
    fmt._last_day = None  # no date-rollover line unless a test asks for one
    return fmt


def configured(stream=None, **kwargs):
    buf = stream or io.StringIO()
    logsetup.configure_logging(stream=buf, **kwargs)
    return buf


# --- console layout ------------------------------------------------------------------


def test_pretty_line_layout():
    record = make_record(msg="Starting gateway", bind="0.0.0.0:11435", auth="local-trust", workers=1)
    assert pretty().format(record) == (
        "08:41:02.337  INFO   gateway    Starting gateway  bind=0.0.0.0:11435 auth=local-trust workers=1"
    )


def test_pretty_colours_level_and_dims_field_keys():
    line = pretty(color=True).format(make_record(level=logging.WARNING, msg="careful", node="a"))
    assert "\x1b[33mWARN \x1b[0m" in line
    assert "\x1b[90mnode=\x1b[0ma" in line


def test_pretty_aligns_continuation_lines_under_the_message():
    line = pretty().format(make_record(msg="first\nsecond"))
    first, second = line.split("\n")
    assert second == " " * first.index("first") + "second"


def test_pretty_prints_a_rule_when_the_date_rolls_over():
    fmt = pretty()
    fmt._last_day = date(2026, 10, 28)
    out = fmt.format(make_record())
    assert out.startswith("── 2026-10-29 ")
    assert out.splitlines()[1].startswith("08:41:02.337  INFO ")


def test_values_with_spaces_are_quoted_and_request_ids_shortened():
    record = make_record(msg="x", request_id="req_a1b2c3d4e5f6a7b8", reason="connection closed", empty="")
    line = pretty().format(record)
    assert 'req=a1b2c3d4 reason="connection closed" empty=""' in line


def test_plain_line_layout_has_iso_timestamp_and_no_colour():
    record = make_record(msg="Starting gateway", bind="0.0.0.0:11435")
    assert PlainFormatter(utc=True).format(record) == (
        "2026-10-29T08:41:02.337Z INFO  gateway    Starting gateway  bind=0.0.0.0:11435"
    )


def test_json_line_has_the_documented_keys():
    record = make_record(name="ollabridge.addons.local_catalog.sync_service", msg="Sync %s", args=("local",), models=3)
    obj = json.loads(JsonFormatter().format(record))
    assert obj["ts"] == "2026-10-29T08:41:02.337Z"
    assert obj["level"] == "info"
    assert obj["component"] == "catalog"
    assert obj["logger"] == "ollabridge.addons.local_catalog.sync_service"
    assert obj["msg"] == "Sync local"
    assert obj["models"] == 3
    assert obj["pid"] == os.getpid()
    assert obj["version"]
    assert list(obj)[:5] == ["ts", "level", "component", "logger", "msg"]


def test_json_field_named_like_a_core_key_does_not_overwrite_it():
    record = make_record(msg="m")
    record.level = "custom"  # e.g. extra={"level": ...} from a caller
    obj = json.loads(JsonFormatter().format(record))
    assert obj["level"] == "info" and obj["x_level"] == "custom"


# --- redaction --------------------------------------------------------------------


def test_secrets_are_scrubbed_from_any_logger_and_any_argument_type(isolated):
    buf = configured(fmt="plain")
    logging.getLogger("uvicorn.error").error("upstream said %s", ValueError(f"bad key {SECRET}"))
    logging.getLogger("some.library").warning("header Bearer abcdefghijklmnop", extra={"body": f"key={SECRET}"})
    out = buf.getvalue()
    assert SECRET not in out and "abcdefghijklmnop" not in out
    assert out.count("[REDACTED]") >= 3


def test_exception_text_is_redacted_in_every_format():
    try:
        raise RuntimeError(f"provider rejected {SECRET}")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()
    record = make_record(level=logging.ERROR, msg="call failed", exc_info=exc_info)
    for fmt in (pretty(), PlainFormatter(utc=True), JsonFormatter()):
        out = fmt.format(record)
        assert SECRET not in out
        assert "RuntimeError" in out and "[REDACTED]" in out
    obj = json.loads(JsonFormatter().format(record))
    assert obj["exc_type"] == "RuntimeError"
    assert obj["exc_message"] == "provider rejected [REDACTED]"


# --- configuration ------------------------------------------------------------------


def test_resolution_order_is_argument_env_dotenv_default():
    env = {ENV_LEVEL: "debug"}
    dot = {ENV_LEVEL: "warning"}
    assert LogConfig.resolve(level="error", environ=env, dotenv=dot).level == logging.ERROR
    assert LogConfig.resolve(environ=env, dotenv=dot).level == logging.DEBUG
    assert LogConfig.resolve(environ={}, dotenv=dot).level == logging.WARNING
    assert LogConfig.resolve(environ={}, dotenv={}).level == logging.INFO
    # LOG_LEVEL still works, but the namespaced variable wins.
    assert LogConfig.resolve(environ={"LOG_LEVEL": "error"}, dotenv={}).level == logging.ERROR
    assert LogConfig.resolve(environ={"LOG_LEVEL": "error", ENV_LEVEL: "debug"}, dotenv={}).level == logging.DEBUG


def test_bad_values_fall_back_and_are_reported_once(isolated, monkeypatch):
    monkeypatch.setenv(ENV_LEVEL, "loud")
    monkeypatch.setenv(ENV_FORMAT, "xml")
    monkeypatch.setenv(ENV_LEVELS, "catalog=chatty,oops")
    cfg = LogConfig.resolve(dotenv={})
    assert (cfg.level, cfg.format, cfg.levels) == (logging.INFO, "auto", ())
    assert len(cfg.problems) == 4
    buf = configured()
    configured(stream=buf)  # reconfiguring must not repeat the warnings
    warnings = [line for line in buf.getvalue().splitlines() if " WARN " in line]
    assert len(warnings) == 4
    assert any("'loud'" in w for w in warnings)


def test_config_round_trips_through_the_environment():
    cfg = LogConfig.resolve(level="warning", levels="catalog=debug", fmt="json", utc=True, environ={}, dotenv={})
    again = LogConfig.resolve(environ=cfg.to_env(), dotenv={})
    assert again == cfg


def test_cli_level_values_split_into_global_and_rules():
    assert validate_cli_levels(["info", "catalog=debug", "server=info,httpx=warning"]) == (
        "info",
        ["catalog=debug", "server=info", "httpx=warning"],
        [],
    )
    assert validate_cli_levels(None) == (None, [], [])
    assert validate_cli_levels(["verbose", "x=loud"])[2] == ["verbose", "x=loud"]


def test_configure_is_idempotent_and_swaps_the_format(isolated):
    first = logsetup.configure_logging("info", fmt="plain", stream=io.StringIO())
    second = logsetup.configure_logging("warning", fmt="json")
    assert first is second
    # pytest adds its own capture handlers around the test body; ours is one.
    assert [h.get_name() for h in isolated.handlers].count(logsetup.HANDLER_NAME) == 1
    assert isinstance(second.formatter, JsonFormatter)
    assert isolated.level == logging.WARNING


def test_auto_format_is_plain_off_a_terminal_and_pretty_when_forced(isolated, monkeypatch):
    logsetup.configure_logging(stream=io.StringIO())
    assert logsetup.get_active().layout == "plain"
    monkeypatch.setenv("FORCE_COLOR", "1")
    logsetup.configure_logging()
    assert (logsetup.get_active().layout, logsetup.get_active().color) == ("pretty", True)


# --- thresholds ---------------------------------------------------------------------


def test_component_and_logger_rules_override_the_global_level(isolated):
    buf = configured(level="info", levels="catalog=debug,somelib.engine=warning", fmt="plain")
    logging.getLogger("ollabridge.addons.local_catalog.sync_service").debug("catalog detail")
    logging.getLogger("ollabridge.addons.providers.registry").debug("provider detail")
    logging.getLogger("somelib.engine.Engine").info("SELECT 1")
    logging.getLogger("somelib.pool").info("pool checkout")
    out = buf.getvalue()
    assert "catalog detail" in out
    assert "provider detail" not in out
    assert "SELECT 1" not in out
    assert "pool checkout" in out
    assert isolated.level == logging.DEBUG  # low enough for the most verbose rule


def test_noisy_libraries_stay_at_warning_unless_a_rule_names_them(isolated):
    logsetup.configure_logging("debug", stream=io.StringIO())
    assert logging.getLogger("httpx").level == logging.WARNING
    logsetup.configure_logging("debug", levels="httpx=debug")
    assert logging.getLogger("httpx").level == logging.DEBUG
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_log_once_drops_repeats(isolated):
    buf = configured(fmt="plain")
    for _ in range(3):
        logging.getLogger("ollabridge").warning("OLLA_SECRET not set", extra={logsetup.ONCE_KEY: "olla-secret"})
    assert buf.getvalue().count("OLLA_SECRET not set") == 1


def test_session_header_shows_even_when_the_level_is_error(isolated):
    buf = configured(level="error", fmt="pretty")
    logsetup.log_session_header(role="gateway")
    line = buf.getvalue().strip()
    assert line.startswith("── OllaBridge ")
    assert "· gateway · " in line and "level error" in line and "format pretty" in line
    buf = configured(level="error", fmt="json")
    logsetup.log_session_header(role="node")
    obj = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert (obj["event"], obj["role"], obj["log_level"]) == ("session_start", "node", "error")


# --- context ------------------------------------------------------------------------


def test_context_fields_are_task_local(isolated):
    buf = configured(fmt="json")
    log = logging.getLogger("ollabridge")

    async def handle(rid: str) -> None:
        with logsetup.log_context(request_id=rid):
            await asyncio.sleep(0)
            log.info("working")

    async def main() -> None:
        await asyncio.gather(handle("req_aaaaaaaa1111"), handle("req_bbbbbbbb2222"))
        log.info("outside")

    asyncio.run(main())
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    working = sorted(o["request_id"] for o in lines if o["msg"] == "working")
    assert working == ["req_aaaaaaaa1111", "req_bbbbbbbb2222"]
    assert "request_id" not in next(o for o in lines if o["msg"] == "outside")


def test_request_middleware_binds_the_request_id(monkeypatch):
    from fastapi.testclient import TestClient

    from ollabridge.api.main import create_app

    app = create_app()

    @app.get("/_test/log-context")
    async def _ctx():
        return dict(logsetup.current_context())

    with TestClient(app) as client:
        body = client.get("/_test/log-context", headers={"X-Request-ID": "req_feedc0de0001"}).json()
    assert body == {"request_id": "req_feedc0de0001"}


def test_lifespan_logs_shutdown_with_uptime(caplog):
    from fastapi.testclient import TestClient

    from ollabridge.api.main import create_app

    with caplog.at_level(logging.INFO, logger="ollabridge"):
        with TestClient(create_app()):
            pass
    shutdown = [r for r in caplog.records if r.getMessage() == "Shutting down"]
    assert len(shutdown) == 1
    assert shutdown[0].uptime.endswith("s")


# --- uvicorn ------------------------------------------------------------------------


def test_take_over_strips_uvicorn_handlers_but_keeps_a_disabled_access_log(isolated):
    server, access = logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")
    server.handlers, server.propagate = [logging.StreamHandler(io.StringIO())], False
    access.handlers, access.propagate = [logging.StreamHandler(io.StringIO())], False
    take_over()
    assert (server.handlers, server.propagate) == ([], True)
    assert (access.handlers, access.propagate) == ([], True)

    access.handlers, access.propagate = [], False  # what --no-access-log leaves behind
    take_over()
    assert access.propagate is False


def test_uvicorn_lifecycle_chatter_is_debug(isolated):
    buf = configured(level="info", fmt="plain")
    logging.getLogger("uvicorn.error").info("Waiting for application startup.")
    logging.getLogger("uvicorn.error").info("Started server process [%d]", 42)
    assert buf.getvalue() == ""
    buf = configured(level="info", levels="server=debug", fmt="plain")
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    assert " DEBUG server     Application startup complete." in buf.getvalue()


@pytest.mark.parametrize(
    ("host", "url", "bind"),
    [
        ("0.0.0.0", "http://localhost:11435", "0.0.0.0:11435"),
        ("127.0.0.1", "http://127.0.0.1:11435", "127.0.0.1:11435"),
        ("::", "http://localhost:11435", "[::]:11435"),
    ],
)
def test_uvicorn_running_line_becomes_the_ready_line(host, url, bind):
    template = "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)"
    record = make_record(name="uvicorn.error", msg=template, args=("http", host, 11435), func="_log_started_message")
    UvicornFilter(started=0.0).filter(record)
    assert record.getMessage().startswith("Ready in ")
    assert (record.url, record.bind, record._ob_component) == (url, bind, "gateway")

    parent = make_record(name="uvicorn.error", msg=template, args=("http", host, 11435), func="bind_socket")
    UvicornFilter(started=0.0).filter(parent)
    assert parent.getMessage() == "Listening, starting worker processes"


@pytest.mark.parametrize(("status", "level"), [(200, logging.INFO), (404, logging.WARNING), (503, logging.ERROR)])
def test_access_lines_read_as_method_path_status(status, level, monkeypatch):
    # Without the app's request-log middleware (a bare ASGI app under uvicorn).
    monkeypatch.setattr(uvicorn_logs, "APP_LOGS_REQUESTS", False)
    record = make_record(
        name="uvicorn.access", msg='%s - "%s %s HTTP/%s" %d', args=("127.0.0.1:5000", "GET", "/health", "1.1", status)
    )
    UvicornFilter(started=0.0).filter(record)
    assert record.getMessage() == f"GET /health {status}"
    assert record.levelno == level
    plain = PlainFormatter(utc=True).format(record)
    assert plain.endswith(f"http       GET /health {status}  client=127.0.0.1:5000")
    obj = json.loads(JsonFormatter().format(record))
    assert (obj["method"], obj["path"], obj["status"], obj["client"]) == ("GET", "/health", status, "127.0.0.1:5000")


def test_websocket_handshake_reads_like_an_access_line():
    record = make_record(name="uvicorn.error", msg='%s - "WebSocket %s" [accepted]', args=("10.0.0.12:5000", "/relay/connect"))
    UvicornFilter(started=0.0).filter(record)
    assert record.getMessage() == "WS /relay/connect accepted"
    assert record._ob_component == "http"


# --- CLI hand-off -------------------------------------------------------------------


def _run_start(monkeypatch, *flags: str):
    """Invoke `ollabridge start` with uvicorn stubbed out; all env/settings it touches are restored."""
    from typer.testing import CliRunner

    from ollabridge.cli import main as cli
    from ollabridge.core.settings import settings

    for key in _ENV_KEYS:
        monkeypatch.setenv(key, "")
    for key in ("API_KEYS", "AUTH_MODE", "LOCAL_RUNTIME_ENABLED", "HOST"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("API_KEYS", "sk-ollabridge-test-only-key")
    for attr in ("API_KEYS", "AUTH_MODE", "LOCAL_RUNTIME_ENABLED"):
        monkeypatch.setattr(settings, attr, getattr(settings, attr))

    calls: list[dict] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.append(kw))
    result = CliRunner().invoke(
        cli.app,
        ["start", "--no-setup", "--no-open", "--host", "127.0.0.1", "--port", "11999", "--auth-mode", "local-trust", *flags],
    )
    return result, calls


@pytest.mark.parametrize(
    ("flags", "level"),
    [
        (["--verbose"], "debug"),
        (["-v"], "debug"),
        (["-v", "--log-level", "warning"], "warning"),  # an explicit level wins
        ([], "info"),
    ],
)
def test_verbose_is_shorthand_for_debug(isolated, monkeypatch, flags, level):
    result, _ = _run_start(monkeypatch, "--log-format", "plain", *flags)
    assert result.exit_code == 0, result.output
    assert os.environ[ENV_LEVEL] == level


def test_start_configures_logging_and_hands_it_to_uvicorn(isolated, monkeypatch):
    result, calls = _run_start(
        monkeypatch, "--log-format", "json", "--log-level", "info", "--log-level", "catalog=debug"
    )
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["log_config"] is None and calls[0]["log_level"] is None
    assert os.environ[ENV_FORMAT] == "json"
    assert os.environ[ENV_LEVEL] == "info"
    assert os.environ[ENV_LEVELS] == "catalog=debug"
    assert os.environ[logsetup.ENV_PARENT_PID] == str(os.getpid())

    records = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
    assert records[0]["event"] == "session_start"
    starting = next(r for r in records if r["msg"] == "Starting gateway")
    assert (starting["bind"], starting["auth"], starting["component"]) == ("127.0.0.1:11999", "local-trust", "gateway")


def test_start_rejects_an_unknown_log_level():
    from typer.testing import CliRunner

    from ollabridge.cli import main as cli

    result = CliRunner().invoke(cli.app, ["start", "--log-level", "verbose"])
    assert result.exit_code != 0
    assert "--log-level" in result.output


# --- helpers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "component"),
    [
        ("ollabridge", "gateway"),
        ("ollabridge.cli", "gateway"),
        ("ollabridge.addons.providers.services.provider_loader", "providers"),
        ("ollabridge.addons.providers.router", "router"),
        ("ollabridge.addons.providers.secret_store", "secrets"),
        ("ollabridge.addons.local_catalog.sync_service", "catalog"),
        ("ollabridge.reachability", "runtime"),
        ("ollabridge.cloud.bridge_manager", "cloud"),
        ("uvicorn.error", "server"),
        ("uvicorn.access", "http"),
        ("ollabridge.something_new.module_name", "module_nam"),
        ("sqlalchemy.engine.Engine", "sqlalchemy"),
    ],
)
def test_component_names(name, component):
    assert component_for(name) == component


def test_duration_and_request_id_helpers():
    assert [format_duration(s) for s in (0.94, 59.96, 245, 5700)] == ["0.9s", "60.0s", "4m05s", "1h35m"]
    assert short_request_id("req_a1b2c3d4e5f6") == "a1b2c3d4"
    assert short_request_id("client-supplied-id-123") == "client-suppl"
