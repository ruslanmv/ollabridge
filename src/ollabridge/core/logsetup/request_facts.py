"""Facts about the HTTP request in flight, for its one access line.

The request-log middleware (``ollabridge.api.request_log``) opens an empty
dict for each request. Code that learns something worth showing on that
line adds to it with :func:`note`: the auth check records why a key was
refused, the provider router records which provider answered and how many
tokens it used, the chat handler records the model.

The dict lives in a :class:`~contextvars.ContextVar`. Child tasks and worker
threads get a copy of the context that points at the same dict, so a note
made in a sync dependency running in the thread pool still reaches the
middleware. Outside a request, :func:`note` does nothing.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_FACTS: ContextVar[dict[str, Any] | None] = ContextVar("ollabridge_request_facts", default=None)


def begin() -> tuple[dict[str, Any], Token[dict[str, Any] | None]]:
    """Open a fresh facts dict for the current request."""
    facts: dict[str, Any] = {}
    return facts, _FACTS.set(facts)


def end(token: Token[dict[str, Any] | None]) -> None:
    try:
        _FACTS.reset(token)
    except ValueError:  # reset from another context; the request is over anyway
        _FACTS.set(None)


def note(**facts: Any) -> None:
    """Record facts for the current request's log line; ``None`` values are skipped."""
    current = _FACTS.get()
    if current is not None:
        current.update({k: v for k, v in facts.items() if v is not None})


def current() -> dict[str, Any] | None:
    return _FACTS.get()
