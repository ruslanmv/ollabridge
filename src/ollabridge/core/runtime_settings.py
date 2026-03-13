"""Runtime settings store — persisted to JSON, hot-reloadable from frontend."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge")

_STORE_FILE = settings.DATA_DIR / "runtime_settings.json"

# Defaults mirror the env-based settings but can be overridden at runtime.
_DEFAULTS: dict[str, Any] = {
    "default_model": settings.DEFAULT_MODEL,
    "default_embed_model": settings.DEFAULT_EMBED_MODEL,
    "ollama_base_url": settings.OLLAMA_BASE_URL,
    "local_runtime_enabled": settings.LOCAL_RUNTIME_ENABLED,
    "homepilot_enabled": settings.HOMEPILOT_ENABLED,
    "homepilot_base_url": settings.HOMEPILOT_BASE_URL,
    "homepilot_api_key": settings.HOMEPILOT_API_KEY,
    "homepilot_node_id": settings.HOMEPILOT_NODE_ID,
    "homepilot_node_tags": settings.HOMEPILOT_NODE_TAGS,
}

_cache: dict[str, Any] | None = None


def has_saved_settings() -> bool:
    """Check if the user has previously saved settings from the UI."""
    return _STORE_FILE.exists()


def _load() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    if _STORE_FILE.exists():
        try:
            _cache = json.loads(_STORE_FILE.read_text())
            return _cache
        except Exception:
            pass
    _cache = dict(_DEFAULTS)
    return _cache


def _save(data: dict[str, Any]) -> None:
    global _cache
    _cache = data
    _STORE_FILE.write_text(json.dumps(data, indent=2))


def get_all() -> dict[str, Any]:
    return dict(_load())


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, _DEFAULTS.get(key, default))


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge patch into current settings, persist, return new state."""
    current = _load()
    current.update(patch)
    _save(current)
    return dict(current)
