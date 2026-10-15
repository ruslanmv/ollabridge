"""Reachability of upstream endpoints, logged on *change* rather than on every probe.

The gateway probes Ollama from several places (the catalog sync every minute,
``/v1/models`` on every dashboard poll, chat requests). When Ollama is down,
each of them used to emit its own WARNING on every attempt, so an idle gateway
printed the same line once a minute for hours while saying nothing new.

An :class:`EndpointMonitor` keeps one state per base URL and applies the
usual operational logging policy:

* the first failure is a WARNING that names the address, the error and what
  to do about it;
* further failures are DEBUG, with a WARNING reminder at most every
  ``OLLABRIDGE_UNREACHABLE_REMINDER_S`` seconds (default 600) that states how
  long it has been down and how many attempts were made;
* recovery is an INFO line with the outage duration.

``snapshot()`` exposes the same state to ``/health`` so a dashboard or a
monitoring check can read it without parsing logs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

log = logging.getLogger("ollabridge.reachability")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


DEFAULT_REMINDER_S = _env_float("OLLABRIDGE_UNREACHABLE_REMINDER_S", 600.0)


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def _describe(error: Any) -> str:
    if isinstance(error, BaseException):
        text = str(error).strip()
        return f"{type(error).__name__}: {text}" if text else type(error).__name__
    return str(error)


@dataclass
class EndpointState:
    url: str
    reachable: Optional[bool] = None  # None until the first probe
    since: float = 0.0  # monotonic clock at the last transition
    since_wall: Optional[float] = None  # epoch seconds, for reporting
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_reminder: float = 0.0


class EndpointMonitor:
    """Per-URL up/down state with change-only logging. Thread-safe."""

    def __init__(
        self,
        label: str,
        *,
        hint: str = "",
        reminder_s: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        logger: logging.Logger = log,
    ) -> None:
        self.label = label
        self.hint = hint.strip()
        self.reminder_s = DEFAULT_REMINDER_S if reminder_s is None else reminder_s
        self._clock = clock
        self._wall = wall
        self._log = logger
        self._states: dict[str, EndpointState] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(url: str) -> str:
        return (url or "").rstrip("/")

    def _state(self, url: str) -> EndpointState:
        key = self._key(url)
        state = self._states.get(key)
        if state is None:
            state = EndpointState(url=key)
            self._states[key] = state
        return state

    # ── reporting ────────────────────────────────────────────────────────

    def failure(self, url: str, error: Any) -> None:
        """Record a failed probe; log once per outage plus periodic reminders."""
        with self._lock:
            state = self._state(url)
            now = self._clock()
            described = _describe(error)
            state.consecutive_failures += 1
            state.last_error = described

            if state.reachable is not False:
                state.reachable = False
                state.since = now
                state.since_wall = self._wall()
                state.last_reminder = now
                self._log.warning(
                    "%s not reachable at %s (%s).%s Further failures are logged at DEBUG, "
                    "with a reminder every %s while it stays down.",
                    self.label,
                    state.url,
                    described,
                    f" {self.hint}" if self.hint else "",
                    _fmt_duration(self.reminder_s),
                )
                return

            if now - state.last_reminder >= self.reminder_s:
                state.last_reminder = now
                self._log.warning(
                    "%s still not reachable at %s, down for %s (%d attempts, last error: %s).",
                    self.label,
                    state.url,
                    _fmt_duration(now - state.since),
                    state.consecutive_failures,
                    described,
                )
                return

            self._log.debug("%s still not reachable at %s (%s)", self.label, state.url, described)

    def success(self, url: str) -> None:
        """Record a successful probe; log recovery once."""
        with self._lock:
            state = self._state(url)
            now = self._clock()
            if state.reachable is False:
                self._log.info(
                    "%s reachable again at %s after %s (%d failed attempts).",
                    self.label,
                    state.url,
                    _fmt_duration(now - state.since),
                    state.consecutive_failures,
                )
            elif state.reachable is None:
                self._log.debug("%s reachable at %s", self.label, state.url)
            if state.reachable is not True:
                state.since = now
                state.since_wall = self._wall()
            state.reachable = True
            state.consecutive_failures = 0
            state.last_error = None

    # ── reading ──────────────────────────────────────────────────────────

    def is_reachable(self, url: str) -> Optional[bool]:
        with self._lock:
            state = self._states.get(self._key(url))
            return None if state is None else state.reachable

    def snapshot(self, url: str) -> dict[str, Any]:
        """JSON-friendly state for ``/health`` and diagnostics."""
        with self._lock:
            state = self._states.get(self._key(url))
            if state is None:
                return {
                    "url": self._key(url),
                    "reachable": None,
                    "since": None,
                    "consecutive_failures": 0,
                    "last_error": None,
                }
            since = (
                datetime.fromtimestamp(state.since_wall, tz=timezone.utc).isoformat()
                if state.since_wall is not None
                else None
            )
            return {
                "url": state.url,
                "reachable": state.reachable,
                "since": since,
                "consecutive_failures": state.consecutive_failures,
                "last_error": state.last_error,
            }

    def reset(self) -> None:
        """Forget every endpoint (tests; a settings change that swaps the URL)."""
        with self._lock:
            self._states.clear()


#: The local Ollama runtime. Every Ollama probe in the process reports here,
#: so one outage is one warning no matter how many callers notice it.
OLLAMA = EndpointMonitor(
    "Ollama",
    hint="Start Ollama, or fix the Ollama base URL on the Local Runtimes page.",
)
