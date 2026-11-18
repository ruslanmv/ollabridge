"""Record one usage event per served request.

Called from the gateway's ``_record_trace`` — the single function every
request already passes through. Like tracing, it is best-effort: a failure
here is logged at DEBUG and never affects the response.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional

from ollabridge.core.settings import settings

from . import context as usage_context
from .contract import Usage, UsageEvent, clean_label, new_event_id
from .normalize import normalize_usage, reported_cost_micro
from .pricing import PriceCatalog
from .store import get_usage_store

log = logging.getLogger(__name__)

_SEED = Path(__file__).parent / "catalog" / "pricing.seed.yaml"
_LOCAL_PROVIDERS = {None, "", "ollama-local", "local", "ollama"}


def enabled() -> bool:
    return bool(settings.USAGE_ENABLED)


@lru_cache(maxsize=4)
def _load_catalog(path: str) -> PriceCatalog:
    return PriceCatalog.from_file(path)


def get_catalog() -> PriceCatalog:
    """Active price catalog: ``USAGE_PRICING_FILE`` or the bundled seed."""
    path = settings.USAGE_PRICING_FILE or str(_SEED)
    try:
        return _load_catalog(path)
    except Exception as exc:  # noqa: BLE001 — a bad catalog must not stop metering
        log.warning("usage: price catalog %s unusable (%s); costs stay unpriced", path, exc)
        return PriceCatalog()


def price(event: UsageEvent) -> None:
    """Fill ``estimated_micro`` from the catalog when nobody supplied one."""
    if event.cost.estimated_micro is not None or event.billing_mode not in ("api", "subscription"):
        return
    catalog, day = get_catalog(), event.occurred_at.date()
    micro, version = catalog.cost_micro(event.effective_billing_provider, event.model, event.usage, day)
    if micro is None and event.effective_billing_provider != event.provider:
        micro, version = catalog.cost_micro(event.provider, event.model, event.usage, day)
    event.cost.estimated_micro, event.cost.pricing_version = micro, version


def _safe_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "._:-")[:128]
    return cleaned if cleaned and cleaned[0].isalnum() else None


@lru_cache(maxsize=1)
def _device_id() -> Optional[str]:
    try:
        from ollabridge.cloud.device_config import load_cloud_device_credentials

        creds = load_cloud_device_credentials()
        return _safe_id(creds.device_id) if creds else None
    except Exception:  # noqa: BLE001
        return None


def _classify(request: Any, provider: Optional[str], model: Optional[str], reported: Optional[int]):
    """→ (provider, billing_provider, execution, billing_mode)."""
    if provider in _LOCAL_PROVIDERS:
        return "ollama", None, "local_device", "local"
    if provider == "homepilot":
        return "homepilot", None, "local_device", "local"

    registry = getattr(getattr(request, "app", None), "state", None)
    registry = getattr(registry, "provider_registry", None)
    config = registry.get_config(provider) if registry is not None else None
    kind = getattr(config, "kind", "") or ""
    category = str(getattr(getattr(config, "category", None), "value", "") or "")
    if kind == "ollama_bridge" or category == "local":
        return provider, None, "local_device", "local"
    if kind == "openrouter":
        # OpenRouter bills the call; the model's vendor is the id prefix.
        vendor = model.split("/", 1)[0] if model and "/" in model else "openrouter"
        return vendor, "openrouter", "provider_api", "api"
    if category.startswith("free") and not reported:
        return provider, None, "provider_api", "free_tier"
    return provider, None, "provider_api", "api"


def record_from_trace(request: Any, fields: Mapping[str, Any]) -> None:
    """Turn the gateway's trace fields into a usage event. Never raises."""
    raw, route = usage_context.take_raw_usage(), usage_context.take_route()
    if not enabled():
        return
    try:
        ok = bool(fields.get("ok", True))
        headers = request.headers

        if not ok:
            usage, measurement = Usage(), "unavailable"
        elif raw:
            usage = normalize_usage(raw)
            # Ollama's counts come from the runtime; everything else that
            # reaches this branch is the provider's own usage block.
            measurement = "locally_observed" if "eval_count" in raw else "provider_reported"
        elif fields.get("tokens_in") is not None or fields.get("tokens_out") is not None:
            # Text-length approximation from the gateway (see _estimate_tokens).
            usage = Usage(input_tokens=fields.get("tokens_in"), output_tokens=fields.get("tokens_out"))
            measurement = "estimated"
        else:
            usage, measurement = Usage(), "unavailable"

        reported = reported_cost_micro(raw) if ok else None
        model = fields.get("resolved_model") or fields.get("requested_model")
        trace_provider = fields.get("provider")
        if route and (trace_provider == "provider-addon" or (not ok and trace_provider is None)):
            # The trace only says "a provider add-on answered" (or, when it
            # failed, nothing at all); the router noted which provider it was
            # tried on, and the model id it was asked for. Without this a
            # failed add-on request was filed under local Ollama.
            trace_provider, model = route
        provider, billing_provider, execution, billing_mode = _classify(
            request, trace_provider, model, reported
        )
        latency = fields.get("latency_ms")

        event = UsageEvent(
            # A cloud-relayed request carries the cloud's attempt id, so both
            # sides' records of it collapse into one ledger row.
            event_id=_safe_id(headers.get("x-ollabridge-attempt-id")) or new_event_id(),
            trace_id=_safe_id(headers.get("x-ollabridge-trace"))
            or _safe_id(getattr(request.state, "request_id", None)),
            task_id=_safe_id(headers.get("x-ollabridge-task")),
            source="local_gateway",
            device_id=_device_id(),
            application_id=clean_label(headers.get("x-ollabridge-app"))
            or clean_label(headers.get("x-client-type")),
            agent_id=clean_label(headers.get("x-ollabridge-agent")),
            provider=provider,
            billing_provider=billing_provider,
            model=model,
            requested_model=fields.get("requested_model"),
            execution=execution,
            billing_mode=billing_mode,
            usage=usage,
            measurement=measurement,
            status="completed" if ok else "failed",
            error_category=clean_label(fields.get("error_category")),
            latency_ms=int(latency) if isinstance(latency, (int, float)) and latency >= 0 else None,
        )
        event.cost.provider_reported_micro = reported
        price(event)
        get_usage_store().record(event)
    except Exception:  # pragma: no cover - metering must never break serving
        log.debug("usage capture failed", exc_info=True)
