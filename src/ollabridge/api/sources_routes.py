"""``/admin/sources/*`` — generic External Sources management API.

This is the HTTP surface behind the dashboard's Sources tab (see
docs/UX_EXTERNAL_SOURCES.md). It manages *any* supported provider —
OpenAI, Anthropic, Gemini, Hugging Face, OpenRouter, Groq, DeepSeek,
Mistral, Together, Fireworks, Azure OpenAI, Bedrock, custom
OpenAI-compatible endpoints — with one uniform add/test/rotate/remove
pattern, replacing the Hugging-Face-only connect flow as the way to
configure accounts.

Security invariants:
* API keys go straight into the encrypted SecretStore; they are never
  written to providers.yaml, never logged, and never returned by any
  endpoint — responses carry only a redacted hint (``sk-…(redacted)``).
* Safe defaults: new sources are local-only, private, routing-disabled.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.core.redact import redact_secret
from ollabridge.core.security import require_api_key
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    STORAGE_MODES,
    ProviderRecord,
    get_record,
    load_providers,
    remove_record,
    upsert_record,
)

router = APIRouter(prefix="/admin/sources", tags=["sources"])


# ── Schemas ──────────────────────────────────────────────────────────


class SourceUpsert(BaseModel):
    """Add or update a source. Omitted fields keep their current values."""

    api_key: Optional[str] = Field(
        default=None,
        description="Provider API key (stored encrypted; never echoed back)",
    )
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    enabled: Optional[bool] = None
    allow_routing: Optional[bool] = None
    sharing: Optional[str] = None  # private | account | workspace | organization
    storage_mode: Optional[str] = (
        None  # local_only | cloud_encrypted_vault | organization_vault
    )


def _source_view(rec: ProviderRecord, key: str | None) -> dict[str, Any]:
    """Public view of a source: metadata + redacted key hint, never the key."""
    spec = PROVIDER_CATALOG.get(rec.kind or rec.name)
    if key:
        status = "connected" if rec.last_test_ok is not False else "error"
    else:
        status = "missing_key"
    if not rec.enabled:
        status = "disabled"
    return {
        **rec.model_dump(),
        "label": spec.label if spec else rec.name,
        "key": redact_secret(key) if key else None,
        "key_configured": bool(key),
        "status": status,
    }


def _get_secret(name: str) -> str | None:
    from ollabridge.provider_ops import get_secret

    return get_secret(name)


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("")
async def list_sources(_key: str = Depends(require_api_key)) -> dict[str, Any]:
    """All sources: configured ones first, then the available catalog."""
    records = {r.name: r for r in load_providers()}
    configured = [_source_view(rec, _get_secret(rec.name)) for rec in records.values()]
    available = [
        {
            "name": spec.name,
            "label": spec.label,
            "base_url": spec.base_url,
            "env_var": spec.env_var,
            "notes": spec.notes,
            "status": "not_configured",
        }
        for spec in PROVIDER_CATALOG.values()
        if spec.name not in records
    ]
    return {"configured": configured, "available": available}


@router.get("/{name}")
async def get_source(name: str, _key: str = Depends(require_api_key)) -> dict[str, Any]:
    rec = get_record(name)
    if rec is None:
        raise HTTPException(404, f"source {name!r} is not configured")
    return _source_view(rec, _get_secret(name))


@router.post("/{name}")
async def upsert_source(
    name: str, body: SourceUpsert, request: Request, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Add or update a source. Saves the key encrypted, then tests it. For a
    dynamic source (one that discovers its models at runtime) it also registers
    the live adapter and returns a discovery summary, so the gateway can serve
    the models — the UI never shows "Connected" for something it cannot route."""
    from ollabridge.provider_ops import set_secret, test_provider

    name = name.lower().strip()
    rec = get_record(name)
    if rec is None:
        if name not in PROVIDER_CATALOG:
            raise HTTPException(
                404,
                f"unknown source {name!r}; supported: {', '.join(sorted(PROVIDER_CATALOG))}",
            )
        spec = PROVIDER_CATALOG[name]
        rec = ProviderRecord(name=name, kind=name, base_url=spec.base_url)

    if body.storage_mode is not None:
        if body.storage_mode not in STORAGE_MODES:
            raise HTTPException(422, f"storage_mode must be one of {STORAGE_MODES}")
        rec.storage_mode = body.storage_mode  # type: ignore[assignment]
    if body.sharing is not None:
        if body.sharing not in ("private", "account", "workspace", "organization"):
            raise HTTPException(
                422, "sharing must be private|account|workspace|organization"
            )
        rec.sharing = body.sharing  # type: ignore[assignment]
    if body.display_name is not None:
        rec.display_name = body.display_name.strip()
    if body.base_url is not None:
        rec.base_url = body.base_url.strip()
    if body.default_model is not None:
        rec.default_model = body.default_model.strip()
    if body.enabled is not None:
        rec.enabled = body.enabled
    if body.allow_routing is not None:
        rec.allow_routing = body.allow_routing

    if name in ("azure-openai", "custom", "open_webui") and not rec.base_url:
        raise HTTPException(422, "base_url is required for this source")

    if body.api_key is not None:
        key = body.api_key.strip()
        if not key:
            raise HTTPException(422, "api_key must not be empty")
        set_secret(name, key)

    upsert_record(rec)

    # Test only when a key exists; report the outcome, never the key.
    test: dict[str, Any] | None = None
    if _get_secret(name):
        ok, detail = test_provider(name)
        rec = get_record(name) or rec  # test_provider stamps last_test_*
        test = {"ok": ok, "detail": detail}

    # Dynamic sources: register the live adapter + summarize what was discovered.
    discovery = await _sync_and_discover(request, name)

    return {"source": _source_view(rec, _get_secret(name)), "test": test, "discovery": discovery}


async def _sync_and_discover(request: Request, name: str) -> dict[str, Any] | None:
    """Register a dynamic source in the live registry and return a summary of the
    models its API key can access. None for non-dynamic sources. Best-effort:
    never raises, so a discovery hiccup cannot fail the save."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec = get_record(name)
    if rec is None or not dss.is_dynamic(rec.kind):
        return None
    secret = _get_secret(name)
    await dss.sync_source(request.app, name, secret)
    adapter = dss.build_adapter(rec, secret)
    if adapter is None:
        return None
    try:
        models = await adapter.list_models()
    except Exception:  # noqa: BLE001 - a discovery failure is not a save failure
        return None
    return dss.discovery_summary(models)


async def _discover_models(name: str) -> tuple[ProviderRecord, list[dict[str, Any]]]:
    """Build the dynamic source's adapter and return (record, normalized models).
    Raises HTTPException for the caller to surface a clean status."""
    from ollabridge.addons.providers.errors import (
        ProviderAuthError,
        ProviderError,
    )
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec = get_record(name)
    if rec is None:
        raise HTTPException(404, f"source {name!r} is not configured")
    if not dss.is_dynamic(rec.kind):
        raise HTTPException(400, f"source {name!r} does not support model discovery")
    adapter = dss.build_adapter(rec, _get_secret(name))
    if adapter is None:
        raise HTTPException(422, "base_url is required for this source")
    try:
        return rec, await adapter.list_models()
    except ProviderAuthError:
        raise HTTPException(401, "the server rejected this API key")
    except ProviderError as exc:
        raise HTTPException(502, f"model discovery failed: {type(exc).__name__}")


@router.get("/{name}/models")
async def source_models(
    name: str,
    _key: str = Depends(require_api_key),
    connection_type: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    persona_compatible: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """List the models a dynamic source exposes, with the same All / Local /
    External / tag / persona-compatible filters the UI shows. Data is live from
    the upstream (filtered by the API key's user), never a guessed catalog."""
    from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    _rec, models = await _discover_models(name)
    pc = None if persona_compatible is None else persona_compatible.lower() in ("1", "true", "yes")
    filtered = OpenWebUIAdapter.filter_models(
        models, connection_type=connection_type, tag=tag, category=category, persona_compatible=pc,
    )
    if search:
        q = search.lower()
        filtered = [
            m for m in filtered
            if q in str(m.get("id", "")).lower() or q in str(m.get("name", "")).lower()
        ]
    return {"models": filtered, "summary": dss.discovery_summary(models)}


@router.post("/{name}/models/refresh")
async def refresh_source_models(
    name: str, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Re-discover a dynamic source's models from the upstream."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    _rec, models = await _discover_models(name)
    return {"models": models, "summary": dss.discovery_summary(models)}


@router.post("/{name}/test")
async def test_source(
    name: str, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Probe the source's models endpoint — validates the key, costs no tokens."""
    from ollabridge.provider_ops import test_provider

    if get_record(name) is None and name not in PROVIDER_CATALOG:
        raise HTTPException(404, f"unknown source {name!r}")
    ok, detail = test_provider(name)
    return {
        "ok": ok,
        "detail": detail,
        "tested_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@router.post("/{name}/rotate")
async def rotate_source(
    name: str, body: SourceUpsert, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Replace the stored key and stamp the rotation time."""
    from ollabridge.provider_ops import rotate_secret, test_provider

    if get_record(name) is None:
        raise HTTPException(404, f"source {name!r} is not configured")
    if not body.api_key or not body.api_key.strip():
        raise HTTPException(422, "api_key is required to rotate")
    rec = rotate_secret(name, body.api_key.strip())
    ok, detail = test_provider(name)
    return {
        "source": _source_view(get_record(name) or rec, _get_secret(name)),
        "test": {"ok": ok, "detail": detail},
    }


@router.delete("/{name}")
async def delete_source(
    name: str, request: Request, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Remove a source, delete its stored key, and drop its access records."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss
    from ollabridge.model_access import remove_source as drop_access
    from ollabridge.provider_ops import delete_secret

    # Drop it from the live registry first so its models stop being served.
    await dss.unsync_source(request.app, name)

    removed_meta = remove_record(name)
    removed_key = delete_secret(name)
    removed_access = drop_access(name)
    if not (removed_meta or removed_key):
        raise HTTPException(404, f"source {name!r} is not configured")
    return {
        "ok": True,
        "removed_metadata": removed_meta,
        "removed_key": removed_key,
        "removed_access_records": removed_access,
    }
