"""Bridge saved External Sources into the live provider registry.

BYOK sources (``providers.yaml`` + ``SecretStore``) and the runtime provider
registry are two subsystems. A *dynamic* source — one whose model list is
discovered from the upstream at runtime, e.g. an Open WebUI-compatible server —
must be built into an adapter and registered, or the gateway could show
"Connected" in the UI while ``/v1/chat/completions`` and ``/v1/models`` cannot
serve it.

Separately, every OpenAI-compatible source (Groq, OpenRouter, DeepSeek, …) is
*discoverable*: its catalog is one ``GET {base}/models`` away, so the Sources
UI can list what the saved key can actually reach instead of asking the user
to type a model id from memory. Discovery does not require registering a new
provider — those kinds are already seeded — so the two capabilities are kept
apart: :func:`is_dynamic` gates registry registration, :func:`is_discoverable`
gates model listing.

Everything here is additive and best-effort: with no registry (addon disabled)
the functions no-op, and they never raise into a request or startup path.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ollabridge.addons.providers import free_tier
from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.models import ProviderConfig
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    ProviderRecord,
    get_record,
    load_providers,
)

log = logging.getLogger(__name__)

# Source kinds that are registered into the live registry from providers.yaml,
# because nothing in the seed catalog covers them.
DYNAMIC_KINDS = {"open_webui"}

# Kinds that speak an OpenAI-style ``/models`` listing but are NOT registered
# from providers.yaml — the seed catalog already carries them. They are still
# discoverable, which is what the Sources settings picker needs.
_NON_OPENAI_KINDS = {"anthropic", "watsonx", "bedrock", "azure-openai"}

# The namespaced routing heuristic resolves ``<prefix>/<model>`` to the provider
# whose id/prefix matches, so the config id shares this prefix.
_DEFAULT_PREFIX = "openwebui"


def is_dynamic(kind: str | None) -> bool:
    """Is this source registered into the live registry from providers.yaml?"""
    return (kind or "").lower() in DYNAMIC_KINDS


def is_discoverable(kind: str | None) -> bool:
    """Can this source's model list be fetched live from the upstream?

    True for every OpenAI-compatible catalog kind. The catalog's own
    ``openai_compatible`` flag decides, so a provider added there later is
    discoverable without touching this module.
    """
    k = (kind or "").lower()
    if is_dynamic(k):
        return True
    if k in _NON_OPENAI_KINDS:
        return False
    spec = PROVIDER_CATALOG.get(k)
    return bool(spec and spec.openai_compatible)


def _openai_adapter_for(kind: str) -> type[BaseProviderAdapter]:
    """The adapter class serving an OpenAI-compatible kind.

    Imported lazily and per-kind so a source whose provider has its own
    quirks (Groq's ``/openai/v1`` root, OpenRouter's referer headers) is
    discovered through exactly the client that will later serve its chat
    requests — otherwise discovery and inference could disagree about URLs.
    """
    from ollabridge.addons.providers.adapters.deepseek import DeepSeekAdapter
    from ollabridge.addons.providers.adapters.groq import GroqAdapter
    from ollabridge.addons.providers.adapters.huggingface import HuggingFaceAdapter
    from ollabridge.addons.providers.adapters.openai_compatible import (
        OpenAICompatibleAdapter,
    )
    from ollabridge.addons.providers.adapters.openrouter import OpenRouterAdapter

    return {
        "groq": GroqAdapter,
        "openrouter": OpenRouterAdapter,
        "deepseek": DeepSeekAdapter,
        "huggingface": HuggingFaceAdapter,
    }.get(kind.lower(), OpenAICompatibleAdapter)


def _base_url_for(rec: ProviderRecord) -> str:
    """The source's base URL, falling back to the catalog default.

    A record saved before the catalog's URL was corrected keeps its old value;
    the adapters normalize an over- or under-qualified base URL, so both shapes
    reach the same endpoint.
    """
    if rec.base_url:
        return rec.base_url
    spec = PROVIDER_CATALOG.get(rec.kind or rec.name)
    return spec.base_url if spec else ""


def build_adapter(
    rec: ProviderRecord, secret: str | None
) -> BaseProviderAdapter | None:
    """Construct the live adapter for a source, or None when the source cannot
    be discovered or lacks a base URL."""
    kind = (rec.kind or rec.name or "").lower()
    if not is_discoverable(kind):
        return None
    base_url = _base_url_for(rec)
    if not base_url:
        return None
    if is_dynamic(kind):
        return OpenWebUIAdapter(
            base_url=base_url,
            api_key=secret or None,
            model_prefix=_DEFAULT_PREFIX,
        )
    return _openai_adapter_for(kind)(base_url=base_url, api_key=secret or None)


def normalize_models(rec: ProviderRecord, models: list[dict]) -> list[dict]:
    """Bring a raw ``/models`` payload into the shape the Sources UI renders.

    The Open WebUI adapter already normalizes its own catalog (it has richer
    metadata to preserve); a plain OpenAI-style listing is only ``{"id": ...}``,
    so the missing fields are filled with honest values rather than guesses:
    every entry is an external chat model, and ``free`` comes from the free-tier
    catalog.
    """
    kind = (rec.kind or rec.name or "").lower()
    if is_dynamic(kind):
        return free_tier.annotate(kind, models)

    out: list[dict] = []
    seen: set[str] = set()
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        # Groq (and friends) report non-chat models — transcription, TTS,
        # moderation — in the same listing. Only a chat model may be
        # auto-selected as a default, so classify rather than assume.
        category = _classify(m, mid)
        out.append(
            {
                "id": mid,
                "object": "model",
                "name": str(m.get("name") or mid),
                "owned_by": m.get("owned_by") or kind,
                "upstream_model_id": mid,
                "upstream_owned_by": m.get("owned_by"),
                "connection_type": "external",
                "tags": [],
                "context_window": m.get("context_window"),
                "status": "available" if m.get("active", True) else "inactive",
                "stale": False,
                "capabilities": {"chat": category == "chat"},
                "category": category,
                "persona_compatible": category == "chat",
            }
        )
    out.sort(key=lambda m: str(m.get("id", "")))
    return free_tier.annotate(kind, out)


def _classify(raw: dict, model_id: str) -> str:
    """Coarse category for an OpenAI-style model entry: chat | audio | guard."""
    mid = model_id.lower()
    if any(t in mid for t in ("whisper", "tts", "-voice", "playai")):
        return "audio"
    if "guard" in mid or "moderation" in mid or "prompt-guard" in mid:
        return "guard"
    return "chat"


def default_model_for(rec: ProviderRecord, models: list[dict] | None = None) -> str:
    """The free model this source should default to, "" when none is known.

    Restricted to chat models: a transcription or guard model is a valid
    discovery result but never a sensible chat default. ``models=None`` means
    discovery has not run, and falls back to the free-tier catalog.
    """
    kind = (rec.kind or rec.name or "").lower()
    if models is None:
        return free_tier.preferred_default(kind)
    ids = [
        str(m.get("upstream_model_id") or m.get("id") or "")
        for m in models
        if isinstance(m, dict) and m.get("category", "chat") == "chat"
    ]
    return free_tier.preferred_default(kind, [i for i in ids if i])


def _addon_config(rec: ProviderRecord) -> ProviderConfig:
    return ProviderConfig(
        id=_provider_id(),
        name=rec.display_name or rec.name,
        kind="open_webui",
        enabled=rec.enabled,
        base_url=_base_url_for(rec),
        model_prefix=_DEFAULT_PREFIX,
        dynamic_models=True,
    )


def _provider_id() -> str:
    return _DEFAULT_PREFIX


def _registry(app: Any) -> Any:
    return getattr(getattr(app, "state", None), "provider_registry", None)


async def sync_source(app: Any, name: str, secret: str | None) -> bool:
    """Reconcile a saved source with the live registry. Returns True when the
    registry was updated.

    For a dynamic source this registers (or replaces) its adapter. For every
    other source it re-keys the already-seeded providers of the same kind, so a
    key pasted into the Sources UI actually reaches inference — the seeded
    adapters are built at startup from environment variables alone and would
    otherwise stay credential-less. Never raises."""
    try:
        rec = get_record(name)
        if rec is None:
            return False
        registry = _registry(app)
        if registry is None:
            return False
        kind = (rec.kind or rec.name or "").lower()

        if not is_dynamic(kind):
            return rekey_registered(registry, kind, secret if rec.enabled else None)

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


def rekey_registered(registry: Any, kind: str, secret: str | None) -> bool:
    """Push a BYOK key onto every seeded adapter of *kind*.

    The seed catalog registers e.g. ``groq-free`` at startup with whatever
    ``GROQ_API_KEY`` held then. When the user saves a Groq key in Settings the
    adapter must pick it up, or the source reports "connected" while every
    chat request 401s. Returns True when at least one adapter changed.
    """
    changed = False
    try:
        for config in registry.list_providers():
            if (config.kind or "").lower() != (kind or "").lower():
                continue
            adapter = registry.get_adapter(config.id)
            if adapter is None:
                continue
            # An explicit environment variable stays authoritative: it is the
            # deployment's own configuration, not something the UI owns.
            env_name = config.credential_env or ""
            if env_name and os.environ.get(env_name, "").strip():
                continue
            if getattr(adapter, "api_key", None) != secret:
                adapter.api_key = secret
                changed = True
    except Exception as exc:  # noqa: BLE001
        log.warning("rekey_registered(%s) failed: %s", kind, exc)
    return changed


async def unsync_source(app: Any, name: str) -> None:
    """Drop a deleted source's credential and, for a dynamic source, its live
    registration."""
    try:
        registry = _registry(app)
        if registry is None:
            return
        rec = get_record(name)
        kind = (rec.kind if rec else None) or name
        if is_dynamic(kind):
            await registry.unregister(_provider_id())
        else:
            rekey_registered(registry, kind, None)
    except Exception as exc:  # noqa: BLE001
        log.warning("unsync_source(%s) failed: %s", name, exc)


async def sync_all(app: Any) -> int:
    """Reconcile every enabled source at startup. Returns the count synced.
    Best-effort; never raises."""
    synced = 0
    try:
        from ollabridge.provider_ops import get_secret
    except Exception:  # noqa: BLE001
        return 0
    try:
        for rec in load_providers():
            if not rec.enabled:
                continue
            if await sync_source(app, rec.name, get_secret(rec.name)):
                synced += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("sync_all failed: %s", exc)
    return synced


def discovery_summary(models: list[dict]) -> dict[str, Any]:
    """Aggregate a normalized model list into the counts the UI shows (Local /
    External / free / persona-compatible / dynamic tags)."""
    conn: dict[str, int] = {}
    tags: dict[str, int] = {}
    categories: dict[str, int] = {}
    persona = 0
    free = 0
    for m in models:
        ct = m.get("connection_type")
        if ct:
            conn[str(ct)] = conn.get(str(ct), 0) + 1
        if m.get("persona_compatible") is True:
            persona += 1
        if m.get("free") is True:
            free += 1
        cat = m.get("category")
        if cat:
            categories[str(cat)] = categories.get(str(cat), 0) + 1
        for t in m.get("tags") or []:
            n = t.get("name") if isinstance(t, dict) else None
            if n:
                tags[str(n)] = tags.get(str(n), 0) + 1
    return {
        "count": len(models),
        "connection_types": conn,
        "persona_compatible": persona,
        "free": free,
        "categories": categories,
        "tags": tags,
    }
