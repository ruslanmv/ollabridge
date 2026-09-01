"""Compatibility helpers for supported ``websockets`` client versions."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

try:
    from websockets.asyncio.client import connect as websocket_connect
except ImportError:  # websockets 12 uses the legacy client namespace.
    from websockets.client import connect as websocket_connect  # type: ignore[assignment]  # noqa: F401


def connection_options(
    connect: Callable[..., Any],
    *,
    headers: Mapping[str, str] | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Return connection options matching the installed websockets API.

    websockets 13 renamed ``extra_headers`` to ``additional_headers``, while
    newer releases also added options such as ``proxy``.  Passing an option
    from the new API to the legacy client is forwarded to asyncio and fails
    with a misleading ``create_connection()`` TypeError.
    """
    parameters = inspect.signature(connect).parameters
    accepts_arbitrary_options = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )

    compatible = {
        name: value
        for name, value in options.items()
        if accepts_arbitrary_options or name in parameters
    }
    if headers:
        header_option = (
            "additional_headers" if "additional_headers" in parameters else "extra_headers"
        )
        compatible[header_option] = dict(headers)
    return compatible
