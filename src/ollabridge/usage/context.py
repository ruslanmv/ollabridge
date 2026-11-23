"""Carry a provider's untouched usage block from where the response is parsed
to where the request is recorded, without changing any return value.

A ``ContextVar`` is scoped to the task serving the request, so one request's
usage can not leak into another's.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Mapping, Optional

_raw_usage: ContextVar[Optional[Mapping[str, Any]]] = ContextVar("ollabridge_raw_usage", default=None)


def note_raw_usage(raw: Any) -> None:
    """Remember the usage block of the response being handled. Never raises."""
    if isinstance(raw, Mapping) and raw:
        _raw_usage.set(raw)


def take_raw_usage() -> Optional[Mapping[str, Any]]:
    """Return and clear the noted block."""
    raw = _raw_usage.get()
    if raw is not None:
        _raw_usage.set(None)
    return raw


_route: ContextVar[Optional[tuple[str, str]]] = ContextVar("ollabridge_usage_route", default=None)


def note_route(provider_id: str, model: str) -> None:
    """Remember which provider (and upstream model id) answered this request."""
    _route.set((provider_id, model))


def take_route() -> Optional[tuple[str, str]]:
    route = _route.get()
    if route is not None:
        _route.set(None)
    return route
