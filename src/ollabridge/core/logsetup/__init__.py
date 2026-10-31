"""Process-wide logging for OllaBridge: one handler, three renderings.

One stderr handler on the root logger renders every record, OllaBridge's,
uvicorn's and third-party libraries', in a single format:

- ``pretty``: aligned, coloured lines for a terminal;
- ``plain``: the same layout without colour and with ISO-8601 timestamps,
  for pipes and journald;
- ``json``: one object per line for containers and log shippers.

``auto`` (the default) picks ``pretty`` on a colour terminal and ``plain``
everywhere else. Credential shapes are scrubbed from every line.

Entry points call :func:`configure_logging`. The app factory calls
:func:`ensure_logging_configured`, which only acts when nothing has configured
logging yet, so uvicorn's reload and worker processes (which never run the
CLI) and a bare ``uvicorn ollabridge.api.main:app`` still get the same output,
while an embedding application with its own logging setup is left alone.

Configuration (CLI flag → environment → ``./.env`` → default):

=========================  ===================================================
``OLLABRIDGE_LOG_LEVEL``   ``debug`` ``info`` ``warning`` ``error`` (``LOG_LEVEL`` is a deprecated alias)
``OLLABRIDGE_LOG_LEVELS``  per component or logger: ``catalog=debug,server=info,httpx=warning``
``OLLABRIDGE_LOG_FORMAT``  ``auto`` ``pretty`` ``plain`` ``json``
``OLLABRIDGE_LOG_UTC``     ``1`` for UTC timestamps on the console (JSON is always UTC)
``NO_COLOR``/``FORCE_COLOR``  standard colour overrides
=========================  ===================================================
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import IO, Any

from ollabridge.core.logsetup._text import format_duration, short_request_id
from ollabridge.core.logsetup.components import COMPONENTS, component_for
from ollabridge.core.logsetup.config import (
    ENV_FORMAT,
    ENV_LEVEL,
    ENV_LEVELS,
    ENV_UTC,
    FORMATS,
    LogConfig,
    level_from_name,
    level_name,
    parse_level,
    parse_levels,
    validate_cli_levels,
)
from ollabridge.core.logsetup.context import bind, current as current_context, log_context, unbind
from ollabridge.core.logsetup.filters import (
    ALWAYS_KEY,
    ONCE_KEY,
    ContextFilter,
    LevelFilter,
    OnceFilter,
)
from ollabridge.core.logsetup.formatters import (
    HEADER_ATTR,
    JsonFormatter,
    PlainFormatter,
    PrettyFormatter,
    make_formatter,
    resolve_layout,
    supports_color,
)
from ollabridge.core.logsetup import uvicorn_logs
from ollabridge.core.logsetup.uvicorn_logs import UvicornFilter

__all__ = [
    "COMPONENTS",
    "FORMATS",
    "HANDLER_NAME",
    "NOISY_LOGGERS",
    "ONCE_KEY",
    "ActiveLogging",
    "JsonFormatter",
    "LogConfig",
    "PlainFormatter",
    "PrettyFormatter",
    "bind",
    "component_for",
    "configure_logging",
    "current_context",
    "ensure_logging_configured",
    "export_to_environ",
    "format_duration",
    "get_active",
    "is_child_process",
    "level_from_name",
    "level_name",
    "log_context",
    "log_session_header",
    "parse_level",
    "parse_levels",
    "short_request_id",
    "supports_color",
    "unbind",
    "validate_cli_levels",
]

HANDLER_NAME = "ollabridge"

#: Third-party loggers that narrate every request or every frame at INFO or
#: DEBUG. They never go below WARNING, whatever the global level is; a rule
#: naming them (``httpx=debug``) still opens them up.
NOISY_LOGGERS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "websockets": logging.WARNING,
    "watchfiles": logging.WARNING,
    "asyncio": logging.WARNING,
    "multipart": logging.WARNING,
}

#: Set in the environment by the process that configured logging first (the
#: CLI) so uvicorn's reload and worker children do not repeat the header.
ENV_PARENT_PID = "_OLLABRIDGE_LOG_PARENT_PID"

#: Roughly process start: the ``Ready in …`` line measures from here.
PROCESS_STARTED = time.monotonic()


@dataclass(frozen=True)
class ActiveLogging:
    """The configuration in force plus what it resolved to on this stream."""

    config: LogConfig
    layout: str
    color: bool


_active: ActiveLogging | None = None
_once = OnceFilter()


def get_active() -> ActiveLogging | None:
    """What :func:`configure_logging` set up in this process, if anything."""
    return _active


def _find_handler(root: logging.Logger) -> logging.Handler | None:
    return next((h for h in root.handlers if h.get_name() == HANDLER_NAME), None)


def _apply_logger_levels(cfg: LogConfig) -> None:
    rules = cfg.level_map
    for name, floor in NOISY_LOGGERS.items():
        explicit = next(
            (lvl for key, lvl in rules.items() if name == key or name.startswith(key + ".")),
            None,
        )
        logging.getLogger(name).setLevel(explicit if explicit is not None else max(floor, cfg.level))


def configure_logging(
    level: str | int | None = None,
    *,
    levels: str | Mapping[str, Any] | Iterable[str] | None = None,
    fmt: str | None = None,
    utc: bool | None = None,
    stream: IO[str] | None = None,
    config: LogConfig | None = None,
) -> logging.Handler:
    """Install (or reconfigure) the gateway's handler on the root logger.

    Idempotent: calling it again swaps the formatter and thresholds on the
    same handler, so reloads and tests never stack duplicate handlers.
    Arguments override the environment; anything left ``None`` is resolved
    from ``OLLABRIDGE_LOG_*``, then ``./.env``, then defaults.
    """
    global _active
    cfg = config or LogConfig.resolve(level=level, levels=levels, fmt=fmt, utc=utc)

    root = logging.getLogger()
    handler = _find_handler(root)
    if handler is None:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.set_name(HANDLER_NAME)
        root.addHandler(handler)
    elif stream is not None and isinstance(handler, logging.StreamHandler):
        handler.setStream(stream)

    layout, color = resolve_layout(cfg.format, getattr(handler, "stream", None))
    handler.setFormatter(make_formatter(layout, color=color, utc=cfg.utc))
    handler.setLevel(logging.NOTSET)
    for existing in list(handler.filters):
        handler.removeFilter(existing)
    # Order matters: tag the record, translate uvicorn's, then decide.
    handler.addFilter(ContextFilter())
    handler.addFilter(UvicornFilter(PROCESS_STARTED))
    handler.addFilter(LevelFilter(cfg.level, cfg.levels))
    handler.addFilter(_once)

    root.setLevel(cfg.min_level)
    _apply_logger_levels(cfg)
    uvicorn_logs.take_over()

    _active = ActiveLogging(config=cfg, layout=layout, color=color)

    log = logging.getLogger("ollabridge")
    for problem in cfg.problems:
        log.warning(problem, extra={ONCE_KEY: f"config:{problem}"})
    return handler


def ensure_logging_configured(level: str | int | None = None) -> bool:
    """Configure logging only if nobody has. Returns True when it did."""
    if logging.getLogger().handlers:
        return False
    configure_logging(level)
    return True


def export_to_environ(environ: dict[str, str] | None = None) -> None:
    """Hand the active configuration to child processes through the environment.

    uvicorn's reload and worker processes re-import the app without running
    the CLI; :func:`ensure_logging_configured` there reads these variables.
    The resolved layout is exported rather than ``auto`` so children render
    exactly like the parent.
    """
    env = os.environ if environ is None else environ
    active = _active
    if active is None:
        return
    env.update(active.config.to_env(format_override=active.layout))
    env[ENV_PARENT_PID] = str(os.getpid())


def is_child_process() -> bool:
    """True inside a process started by one that already printed the header."""
    parent = os.environ.get(ENV_PARENT_PID, "")
    return bool(parent) and parent != str(os.getpid())


def log_session_header(role: str = "gateway", **fields: Any) -> None:
    """Emit the one-line session header.

    It always shows, whatever the level, so a pasted log says which version,
    process and settings produced it. In ``pretty`` mode it is a rule line;
    ``plain`` and ``json`` render it as an ordinary record.
    """
    from ollabridge.core.logsetup.formatters import _version

    active = _active
    version = _version()
    lvl = level_name(active.config.level) if active else "info"
    layout = active.layout if active else "plain"
    rules = ",".join(f"{k}={level_name(v)}" for k, v in (active.config.levels if active else ()))
    items = [f"pid {os.getpid()}", f"level {lvl}"]
    if rules:
        items.append(f"rules {rules}")
    items.append(f"format {layout}")
    items.extend(f"{k} {v}" for k, v in fields.items() if v is not None)

    log = logging.getLogger("ollabridge")
    extra: dict[str, Any] = {
        "event": "session_start",
        "role": role,
        "log_level": lvl,
        "log_format": layout,
        HEADER_ATTR: {"version": version, "role": role, "items": items},
        ALWAYS_KEY: True,
    }
    if rules:
        extra["log_levels"] = rules
    extra.update({k: v for k, v in fields.items() if v is not None})
    record = log.makeRecord(
        log.name, logging.INFO, __file__, 0, "OllaBridge %s %s started", (version, role), None, extra=extra
    )
    log.handle(record)
