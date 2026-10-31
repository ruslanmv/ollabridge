"""Three renderings of one record model: ``pretty``, ``plain`` and ``json``.

pretty (colour terminal)::

    08:41:02.337  INFO   gateway    Ready in 1.2s  url=http://localhost:11435 bind=0.0.0.0:11435

plain (pipes, journald, ``make start | tee``)::

    2026-10-29T08:41:02.337+01:00 INFO  gateway    Ready in 1.2s  url=http://localhost:11435 bind=0.0.0.0:11435

json (containers, log shippers)::

    {"ts":"2026-10-29T07:41:02.337Z","level":"info","component":"gateway","logger":"uvicorn.error","msg":"Ready in 1.2s","url":"http://localhost:11435",…}

The message carries the decision, the ``key=value`` tail carries the data.
Fields come from ``extra=`` on the logging call and from the bound context.
Every rendering redacts credential shapes from the message, the fields and
exception text, whichever logger produced the record.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import IO, Any

from ollabridge.core.logsetup import tracebacks
from ollabridge.core.logsetup._text import format_value, short_request_id
from ollabridge.core.logsetup.components import WIDTH
from ollabridge.core.logsetup.filters import CONTEXT_KEYS_ATTR, ONCE_KEY, record_component
from ollabridge.core.logsetup.uvicorn_logs import TEXT_HIDE_ATTR
from ollabridge.core.redact import redact_mapping, redact_text

HEADER_ATTR = "_ob_header"

#: Attributes every LogRecord has; anything else on a record is a field.
_RESERVED = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
#: Extras some libraries attach that are not useful as fields.
_IGNORED = frozenset({"color_message", "websocket", ONCE_KEY})

_LEVEL_LABELS = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRIT",
}

# ANSI styles. Only the level carries strong colour; everything else is quiet.
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_GREY = "\x1b[90m"
_COMPONENT = "\x1b[36m"
_LEVEL_STYLES = {
    logging.DEBUG: "\x1b[90m",
    logging.INFO: "\x1b[32m",
    logging.WARNING: "\x1b[33m",
    logging.ERROR: "\x1b[1;31m",
    logging.CRITICAL: "\x1b[1;97;41m",
}

_PRETTY_INDENT = " " * (12 + 2 + 5 + 2 + WIDTH + 1)
_PLAIN_INDENT = "    "


# --- terminal detection ------------------------------------------------------------


def _enable_windows_vt(stream: IO[str]) -> bool:
    """Turn on ANSI processing for a Windows console; False when unavailable."""
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def supports_color(stream: IO[str] | None) -> bool:
    """Colour on a terminal unless ``NO_COLOR`` / ``TERM=dumb``; ``FORCE_COLOR`` wins."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb" or stream is None:
        return False
    try:
        tty = bool(stream.isatty())
    except Exception:
        tty = False
    if not tty:
        return False
    if sys.platform == "win32":
        return _enable_windows_vt(stream)
    return True


def resolve_layout(fmt: str, stream: IO[str] | None) -> tuple[str, bool]:
    """Map a configured format to ``(layout, color)``."""
    if fmt == "json":
        return "json", False
    if fmt == "plain":
        return "plain", False
    color = supports_color(stream)
    if fmt == "pretty":
        return "pretty", color
    return ("pretty", True) if color else ("plain", False)


def _terminal_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


# --- shared record helpers ------------------------------------------------------


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return redact_mapping(dict(value))
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_value(v) for v in value)
    return value


def record_fields(record: logging.LogRecord, *, for_text: bool) -> list[tuple[str, Any]]:
    """The record's fields: bound context first, then ``extra=`` values."""
    ctx_keys = getattr(record, CONTEXT_KEYS_ATTR, ())
    hidden = set(getattr(record, TEXT_HIDE_ATTR, ())) if for_text else set()
    ordered = list(ctx_keys) + [k for k in record.__dict__ if k not in ctx_keys]
    fields: list[tuple[str, Any]] = []
    for key in ordered:
        if key in _RESERVED or key in _IGNORED or key in hidden or key.startswith("_"):
            continue
        value = record.__dict__.get(key)
        if value is None and for_text:
            continue
        fields.append((key, _redact_value(value)))
    return fields


def record_message(record: logging.LogRecord) -> str:
    return redact_text(record.getMessage())


class _Base(logging.Formatter):
    def __init__(self, *, utc: bool = False) -> None:
        super().__init__()
        self.utc = utc

    def _datetime(self, record: logging.LogRecord) -> datetime:
        if self.utc:
            return datetime.fromtimestamp(record.created, tz=timezone.utc)
        return datetime.fromtimestamp(record.created).astimezone()

    @staticmethod
    def _iso(moment: datetime) -> str:
        text = moment.isoformat(timespec="milliseconds")
        return text[:-6] + "Z" if text.endswith("+00:00") else text


# --- pretty -------------------------------------------------------------------------


class PrettyFormatter(_Base):
    """Aligned, coloured console lines: time · level · component · message · fields."""

    def __init__(self, *, color: bool = True, utc: bool = False, width: int | None = None) -> None:
        super().__init__(utc=utc)
        self.color = color
        self.width = width
        self._last_day: date | None = self._today()

    def _today(self) -> date:
        now = datetime.now(timezone.utc) if self.utc else datetime.now().astimezone()
        return now.date()

    def _paint(self, text: str, style: str) -> str:
        return f"{style}{text}{_RESET}" if self.color and style else text

    def _rule(self, title: str, items: list[str]) -> str:
        width = min(self.width or _terminal_width(), 110)
        head = f"── {title}"
        body = "".join(f" · {item}" for item in items)
        plain_len = len(head) + len(body) + 1
        fill = "─" * max(3, width - plain_len)
        if not self.color:
            return f"{head}{body} {fill}"
        return (
            f"{_GREY}── {_RESET}{_BOLD}{title}{_RESET}"
            f"{_GREY}{body} {fill}{_RESET}"
        )

    def _header(self, record: logging.LogRecord) -> str:
        info: dict[str, Any] = getattr(record, HEADER_ATTR) or {}
        moment = self._datetime(record)
        self._last_day = moment.date()
        title = f"OllaBridge {info.get('version', '')}".strip()
        items = [str(info["role"])] if info.get("role") else []
        items.append(moment.date().isoformat())
        items.extend(str(i) for i in info.get("items", []))
        return self._rule(title, items)

    def _fields(self, record: logging.LogRecord) -> str:
        parts: list[str] = []
        for key, value in record_fields(record, for_text=True):
            if key == "request_id":
                key, value = "req", short_request_id(value)
            elif key == "node_id":
                key = "node"
            text = format_value(value)
            if self.color:
                parts.append(f"{_GREY}{key}={_RESET}{text}")
            else:
                parts.append(f"{key}={text}")
        return " ".join(parts)

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, HEADER_ATTR, None):
            return self._header(record)

        moment = self._datetime(record)
        prefix = ""
        if self._last_day is not None and moment.date() != self._last_day:
            prefix = self._rule(moment.date().isoformat(), []) + "\n"
        self._last_day = moment.date()

        level = _LEVEL_LABELS.get(record.levelno, record.levelname[:5])
        component = record_component(record)[:WIDTH]
        message = record_message(record)
        if record.levelno <= logging.DEBUG:
            message = self._paint(message, _GREY)
        message = message.replace("\n", "\n" + _PRETTY_INDENT)

        line = (
            f"{self._paint(moment.strftime('%H:%M:%S') + f'.{int(record.msecs):03d}', _GREY)}  "
            f"{self._paint(f'{level:<5}', _LEVEL_STYLES.get(record.levelno, ''))}  "
            f"{self._paint(f'{component:<{WIDTH}}', _COMPONENT)} "
            f"{message}"
        )
        fields = self._fields(record)
        if fields:
            line += "  " + fields
        if record.exc_info and record.exc_info[0] is not None:
            width = min(self.width or _terminal_width(), 120)
            line += "\n" + tracebacks.format_rich(record.exc_info, color=self.color, width=width)
        elif record.exc_text:
            line += "\n" + redact_text(record.exc_text)
        if record.stack_info:
            line += "\n" + redact_text(self.formatStack(record.stack_info))
        return prefix + line


# --- plain --------------------------------------------------------------------------


class PlainFormatter(_Base):
    """The pretty layout without colour, with a full ISO-8601 timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        level = _LEVEL_LABELS.get(record.levelno, record.levelname[:5])
        component = record_component(record)[:WIDTH]
        message = record_message(record).replace("\n", "\n" + _PLAIN_INDENT)
        line = f"{self._iso(self._datetime(record))} {level:<5} {component:<{WIDTH}} {message}"
        fields = []
        for key, value in record_fields(record, for_text=True):
            if key == "request_id":
                key, value = "req", short_request_id(value)
            elif key == "node_id":
                key = "node"
            fields.append(f"{key}={format_value(value)}")
        if fields:
            line += "  " + " ".join(fields)
        if record.exc_info and record.exc_info[0] is not None:
            line += "\n" + tracebacks.format_plain(record.exc_info)
        elif record.exc_text:
            line += "\n" + redact_text(record.exc_text)
        if record.stack_info:
            line += "\n" + redact_text(self.formatStack(record.stack_info))
        return line


# --- json ---------------------------------------------------------------------------

_JSON_CORE = ("ts", "level", "component", "logger", "msg")


def _version() -> str:
    try:
        from ollabridge import __version__

        return str(__version__)
    except Exception:
        return "unknown"


class JsonFormatter(_Base):
    """One JSON object per line, UTC timestamps, flat and stable keys."""

    def __init__(self) -> None:
        super().__init__(utc=True)
        self.version = _version()

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": self._iso(self._datetime(record)),
            "level": logging.getLevelName(record.levelno).lower(),
            "component": record_component(record),
            "logger": record.name,
            "msg": record_message(record),
        }
        for key, value in record_fields(record, for_text=False):
            obj[f"x_{key}" if key in _JSON_CORE or key in ("pid", "version") else key] = value
        obj["pid"] = record.process
        obj["version"] = self.version
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, _ = record.exc_info
            obj["exc_type"] = getattr(exc_type, "__name__", str(exc_type))
            obj["exc_message"] = redact_text(str(exc_value))
            obj["stack"] = tracebacks.format_plain(record.exc_info)
        elif record.exc_text:
            obj["stack"] = redact_text(record.exc_text)
        if record.stack_info:
            obj["stack_info"] = redact_text(self.formatStack(record.stack_info))
        return json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":"))


def make_formatter(layout: str, *, color: bool, utc: bool) -> logging.Formatter:
    if layout == "json":
        return JsonFormatter()
    if layout == "pretty":
        return PrettyFormatter(color=color, utc=utc)
    return PlainFormatter(utc=utc)
