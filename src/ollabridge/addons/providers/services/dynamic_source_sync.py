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

from ollabridge.addons.providers import model_defaults
from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.models import (
    ProviderCategory,
    ProviderConfig,
    ProviderTier,
)
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    ProviderRecord,
    get_extra,
    get_record,
    load_providers,
)

log = logging.getLogger(__name__)

# Source kinds that are registered into the live registry from providers.yaml,
# because nothing in the seed catalog covers them.
DYNAMIC_KINDS = {"open_webui"}

# Kinds whose catalog cannot be listed the OpenAI way and that have no
# adapter of their own here, so the settings picker has nothing to ask.
_UNDISCOVERABLE_KINDS = {"anthropic", "bedrock", "azure-openai"}

# Kinds with a dedicated adapter that speaks the provider's own catalog API.
# watsonx is the case in point: its models are per region, per plan and per
# account, so a listing is the only honest answer to "what can I run here".
_NATIVE_DISCOVERY_KINDS = {"watsonx"}

# The namespaced routing heuristic resolves ``<prefix>/<model>`` to the provider
# whose id/prefix matches, so the config id shares this prefix.
_DEFAULT_PREFIX = "openwebui"


def is_dynamic(kind: str | None) -> bool:
    """Is this source registered into the live registry from providers.yaml?"""
    return (kind or "").lower() in DYNAMIC_KINDS


def is_discoverable(kind: str | None) -> bool:
    """Can this source's model list be fetched live from the upstream?

    True for every OpenAI-compatible catalog kind, plus the kinds with a
    native catalog adapter. The catalog's own ``openai_compatible`` flag
    decides the rest, so a provider added there later is discoverable
    without touching this module.
    """
    k = (kind or "").lower()
    if is_dynamic(k) or k in _NATIVE_DISCOVERY_KINDS:
        return True
    if k in _UNDISCOVERABLE_KINDS:
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
    if kind == "watsonx":
        from ollabridge.addons.providers.adapters.watsonx import WatsonxAdapter

        # Listing the catalog needs only the key; a chat request also needs
        # the scope, so pass it through and let `chat` be the thing that
        # complains when it is missing. Discovery works before the project
        # id is filled in, which is what makes the settings form usable.
        return WatsonxAdapter(
            base_url=base_url,
            api_key=secret or None,
            project_id=get_extra(rec, "project_id"),
            space_id=get_extra(rec, "space_id"),
        )
    return _openai_adapter_for(kind)(base_url=base_url, api_key=secret or None)


def normalize_models(rec: ProviderRecord, models: list[dict]) -> list[dict]:
    """Bring a raw model listing into the shape the Sources UI renders.

    The Open WebUI adapter already normalizes its own catalog (it has richer
    metadata to preserve); a plain OpenAI-style listing is only ``{"id": ...}``,
    so the missing fields are filled with honest values rather than guesses:
    every entry is an external chat model, and ``free`` comes from the model
    defaults catalog. watsonx sits in between — its adapter has already
    resolved the label, provider and lifecycle, which are carried through
    here rather than flattened away.
    """
    kind = (rec.kind or rec.name or "").lower()
    if is_dynamic(kind):
        return model_defaults.annotate(kind, models)

    out: list[dict] = []
    seen: set[str] = set()
    for m in models:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        # Providers report non-chat models — transcription, TTS, moderation,
        # safety guards — in the same listing. Only a chat model may be
        # auto-selected as a default, so classify rather than assume.
        category = _classify(mid)
        deprecated = bool(m.get("deprecated"))
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
                "description": m.get("description"),
                "context_window": m.get("context_window"),
                # A model on its way out is still listed — the user may have
                # pinned it deliberately — but it is never auto-selected.
                "deprecated": deprecated,
                "lifecycle": m.get("lifecycle") or [],
                "status": "deprecated"
                if deprecated
                else ("available" if m.get("active", True) else "inactive"),
                "stale": False,
                "capabilities": {"chat": category == "chat"},
                "category": category,
                "persona_compatible": category == "chat",
            }
        )
    out.sort(key=lambda m: str(m.get("id", "")))
    return model_defaults.annotate(kind, out)


def _classify(model_id: str) -> str:
    """Coarse category for a model id: chat | audio | embedding | guard."""
    mid = model_id.lower()
    if any(t in mid for t in ("whisper", "tts", "-voice", "playai")):
        return "audio"
    if "embedding" in mid or "-embed" in mid or "rerank" in mid:
        return "embedding"
    if "guard" in mid or "moderation" in mid:
        return "guard"
    return "chat"


def default_model_for(rec: ProviderRecord, models: list[dict] | None = None) -> str:
    """The model this source should default to, "" when none is known.

    Only a live, non-deprecated chat model is eligible: an embedding or
    safety-guard model is a valid discovery result but never a sensible chat
    default, and a model the provider has marked deprecated would work today
    and fail on its retirement date. ``models=None`` means discovery has not
    run, and falls back to the catalog's top choice.
    """
    kind = (rec.kind or rec.name or "").lower()
    if models is None:
        return model_defaults.preferred_default(kind)
    ids = [
        str(m.get("upstream_model_id") or m.get("id") or "")
        for m in models
        if isinstance(m, dict)
        and m.get("category", "chat") == "chat"
        and not m.get("deprecated")
    ]
    return model_defaults.preferred_default(kind, [i for i in ids if i])


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


def byok_provider_id(name: str) -> str:
    """Registry id for a BYOK source registered as its own runtime.

    Namespaced so it can never collide with a seed-catalog id — ``groq`` the
    saved source and ``groq-free`` the seeded provider are different runtimes
    with different credentials, and unregistering one must not touch the other.
    """
    return f"byok-{name.lower().strip()}"


def _byok_config(rec: ProviderRecord, models: list[str]) -> ProviderConfig:
    """The registry entry for a routing-enabled BYOK source.

    ``models`` is what makes the source routable: the router matches a
    concrete request against a provider's declared ids before falling back to
    guessing from the model name, and a watsonx id like
    ``ibm/granite-4-h-small`` matches no heuristic at all.
    """
    kind = (rec.kind or rec.name or "").lower()
    # Scoring prefers a free provider over a paid one, so say which this is
    # rather than assuming: a Groq source costs nothing to run, a watsonx one
    # is billed per token.
    free = any(model_defaults.is_free(kind, m) for m in models)
    return ProviderConfig(
        id=byok_provider_id(rec.name),
        name=rec.display_name or rec.name,
        kind=kind,
        enabled=rec.enabled,
        # A source the user connected and opted into routing is a main-tier
        # runtime: they chose it deliberately, so it is not a last resort.
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE if free else ProviderCategory.PAID,
        base_url=_base_url_for(rec),
        models=models,
        notes="Connected in Sources (BYOK)",
    )


def _seeded_kinds(registry: Any) -> set[str]:
    """Provider kinds the seed catalog already covers and has registered."""
    try:
        return {
            (c.kind or "").lower()
            for c in registry.list_providers()
            if c.enabled and not str(c.id).startswith("byok-")
        }
    except Exception:  # noqa: BLE001
        return set()


def _registry(app: Any) -> Any:
    return getattr(getattr(app, "state", None), "provider_registry", None)


async def sync_source(app: Any, name: str, secret: str | None) -> bool:
    """Reconcile a saved source with the live registry. Returns True when the
    registry was updated. Never raises.

    Three cases, in order:

    * A *dynamic* source (Open WebUI) is registered from providers.yaml,
      because nothing in the seed catalog covers it.
    * A source whose kind the seed catalog already carries re-keys those
      seeded adapters, so a key pasted into Sources reaches inference — the
      seeded adapters are built at startup from environment variables alone
      and would otherwise stay credential-less. Its chosen model is added to
      the seeded provider's declared ids so the router can reach it.
    * Any other connected source with routing switched on is registered as a
      runtime of its own. Without this a watsonx source could be "Connected"
      with "Routing on" and still serve nothing: the local seed catalog has
      no watsonx provider, so its model resolved to no candidate at all.
    """
    try:
        rec = get_record(name)
        if rec is None:
            return False
        registry = _registry(app)
        if registry is None:
            return False
        kind = (rec.kind or rec.name or "").lower()

        if is_dynamic(kind):
            if not rec.enabled:
                await registry.unregister(_provider_id())
                return False
            adapter = build_adapter(rec, secret)
            if adapter is None:
                return False
            await registry.register(_addon_config(rec), adapter)
            return True

        if kind in _seeded_kinds(registry):
            changed = rekey_registered(registry, kind, secret if rec.enabled else None)
            if declare_model(registry, kind, rec.default_model):
                changed = True
            return changed

        return await sync_byok_runtime(registry, rec, secret)
    except Exception as exc:  # noqa: BLE001 - best-effort; never break the request
        log.warning("sync_source(%s) failed: %s", name, exc)
        return False


async def sync_byok_runtime(
    registry: Any, rec: ProviderRecord, secret: str | None
) -> bool:
    """Register (or drop) a BYOK source as a runtime of its own.

    Registered only when the source is enabled, has a credential, names a
    model to serve, and the user has switched routing on — the same explicit
    opt-in the Sources UI describes as "OllaBridge may pick this source under
    the active routing profile". Anything less and the source is removed from
    the registry, so turning routing off takes effect immediately.
    """
    provider_id = byok_provider_id(rec.name)
    models = [m for m in (rec.default_model,) if m]
    routable = bool(rec.enabled and rec.allow_routing and secret and models)
    if not routable:
        await registry.unregister(provider_id)
        return False
    adapter = build_adapter(rec, secret)
    if adapter is None:
        return False
    await registry.register(_byok_config(rec, models), adapter)
    return True


def byok_runtime_models(registry: Any, already: list[dict] | None = None) -> list[dict]:
    """OpenAI-shaped entries for the models BYOK runtimes serve.

    These ids are declared on the provider config, so this costs no upstream
    call. ``already`` is the list being built, so a model a local runtime
    also serves is not listed twice. Never raises — a listing must not fail
    over a registry hiccup.
    """
    out: list[dict] = []
    try:
        seen = {
            m.get("id") for m in (already or []) if isinstance(m, dict) and m.get("id")
        }
        for config in registry.list_enabled():
            if not str(config.id).startswith("byok-"):
                continue
            for model_id in config.models:
                if model_id and model_id not in seen:
                    seen.add(model_id)
                    out.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "owned_by": config.name or config.kind,
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        log.warning("byok_runtime_models failed: %s", exc)
    return out


def declare_model(registry: Any, kind: str, model_id: str) -> bool:
    """Teach the seeded providers of *kind* about a model the user picked.

    The seed catalog lists the ids it knows; a model chosen from the live
    catalog may not be among them, and the router's name heuristic cannot
    place a vendor-namespaced id on the right provider. Returns True when a
    provider's declared list actually grew.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return False
    changed = False
    try:
        for config in registry.list_providers():
            if (config.kind or "").lower() != (kind or "").lower():
                continue
            if any(model_id.lower() == str(m).lower() for m in config.models):
                continue
            config.models = [*config.models, model_id]
            changed = True
    except Exception as exc:  # noqa: BLE001
        log.warning("declare_model(%s, %s) failed: %s", kind, model_id, exc)
    return changed


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
    """Drop a deleted source from the live registry.

    Called after the record and its key are gone, so it clears every trace:
    the dynamic registration, the BYOK runtime, and the credential pushed
    onto any seeded provider of the same kind. Missing any of the three would
    leave a deleted source still serving requests until the next restart.
    """
    try:
        registry = _registry(app)
        if registry is None:
            return
        rec = get_record(name)
        kind = ((rec.kind if rec else None) or name or "").lower()
        if is_dynamic(kind):
            await registry.unregister(_provider_id())
            return
        await registry.unregister(byok_provider_id(name))
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
