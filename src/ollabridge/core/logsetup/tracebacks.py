"""Exception rendering for the console.

Pretty mode uses Rich's traceback: syntax-highlighted source, framework frames
(Starlette, FastAPI, AnyIO, uvicorn) collapsed, at most eight frames, never
local variables. Exception messages are redacted before rendering because an
upstream error body can echo a credential back.

Plain and JSON modes use the standard library's text traceback, redacted.
"""

from __future__ import annotations

import importlib
import io
import os
import traceback as _tb
from types import ModuleType
from typing import Any

from ollabridge.core.redact import redact_text

_FRAMEWORKS = ("starlette", "fastapi", "anyio", "uvicorn", "httpx", "httpcore")
_suppress_cache: list[ModuleType] | None = None


def _suppressed_modules() -> list[ModuleType]:
    global _suppress_cache
    if _suppress_cache is None:
        mods: list[ModuleType] = []
        for name in _FRAMEWORKS:
            try:
                mods.append(importlib.import_module(name))
            except Exception:
                continue
        _suppress_cache = mods
    return _suppress_cache


def format_plain(exc_info: Any) -> str:
    """Standard library traceback text, credential shapes scrubbed."""
    return redact_text("".join(_tb.format_exception(*exc_info)).rstrip("\n"))


def _redact_trace(trace: Any) -> None:
    for stack in getattr(trace, "stacks", ()):
        stack.exc_value = redact_text(stack.exc_value)
        stack.notes = [redact_text(n) for n in getattr(stack, "notes", [])]
        for nested in getattr(stack, "exceptions", ()):
            _redact_trace(nested)


def format_rich(exc_info: Any, *, color: bool, width: int) -> str:
    """Rich traceback rendered to a string; falls back to :func:`format_plain`."""
    try:
        from rich.console import Console
        from rich.traceback import Traceback

        exc_type, exc_value, tb = exc_info
        trace = Traceback.extract(exc_type, exc_value, tb, show_locals=False)
        _redact_trace(trace)
        renderable = Traceback(
            trace,
            width=width,
            word_wrap=True,
            show_locals=False,
            suppress=_suppressed_modules(),
            max_frames=8,
        )
        truecolor = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        buf = io.StringIO()
        console = Console(
            file=buf,
            width=width,
            force_terminal=color,
            no_color=not color,
            color_system=("truecolor" if truecolor else "256") if color else None,
            highlight=False,
            legacy_windows=False,
        )
        console.print(renderable)
        return buf.getvalue().rstrip("\n")
    except Exception:
        return format_plain(exc_info)
