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
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.addons.providers.model_defaults import suggested_models
from ollabridge.core.redact import redact_secret
from ollabridge.core.security import require_api_key
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    STORAGE_MODES,
    ProviderRecord,
    apply_extras,
    extra_fields_for,
    get_record,
    get_extra,
    load_providers,
    missing_extras,
    remove_record,
    upsert_record,
)

log = logging.getLogger("ollabridge.sources")

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
    extra: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Provider-specific non-secret config declared by the catalog, "
            "e.g. {'project_id': '...'} for watsonx. An empty value clears "
            "a field; undeclared keys are ignored."
        ),
    )


def _field_view(rec: ProviderRecord, spec) -> dict[str, Any]:
    """One extra field with its resolved value, for the UI to render."""
    return {
        **spec.model_dump(),
        "value": get_extra(rec, spec.name) or "",
    }


def _supports_discovery(kind: str) -> bool:
    """Can the settings UI fetch this source's model list from the upstream?"""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    return dss.is_discoverable(kind)


def _source_view(rec: ProviderRecord, key: str | None) -> dict[str, Any]:
    """Public view of a source: metadata + redacted key hint, never the key."""
    spec = PROVIDER_CATALOG.get(rec.kind or rec.name)
    missing = missing_extras(rec)
    if key:
        status = "connected" if rec.last_test_ok is not False else "error"
    else:
        status = "missing_key"
    # A key alone is not enough when the provider declares required extra
    # config — say so rather than reporting the source as connected.
    if key and missing:
        status = "missing_config"
    if not rec.enabled:
        status = "disabled"
    return {
        **rec.model_dump(),
        "label": spec.label if spec else rec.name,
        "key": redact_secret(key) if key else None,
        "key_configured": bool(key),
        "extra_fields": [
            _field_view(rec, f) for f in extra_fields_for(rec.kind or rec.name)
        ],
        "missing_config": missing,
        "supports_discovery": _supports_discovery(rec.kind or rec.name),
        # Models worth suggesting before a key has been saved to discover
        # with. Empty for a provider whose catalog is per-account (watsonx):
        # there is nothing honest to suggest until we have asked it.
        "suggested_models": suggested_models(rec.kind or rec.name),
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
            # So the add form can prompt for what this provider needs
            # beyond an API key (watsonx: a project id).
            "extra_fields": [f.model_dump() for f in spec.extra_fields],
            "supports_discovery": _supports_discovery(spec.name),
            "suggested_models": suggested_models(spec.name),
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

    if body.extra is not None:
        apply_extras(rec, body.extra)

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

    # Push the saved key onto the live adapters, and — when there is something
    # to learn — summarize what it can reach. Discovery is a round-trip to the
    # provider, so it runs when the credential just changed or the source still
    # needs a default model, not on every toggle of a checkbox.
    needs_discovery = body.api_key is not None or not rec.default_model
    discovery, models = await _sync_and_discover(
        request, name, discover=needs_discovery
    )

    # Free by default: a source the user did not give a model gets the first
    # free one its own catalog still offers. Never overrides an explicit
    # choice, and never invents a model the provider does not serve.
    rec = _apply_default_model(rec, body, models)

    # Choosing a model, switching routing on, or disabling the source changes
    # what this device publishes to OllaBridge Cloud. Re-publish now so a
    # paired device sees the change in seconds rather than at the next
    # five-minute refresh. A default filled in by discovery counts too — it is
    # the model the source will actually serve, and it arrives with the key.
    if any(
        v is not None
        for v in (body.default_model, body.allow_routing, body.enabled, body.api_key)
    ):
        await _republish_to_cloud(request)

    return {
        "source": _source_view(rec, _get_secret(name)),
        "test": test,
        "discovery": discovery,
    }


async def _republish_to_cloud(request: Request) -> None:
    """Ask the cloud bridge to re-send its approved manifest. Best-effort."""
    bridge = getattr(request.app.state, "cloud_bridge", None)
    if bridge is None or not hasattr(bridge, "refresh_models_now"):
        return
    try:
        await bridge.refresh_models_now()
    except Exception as exc:  # noqa: BLE001 - never fail a save over this
        log.warning("cloud manifest refresh after a source change failed: %s", exc)


def _apply_default_model(
    rec: ProviderRecord, body: SourceUpsert, models: list[dict[str, Any]] | None
) -> ProviderRecord:
    """Fill in a free default model when the source has none. Returns the record."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    if rec.default_model or (body.default_model is not None and body.default_model.strip()):
        return rec
    chosen = dss.default_model_for(rec, models)
    if not chosen:
        return rec
    rec.default_model = chosen
    upsert_record(rec)
    return get_record(rec.name) or rec


async def _sync_and_discover(
    request: Request, name: str, *, discover: bool = True
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Reconcile a saved source with the live registry, then return
    ``(summary, models)`` for what its key can reach — ``(None, None)`` when the
    source cannot or need not be discovered. Best-effort: never raises, so a
    discovery hiccup cannot fail the save."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec = get_record(name)
    if rec is None:
        return None, None
    secret = _get_secret(name)
    await dss.sync_source(request.app, name, secret)
    if not discover or not dss.is_discoverable(rec.kind) or not secret:
        return None, None
    adapter = dss.build_adapter(rec, secret)
    if adapter is None:
        return None, None
    try:
        models = dss.normalize_models(rec, await adapter.list_models())
    except Exception:  # noqa: BLE001 - a discovery failure is not a save failure
        return None, None
    return dss.discovery_summary(models), models


async def _discover_models(name: str) -> tuple[ProviderRecord, list[dict[str, Any]]]:
    """Build the source's adapter and return (record, normalized models).
    Raises HTTPException for the caller to surface a clean status."""
    from ollabridge.addons.providers.errors import (
        ProviderAuthError,
        ProviderError,
        ProviderQuotaExceeded,
    )
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec = get_record(name)
    if rec is None:
        raise HTTPException(404, f"source {name!r} is not configured")
    if not dss.is_discoverable(rec.kind):
        raise HTTPException(400, f"source {name!r} does not support model discovery")
    secret = _get_secret(name)
    if not secret:
        raise HTTPException(422, "no API key configured for this source")
    adapter = dss.build_adapter(rec, secret)
    if adapter is None:
        raise HTTPException(422, "base_url is required for this source")
    try:
        return rec, dss.normalize_models(rec, await adapter.list_models())
    except ProviderAuthError:
        raise HTTPException(401, "the server rejected this API key")
    except ProviderQuotaExceeded:
        raise HTTPException(429, "the provider is rate limiting or out of quota")
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
    free: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """List the models this source exposes, with the same All / Local /
    External / tag / persona-compatible / free filters the UI shows. Data is
    live from the upstream (what this API key can actually reach), never a
    guessed catalog."""
    from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec, models = await _discover_models(name)
    pc = _as_bool(persona_compatible)
    filtered = OpenWebUIAdapter.filter_models(
        models, connection_type=connection_type, tag=tag, category=category, persona_compatible=pc,
    )
    free_only = _as_bool(free)
    if free_only is not None:
        filtered = [m for m in filtered if bool(m.get("free")) is free_only]
    if search:
        q = search.lower()
        filtered = [
            m for m in filtered
            if q in str(m.get("id", "")).lower() or q in str(m.get("name", "")).lower()
        ]
    return {
        "models": filtered,
        "summary": dss.discovery_summary(models),
        # What the UI should preselect when the source has no default yet.
        "recommended_default": rec.default_model or dss.default_model_for(rec, models),
    }


def _as_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


@router.post("/{name}/models/refresh")
async def refresh_source_models(
    name: str, _key: str = Depends(require_api_key)
) -> dict[str, Any]:
    """Re-discover a source's models from the upstream."""
    from ollabridge.addons.providers.services import dynamic_source_sync as dss

    rec, models = await _discover_models(name)
    return {
        "models": models,
        "summary": dss.discovery_summary(models),
        "recommended_default": rec.default_model or dss.default_model_for(rec, models),
    }


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
    # Its models must stop being offered on paired devices too, not just here.
    await _republish_to_cloud(request)
    return {
        "ok": True,
        "removed_metadata": removed_meta,
        "removed_key": removed_key,
        "removed_access_records": removed_access,
    }
