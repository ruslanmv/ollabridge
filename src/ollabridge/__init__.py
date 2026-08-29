"""OllaBridge package metadata."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ollabridge")
except PackageNotFoundError:  # pragma: no cover - source tree without install metadata
    __version__ = "0.1.6"

__all__ = ["__version__"]
