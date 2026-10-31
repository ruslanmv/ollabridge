"""Handler filters: context injection, per-component levels, log-once.

They run on the gateway's handler, not on individual loggers, so they apply
to every record that reaches it: OllaBridge's own, uvicorn's and third-party
libraries'. Redaction is done by the formatters on the final rendered text
(see ``formatters.py``), which also covers arguments that are not strings,
such as exception objects.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from ollabridge.core.logsetup import context
from ollabridge.core.logsetup.components import COMPONENTS, component_for

#: Pass ``extra={ONCE_KEY: "some-key"}`` to log a record only the first time
#: that key is seen in this process (configuration warnings, deprecations).
ONCE_KEY = "log_once"

#: Records carrying this attribute bypass level thresholds (session header).
ALWAYS_KEY = "_ob_always"

#: Internal attributes the filters attach to records.
COMPONENT_ATTR = "_ob_component"
CONTEXT_KEYS_ATTR = "_ob_ctx"


def record_component(record: logging.LogRecord) -> str:
    comp = getattr(record, COMPONENT_ATTR, None)
    if not comp:
        comp = component_for(record.name)
        setattr(record, COMPONENT_ATTR, comp)
    return comp


class ContextFilter(logging.Filter):
    """Copy the current :mod:`context` fields and the component onto the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record_component(record)
        if not hasattr(record, CONTEXT_KEYS_ATTR):
            added: list[str] = []
            for key, value in context.current().items():
                if key not in record.__dict__:
                    setattr(record, key, value)
                    added.append(key)
            setattr(record, CONTEXT_KEYS_ATTR, tuple(added))
        return True


class LevelFilter(logging.Filter):
    """Global threshold plus per-component and per-logger overrides.

    A rule key that is a known component (``catalog``) applies to that
    component; any other key is a logger-name prefix (``sqlalchemy.engine``).
    A logger rule beats a component rule, which beats the global level.
    """

    def __init__(self, level: int, rules: Iterable[tuple[str, int]] = ()) -> None:
        super().__init__()
        self.level = level
        self.component_rules: dict[str, int] = {}
        logger_rules: list[tuple[str, int]] = []
        for key, lvl in rules:
            if key in COMPONENTS:
                self.component_rules[key] = lvl
            else:
                logger_rules.append((key, lvl))
        self.logger_rules = sorted(logger_rules, key=lambda kv: len(kv[0]), reverse=True)
        self._cache: dict[tuple[str, str], int] = {}

    def threshold(self, name: str, component: str) -> int:
        key = (name, component)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = self.level
        for prefix, lvl in self.logger_rules:
            if name == prefix or name.startswith(prefix + "."):
                result = lvl
                break
        else:
            result = self.component_rules.get(component, self.level)
        if len(self._cache) < 4096:
            self._cache[key] = result
        return result

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, ALWAYS_KEY, False):
            return True
        return record.levelno >= self.threshold(record.name, record_component(record))


class OnceFilter(logging.Filter):
    """Drop a record whose ``log_once`` key has already been logged."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        key = getattr(record, ONCE_KEY, None)
        if key is None:
            return True
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(str(key))
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()
