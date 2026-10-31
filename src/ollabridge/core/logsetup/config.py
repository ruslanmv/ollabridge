"""Logging configuration: one resolved :class:`LogConfig` per process.

Every field is resolved with the same precedence:

1. an explicit argument (the CLI flag),
2. the ``OLLABRIDGE_LOG_*`` environment variable (``LOG_LEVEL`` is still read
   as a deprecated alias for the level),
3. the same key in ``./.env``,
4. the built-in default.

The CLI exports the resolved values back to the environment before starting
uvicorn, so reload and worker processes, which re-import the app but never run
the CLI, render exactly like the parent.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

ENV_LEVEL = "OLLABRIDGE_LOG_LEVEL"
ENV_LEVELS = "OLLABRIDGE_LOG_LEVELS"
ENV_FORMAT = "OLLABRIDGE_LOG_FORMAT"
ENV_UTC = "OLLABRIDGE_LOG_UTC"
LEGACY_ENV_LEVEL = "LOG_LEVEL"

#: ``auto`` picks ``pretty`` on a colour terminal and ``plain`` everywhere else.
FORMATS = ("auto", "pretty", "plain", "json")

_LEVELS = {
    "critical": logging.CRITICAL,
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,  # uvicorn's extra level; the stdlib has no finer one
}

_NAMES = {
    logging.CRITICAL: "critical",
    logging.ERROR: "error",
    logging.WARNING: "warning",
    logging.INFO: "info",
    logging.DEBUG: "debug",
}

_TRUE = {"1", "true", "yes", "on"}


def parse_level(value: str | int | None) -> int | None:
    """Strict level parsing: a known name or an int, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.isdigit():
        return int(text)
    return _LEVELS.get(text)


def level_from_name(level: str | int | None, default: int = logging.INFO) -> int:
    """Lenient level parsing: unknown or empty names fall back to *default*."""
    parsed = parse_level(level)
    return default if parsed is None else parsed


def level_name(level: int) -> str:
    return _NAMES.get(level) or logging.getLevelName(level).lower()


def parse_levels(spec: str | Mapping[str, Any] | Iterable[str] | None) -> tuple[dict[str, int], list[str]]:
    """Parse per-component levels.

    Accepts ``"catalog=debug,server=info"``, a list of ``key=level`` strings,
    or a mapping. Keys are component names (``catalog``) or logger names
    (``sqlalchemy.engine``). Returns the parsed rules and a list of entries
    that could not be understood.
    """
    rules: dict[str, int] = {}
    problems: list[str] = []
    if not spec:
        return rules, problems
    if isinstance(spec, Mapping):
        items: Iterable[tuple[str, Any]] = spec.items()
    else:
        entries = spec.split(",") if isinstance(spec, str) else list(spec)
        pairs: list[tuple[str, Any]] = []
        for raw in entries:
            entry = str(raw).strip()
            if not entry:
                continue
            key, sep, value = entry.partition("=")
            if not sep or not key.strip():
                problems.append(entry)
                continue
            pairs.append((key, value))
        items = pairs
    for key, value in items:
        level = parse_level(value)
        if level is None:
            problems.append(f"{str(key).strip()}={value}")
            continue
        rules[str(key).strip()] = level
    return rules, problems


def _read_dotenv() -> dict[str, str]:
    """The ``./.env`` values, read only when the environment did not answer."""
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(".env").items() if v is not None}
    except Exception:
        return {}


@dataclass(frozen=True)
class LogConfig:
    """Resolved logging configuration. Immutable; build it with :meth:`resolve`."""

    level: int = logging.INFO
    levels: tuple[tuple[str, int], ...] = ()
    format: str = "auto"
    utc: bool = False
    #: Human-readable notes about settings that were ignored, logged once
    #: logging is up (a typo in an env var must not be silent).
    problems: tuple[str, ...] = ()

    @property
    def level_map(self) -> dict[str, int]:
        return dict(self.levels)

    @property
    def min_level(self) -> int:
        return min([self.level, *(lvl for _, lvl in self.levels)])

    @classmethod
    def resolve(
        cls,
        *,
        level: str | int | None = None,
        levels: str | Mapping[str, Any] | Iterable[str] | None = None,
        fmt: str | None = None,
        utc: bool | None = None,
        environ: Mapping[str, str] | None = None,
        dotenv: Mapping[str, str] | None = None,
        default_level: int = logging.INFO,
    ) -> "LogConfig":
        env = os.environ if environ is None else environ
        dotenv_cache: list[Mapping[str, str]] = [] if dotenv is None else [dotenv]

        def from_dotenv() -> Mapping[str, str]:
            if not dotenv_cache:
                dotenv_cache.append(_read_dotenv())
            return dotenv_cache[0]

        def pick(explicit: Any, *keys: str) -> tuple[Any, str]:
            if explicit not in (None, "", (), []):
                return explicit, "argument"
            for key in keys:
                value = env.get(key)
                if value not in (None, ""):
                    return value, key
            values = from_dotenv()
            for key in keys:
                value = values.get(key)
                if value not in (None, ""):
                    return value, f".env {key}"
            return None, ""

        problems: list[str] = []

        raw_level, source = pick(level, ENV_LEVEL, LEGACY_ENV_LEVEL)
        resolved_level = parse_level(raw_level)
        if resolved_level is None:
            if raw_level is not None:
                problems.append(
                    f"Ignoring unknown log level {raw_level!r} from {source}; "
                    f"using {level_name(default_level)}"
                )
            resolved_level = default_level

        raw_levels, source = pick(levels, ENV_LEVELS)
        rules, bad = parse_levels(raw_levels)
        for entry in bad:
            problems.append(f"Ignoring log level rule {entry!r} from {source}; expected component=level")

        raw_fmt, source = pick(fmt, ENV_FORMAT)
        resolved_fmt = str(raw_fmt or "auto").strip().lower()
        if resolved_fmt not in FORMATS:
            problems.append(
                f"Ignoring unknown log format {raw_fmt!r} from {source}; "
                f"expected one of {', '.join(FORMATS)}"
            )
            resolved_fmt = "auto"

        raw_utc, _ = pick(utc, ENV_UTC)
        resolved_utc = raw_utc if isinstance(raw_utc, bool) else str(raw_utc or "").strip().lower() in _TRUE

        return cls(
            level=resolved_level,
            levels=tuple(rules.items()),
            format=resolved_fmt,
            utc=resolved_utc,
            problems=tuple(problems),
        )

    def to_env(self, *, format_override: str | None = None) -> dict[str, str]:
        """Environment variables that reproduce this config in a child process."""
        return {
            ENV_LEVEL: level_name(self.level),
            ENV_LEVELS: ",".join(f"{k}={level_name(v)}" for k, v in self.levels),
            ENV_FORMAT: format_override or self.format,
            ENV_UTC: "1" if self.utc else "0",
        }


def validate_cli_levels(values: Iterable[str] | None) -> tuple[str | None, list[str], list[str]]:
    """Split repeated ``--log-level`` values into a global level and rules.

    ``["info", "catalog=debug"]`` → ``("info", ["catalog=debug"], [])``. The
    last bare level wins. Unknown entries are returned in the third element so
    the CLI can reject them with a clear message.
    """
    global_level: str | None = None
    rules: list[str] = []
    errors: list[str] = []
    for raw in values or ():
        for entry in str(raw).split(","):
            entry = entry.strip()
            if not entry:
                continue
            if "=" in entry:
                _, bad = parse_levels(entry)
                (errors if bad else rules).append(entry)
            elif parse_level(entry) is None:
                errors.append(entry)
            else:
                global_level = entry
    return global_level, rules, errors
