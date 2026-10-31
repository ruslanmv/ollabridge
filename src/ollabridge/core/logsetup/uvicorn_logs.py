"""Bring uvicorn's logging into the gateway's single format.

Uvicorn ships its own handlers and formatters (``INFO:     Started server
process``), which gave the console a second visual language. Here its loggers
are stripped of handlers and propagate to the root handler instead, and a
handler filter maps its messages onto OllaBridge's vocabulary:

- lifecycle chatter ("Waiting for application startup.") drops to DEBUG;
- "Uvicorn running on …" becomes the gateway's ``Ready in 1.2s`` line, logged
  after the socket is bound, which is the moment the gateway really is ready;
- access lines become ``GET /health 200`` with the client as a field and the
  level following the status (4xx WARN, 5xx ERROR);
- WebSocket handshakes read like access lines; per-connection open/close
  chatter drops to DEBUG.
"""

from __future__ import annotations

import logging
import time

from ollabridge.core.logsetup._text import format_duration
from ollabridge.core.logsetup.filters import COMPONENT_ATTR

#: Records not to repeat on the console; the JSON output still carries them.
TEXT_HIDE_ATTR = "_ob_text_hide"

#: Set by the app's request-log middleware when it is installed in this
#: process. Its line per request carries model, route and tokens, so
#: uvicorn's bare access lines are then dropped as duplicates.
APP_LOGS_REQUESTS = False

_HANDLED_ATTR = "_ob_uvicorn"

_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.asgi")

_DEMOTE = frozenset(
    {
        "Started server process [%d]",
        "Finished server process [%d]",
        "Waiting for application startup.",
        "Application startup complete.",
        "Waiting for application shutdown.",
        "Application shutdown complete.",
        "Shutting down",
        "Will watch for changes in these directories: %s",
        "connection open",
        "connection closed",
    }
)
_DEMOTE_PREFIXES = (
    "Started parent process [",
    "Stopping parent process [",
    "Waiting for child process [",
    "Terminated child process [",
)
_RUNNING = frozenset(
    {
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
        "Uvicorn running on %s://[%s]:%d (Press CTRL+C to quit)",
    }
)
_ACCESS = '%s - "%s %s HTTP/%s" %d'
_WS_ACCEPTED = '%s - "WebSocket %s" [accepted]'
_WS_STATUS = '%s - "WebSocket %s" %d'
_WS_403 = '%s - "WebSocket %s" 403'


def take_over() -> None:
    """Route uvicorn's loggers through the root handler.

    Idempotent. Levels are reset so OllaBridge's thresholds decide what shows.
    An access log that was explicitly disabled (``--no-access-log``: no
    handlers and ``propagate`` off) stays disabled.
    """
    for name in _LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(logging.NOTSET)
    access = logging.getLogger("uvicorn.access")
    if access.handlers or access.propagate:
        access.handlers = []
        access.propagate = True
        access.setLevel(logging.NOTSET)


def _set_level(record: logging.LogRecord, level: int) -> None:
    record.levelno = level
    record.levelname = logging.getLevelName(level)


def _status_level(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    return logging.INFO


def _url(scheme: str, host: str, port: int) -> tuple[str, str]:
    bind_host = f"[{host}]" if ":" in host else host
    shown = "localhost" if host in ("0.0.0.0", "::", "") else host
    if ":" in shown:
        shown = f"[{shown}]"
    return f"{scheme}://{shown}:{port}", f"{bind_host}:{port}"


class UvicornFilter(logging.Filter):
    """Translate uvicorn records into the gateway's vocabulary (see module doc)."""

    def __init__(self, started: float) -> None:
        super().__init__()
        self.started = started

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("uvicorn") or getattr(record, _HANDLED_ATTR, False):
            return True
        setattr(record, _HANDLED_ATTR, True)
        msg = record.msg
        if not isinstance(msg, str):
            return True
        args = record.args if isinstance(record.args, tuple) else ()

        if record.name == "uvicorn.access":
            if APP_LOGS_REQUESTS:
                return False
            if msg == _ACCESS and len(args) == 5:
                client, method, path, http_version, status = args
                record.msg, record.args = "%s %s %s", (method, path, status)
                record.method, record.path, record.status = method, path, status
                record.http_version = http_version
                record.client = client
                setattr(record, TEXT_HIDE_ATTR, ("method", "path", "status", "http_version"))
                try:
                    _set_level(record, _status_level(int(status)))
                except (TypeError, ValueError):
                    pass
            return True

        if msg in _DEMOTE or msg.startswith(_DEMOTE_PREFIXES):
            _set_level(record, logging.DEBUG)
        elif msg in _RUNNING and len(args) == 3:
            scheme, host, port = args
            url, bind = _url(str(scheme), str(host), int(port))
            record.url, record.bind = url, bind
            setattr(record, COMPONENT_ATTR, "gateway")
            if record.funcName == "bind_socket":
                # Reload / multi-worker: the parent binds, workers start next.
                record.msg, record.args = "Listening, starting worker processes", ()
            else:
                elapsed = format_duration(time.monotonic() - self.started)
                record.msg, record.args = "Ready in %s", (elapsed,)
        elif msg in (_WS_ACCEPTED, _WS_403, _WS_STATUS) and len(args) >= 2:
            client, path = args[0], args[1]
            status = 403 if msg == _WS_403 else (args[2] if msg == _WS_STATUS and len(args) > 2 else None)
            record.client, record.path = client, path
            setattr(record, COMPONENT_ATTR, "http")
            setattr(record, TEXT_HIDE_ATTR, ("path", "status"))
            if status is None:
                record.msg, record.args = "WS %s accepted", (path,)
            else:
                record.status = status
                record.msg, record.args = "WS %s %s", (path, status)
                try:
                    _set_level(record, _status_level(int(status)))
                except (TypeError, ValueError):
                    pass
        return True
