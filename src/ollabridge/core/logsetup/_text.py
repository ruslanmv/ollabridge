"""Small text helpers shared by the formatters and the uvicorn bridge."""

from __future__ import annotations

import json
from typing import Any

_MAX_VALUE = 200


def format_duration(seconds: float) -> str:
    """``0.9s``, ``12.3s``, ``4m05s``, ``1h35m``."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def short_request_id(value: Any) -> str:
    """``req_a1b2c3d4e5…`` becomes ``a1b2c3d4``; a client-supplied id keeps 12 chars.

    ``ollabridge traces show`` accepts the prefix, so the short form is enough
    to find the full trace.
    """
    text = str(value)
    if text.startswith("req_"):
        return text[4:12]
    return text[:12]


def format_value(value: Any) -> str:
    """Render one ``key=value`` value for the console: compact and unambiguous."""
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        text = f"{value:g}"
    elif isinstance(value, (list, tuple, set, frozenset)):
        text = ",".join(str(v) for v in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > _MAX_VALUE:
        text = text[: _MAX_VALUE - 1] + "…"
    if text == "" or any(ch in text for ch in ' "=\t\n'):
        text = json.dumps(text, ensure_ascii=False)
    return text
