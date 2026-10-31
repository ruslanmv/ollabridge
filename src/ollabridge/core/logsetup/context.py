"""Fields that ride along on every log line emitted in the current context.

Backed by :mod:`contextvars`, so each asyncio task (each HTTP request) sees its
own fields and a request id bound by middleware appears on every line the
request produces, including a provider failover warning deep in the router,
without anyone passing ids around.

    with log_context(request_id=rid):
        ...  # every record logged here carries request_id

    token = bind(node_id="laptop")   # for the lifetime of a task / process
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from types import MappingProxyType
from typing import Any

_EMPTY: Mapping[str, Any] = MappingProxyType({})
_FIELDS: ContextVar[Mapping[str, Any]] = ContextVar("ollabridge_log_fields", default=_EMPTY)


def current() -> Mapping[str, Any]:
    """The fields bound in the current context (read-only)."""
    return _FIELDS.get()


def bind(**fields: Any) -> Token[Mapping[str, Any]]:
    """Add *fields* to the current context; ``None`` values are skipped.

    Returns a token for :func:`unbind`.
    """
    merged = dict(_FIELDS.get())
    merged.update({k: v for k, v in fields.items() if v is not None})
    return _FIELDS.set(MappingProxyType(merged))


def unbind(token: Token[Mapping[str, Any]]) -> None:
    """Restore the fields that were current before the matching :func:`bind`."""
    try:
        _FIELDS.reset(token)
    except ValueError:
        # The token was created in another context (a task that already
        # finished). Fall back to the value it replaced.
        _FIELDS.set(token.old_value if token.old_value is not Token.MISSING else _EMPTY)


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind *fields* for the duration of the ``with`` block."""
    token = bind(**fields)
    try:
        yield
    finally:
        unbind(token)
