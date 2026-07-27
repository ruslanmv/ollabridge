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

# Canonical auth modes, ordered from most restrictive to most permissive. Each
# is a cumulative superset of the previous (see core.security.require_api_key):
#   required    – API keys only
#   local-trust – API keys + loopback bypass
#   pairing     – API keys + loopback bypass + paired-device tokens
_AUTH_MODES = ("required", "local-trust", "pairing")

# Auth mode is deliberately NOT part of _DEFAULTS: the launcher (CLI) sets the
# live ``settings.AUTH_MODE`` at runtime, so baking it into the persisted store
# would freeze it to the import-time value and shadow the launcher's choice
# (this broke local-trust: every admin call 401'd). The UI override lives under
# a dedicated key that ONLY set_auth_mode() writes, so an unrelated settings
# save can never touch it, and effective_auth_mode() falls back to the live
# setting whenever no explicit override is present.
_AUTH_OVERRIDE_KEY = "auth_mode_override"

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


def effective_auth_mode() -> str:
    """The active auth mode: an explicit UI override if the user set one, else
    the LIVE ``settings.AUTH_MODE`` (what the launcher/env selected).

    Always one of ``required`` | ``local-trust`` | ``pairing``; an unknown value
    falls back to ``required`` so a bad write can never disable authentication
    silently. Reads only the dedicated override key, so a legacy store that
    happens to contain a stray ``auth_mode`` field is ignored.
    """
    override = _load().get(_AUTH_OVERRIDE_KEY)
    raw = override if override else (settings.AUTH_MODE or "required")
    mode = str(raw).lower().strip()
    return mode if mode in _AUTH_MODES else "required"


def set_auth_mode(mode: str) -> str:
    """Persist an explicit UI auth-mode override. Returns the normalized mode.

    Raises ``ValueError`` for an unknown mode so callers can 422. Passing an
    empty string clears the override, restoring the live ``settings.AUTH_MODE``.
    """
    m = (mode or "").lower().strip()
    if m == "":
        current = _load()
        if _AUTH_OVERRIDE_KEY in current:
            current.pop(_AUTH_OVERRIDE_KEY, None)
            _save(current)
        return effective_auth_mode()
    if m not in _AUTH_MODES:
        raise ValueError(f"invalid auth mode: {mode!r}")
    update({_AUTH_OVERRIDE_KEY: m})
    return m
