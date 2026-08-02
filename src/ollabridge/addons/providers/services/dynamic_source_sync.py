"""Bridge saved External Sources into the live provider registry.

BYOK sources (``providers.yaml`` + ``SecretStore``) and the runtime provider
registry are two subsystems. A *dynamic* source — one whose model list is
discovered from the upstream at runtime, e.g. an Open WebUI-compatible server —
must be built into an adapter and registered, or the gateway could show
"Connected" in the UI while ``/v1/chat/completions`` and ``/v1/models`` cannot
serve it.

Everything here is additive and best-effort: with no registry (addon disabled)
the functions no-op, and they never raise into a request or startup path.
"""
from __future__ import annotations

import logging
from typing import Any

from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.providers_meta import ProviderRecord, get_record, load_providers

log = logging.getLogger(__name__)

# Source kinds whose model list is discovered from the upstream at runtime.
DYNAMIC_KINDS = {"open_webui"}

# The namespaced routing heuristic resolves ``<prefix>/<model>`` to the provider
# whose id/prefix matches, so the config id shares this prefix.
_DEFAULT_PREFIX = "openwebui"


def is_dynamic(kind: str | None) -> bool:
    return (kind or "").lower() in DYNAMIC_KINDS


def _provider_id() -> str:
    return _DEFAULT_PREFIX


def build_adapter(rec: ProviderRecord, secret: str | None) -> OpenWebUIAdapter | None:
    """Construct the live adapter for a dynamic source, or None when the source
    is not dynamic or lacks the required base URL."""
    if not is_dynamic(rec.kind) or not rec.base_url:
        return None
    return OpenWebUIAdapter(
        base_url=rec.base_url,
        api_key=secret or None,
        model_prefix=_DEFAULT_PREFIX,
    )


def _addon_config(rec: ProviderRecord) -> ProviderConfig:
    return ProviderConfig(
        id=_provider_id(),
        name=rec.display_name or rec.name,
        kind="open_webui",
        enabled=rec.enabled,
        base_url=rec.base_url,
        model_prefix=_DEFAULT_PREFIX,
        dynamic_models=True,
    )


def _registry(app: Any) -> Any:
    return getattr(getattr(app, "state", None), "provider_registry", None)


async def sync_source(app: Any, name: str, secret: str | None) -> bool:
    """Register (or replace) a saved dynamic source in the live registry. Returns
    True when registered, False when skipped. Disabling a source unregisters it.
    Never raises."""
    try:
        rec = get_record(name)
        if rec is None or not is_dynamic(rec.kind):
            return False
        registry = _registry(app)
        if registry is None:
            return False
        if not rec.enabled:
            await registry.unregister(_provider_id())
            return False
        adapter = build_adapter(rec, secret)
        if adapter is None:
            return False
        await registry.register(_addon_config(rec), adapter)
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort; never break the request
        log.warning("sync_source(%s) failed: %s", name, exc)
        return False


async def unsync_source(app: Any, name: str) -> None:
    """Drop a deleted/disabled dynamic source from the live registry."""
    try:
        if not is_dynamic(name):  # source name == catalog kind
            return
        registry = _registry(app)
        if registry is None:
            return
        await registry.unregister(_provider_id())
    except Exception as exc:  # noqa: BLE001
        log.warning("unsync_source(%s) failed: %s", name, exc)


async def sync_all(app: Any) -> int:
    """Register every enabled dynamic source at startup. Returns the count
    synced. Best-effort; never raises."""
    synced = 0
    try:
        from ollabridge.provider_ops import get_secret
    except Exception:  # noqa: BLE001
        return 0
    try:
        for rec in load_providers():
            if not is_dynamic(rec.kind) or not rec.enabled:
                continue
            if await sync_source(app, rec.name, get_secret(rec.name)):
                synced += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("sync_all failed: %s", exc)
    return synced


def discovery_summary(models: list[dict]) -> dict[str, Any]:
    """Aggregate a normalized model list into the counts the UI shows (Local /
    External / persona-compatible / dynamic tags)."""
    conn: dict[str, int] = {}
    tags: dict[str, int] = {}
    persona = 0
    for m in models:
        ct = m.get("connection_type")
        if ct:
            conn[str(ct)] = conn.get(str(ct), 0) + 1
        if m.get("persona_compatible") is True:
            persona += 1
        for t in m.get("tags") or []:
            n = t.get("name") if isinstance(t, dict) else None
            if n:
                tags[str(n)] = tags.get(str(n), 0) + 1
    return {
        "count": len(models),
        "connection_types": conn,
        "persona_compatible": persona,
        "tags": tags,
    }
