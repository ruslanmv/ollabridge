"""One log line per HTTP request, at the level the request deserves.

This replaces uvicorn's access log, which only knows method, path and status
and logged every dashboard poll and health check at INFO. The rules:

- **Successful reads are DEBUG.** GET, HEAD and OPTIONS below 400 are health
  checks, model-list refreshes and dashboard polls arriving every few seconds.
- **Writes and inference are INFO.** POST, PUT, PATCH and DELETE are real
  work: a chat completion, an embedding, a settings change. The line carries
  what the handlers noted: model, route, tokens, fallback.
- **Server errors are ERROR, always.**
- **Client errors are WARN once.** The first 4xx a client gets for a path is
  WARN with the reason; repeats are DEBUG, and while they keep coming a WARN
  with the count is logged once per :data:`REPEAT_WINDOW_S`. A misconfigured
  client polling every minute without a key is one line, not sixty an hour.

``--log-level http=debug`` (or ``-v``) shows every request.

It is a pure ASGI middleware, not ``BaseHTTPMiddleware``, so it adds no
buffering and works for streaming responses. It reads the request id from
the ``X-Request-ID`` response header set by the request-id middleware.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from typing import Any, Callable

from ollabridge.core.logsetup import request_facts, uvicorn_logs

log = logging.getLogger("ollabridge.api.requests")

QUIET_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REPEAT_WINDOW_S = 600.0
_MAX_TRACKED = 1024


@dataclass
class _Seen:
    last_loud: float
    last_loud_wall: float
    suppressed: int = 0


class RepeatTracker:
    """Decide whether a repeated client error is logged loudly or counted."""

    def __init__(
        self,
        window_s: float = REPEAT_WINDOW_S,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.window_s = window_s
        self._clock = clock
        self._wall = wall
        self._seen: OrderedDict[tuple, _Seen] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: tuple) -> tuple[bool, int, float | None]:
        """Return ``(loud, suppressed_since_last_loud, last_loud_wall_time)``."""
        with self._lock:
            now = self._clock()
            seen = self._seen.get(key)
            if seen is None or now - seen.last_loud >= self.window_s:
                suppressed = seen.suppressed if seen else 0
                since = seen.last_loud_wall if seen else None
                self._seen[key] = _Seen(last_loud=now, last_loud_wall=self._wall())
                self._seen.move_to_end(key)
                while len(self._seen) > _MAX_TRACKED:
                    self._seen.popitem(last=False)
                return True, suppressed, since
            seen.suppressed += 1
            return False, seen.suppressed, None


def _took(seconds: float) -> str:
    return f"{seconds:.2f}s" if seconds < 10 else f"{seconds:.1f}s"


def _tokens(facts: dict[str, Any]) -> str | None:
    if facts.get("tokens"):
        return str(facts["tokens"])
    t_in, t_out = facts.get("tokens_in"), facts.get("tokens_out")
    if t_in or t_out:
        return f"~{t_in or 0}→{t_out or 0}"
    return None


class RequestLogMiddleware:
    """Pure ASGI middleware emitting the request's access line (see module doc)."""

    def __init__(self, app: Any, tracker: RepeatTracker | None = None) -> None:
        self.app = app
        self.tracker = tracker or RepeatTracker()
        # uvicorn's own access lines would now be duplicates.
        uvicorn_logs.APP_LOGS_REQUESTS = True

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        facts, token = request_facts.begin()
        status: int | None = None
        request_id: str | None = None

        async def send_and_watch(message: dict) -> None:
            nonlocal status, request_id
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 0))
                for name, value in message.get("headers") or ():
                    if name.lower() == b"x-request-id":
                        request_id = value.decode("latin-1")
            await send(message)

        failed = False
        try:
            await self.app(scope, receive, send_and_watch)
        except BaseException:
            failed = True
            raise
        finally:
            request_facts.end(token)
            if status is None and failed:
                status = 500
            try:
                self._emit(scope, status, time.perf_counter() - started, facts, request_id)
            except Exception:  # pragma: no cover - logging must never break serving
                pass

    def _emit(
        self,
        scope: dict,
        status: int | None,
        seconds: float,
        facts: dict[str, Any],
        request_id: str | None,
    ) -> None:
        method = str(scope.get("method") or "?")
        path = str(scope.get("path") or "")
        client = (scope.get("client") or (None, None))[0]

        extra: dict[str, Any] = {
            "request_id": request_id,
            "model": facts.get("model"),
            "requested": facts.get("requested"),
            "route": facts.get("route"),
            "tokens": _tokens(facts),
            "fallback": True if facts.get("fallback") else None,
            "error": facts.get("error"),
            "client": client,
            # JSON-only fields; the console already has them in the message.
            "method": method,
            "path": path,
            "status": status,
            "latency_ms": int(seconds * 1000),
            uvicorn_logs.TEXT_HIDE_ATTR: ("method", "path", "status", "latency_ms"),
        }

        if status is None:
            log.debug("%s %s no response %s", method, path, _took(seconds), extra=extra)
            return

        msg = "%s %s %s %s"
        args: list[Any] = [method, path, status, _took(seconds)]

        if status >= 500:
            level = logging.ERROR
        elif status >= 400:
            reason = facts.get("reason") or _phrase(status)
            # A different reason is a different problem (no key, then a wrong
            # key). Not-found is keyed per client only, so a scanner probing
            # hundreds of paths is one warning, not hundreds.
            key = (client, status) if status == 404 else (client, method, path, status, reason)
            loud, suppressed, since = self.tracker.check(key)
            msg += ": %s"
            args.append(reason)
            if loud:
                level = logging.WARNING
                if suppressed:
                    msg += " (%d more since %s)"
                    args += [suppressed, datetime.fromtimestamp(since or 0).strftime("%H:%M:%S")]
                else:
                    minutes = int(self.tracker.window_s // 60)
                    msg += "; repeats from this client are counted and summarised every %dm"
                    args.append(minutes)
            else:
                level = logging.DEBUG
        elif method in QUIET_METHODS:
            level = logging.DEBUG
        else:
            level = logging.INFO

        log.log(level, msg, *args, extra=extra)


def _phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "client error"
