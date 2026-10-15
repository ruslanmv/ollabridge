"""Process-wide logging for the gateway: one handler, one format, configured once.

Without this, application loggers had no handler at all. Python's last-resort
handler then prints WARNING and above as bare text (no timestamp, level or
logger name) and drops INFO entirely, which is why the server log showed
``local runtime /api/tags failed`` dozens of times with no way to tell
whether that was one minute or one hour of history.

Entry points call :func:`configure_logging` with the user's chosen level. The
app factory calls :func:`ensure_logging_configured`, which only acts when
nothing has configured logging yet, so an embedding application (or uvicorn's
reload/worker child processes, which never run the CLI code) still gets
timestamps while anyone with their own logging setup is left alone.
"""

from __future__ import annotations

import logging
import os
import sys

HANDLER_NAME = "ollabridge"
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,  # uvicorn's extra level; the stdlib has no finer one
}

#: Third-party loggers that narrate every request at INFO. They never go
#: below WARNING here, whatever the application level is.
NOISY_LOGGERS = {"httpx": logging.WARNING, "httpcore": logging.WARNING}


def level_from_name(level: str | int | None, default: int = logging.INFO) -> int:
    if isinstance(level, int):
        return level
    return _LEVELS.get((level or "").strip().lower(), default)


def configure_logging(level: str | int | None = None) -> logging.Handler:
    """Install (or reuse) the gateway's stderr handler and set the root level.

    Idempotent: calling it again only adjusts the level, so reloads and tests
    never stack duplicate handlers. ``level`` defaults to ``LOG_LEVEL`` from
    the environment, else INFO.
    """
    root = logging.getLogger()
    resolved = level_from_name(level if level is not None else os.environ.get("LOG_LEVEL"))

    handler = next((h for h in root.handlers if h.get_name() == HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(HANDLER_NAME)
        handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATEFMT))
        root.addHandler(handler)

    root.setLevel(resolved)
    for name, floor in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(max(floor, resolved))
    return handler


def ensure_logging_configured(level: str | int | None = None) -> bool:
    """Configure logging only if nobody has. Returns True when it did."""
    if logging.getLogger().handlers:
        return False
    configure_logging(level)
    return True
