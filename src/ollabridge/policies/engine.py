"""Policy loading, validation, and route explanation.

Built-in policies cover the friendly aliases (``local-private``, ``fast``,
``cheap``, ``best``, ``coding``, ``reasoning``, ``vision``, ``team-default``,
``cloud-relay``, ``local-gpu``). A user policy in
``~/.ollabridge/policies.yaml`` with a matching alias overrides the built-in.

Route explanation is deliberately honest: it inspects what is actually
configured (local models, provider credentials, cloud pairing) and reports
why each candidate was selected or skipped. It never sends a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from ollabridge.core import paths
from ollabridge.policies.models import (
    PoliciesFile,
    Policy,
    PreferenceTarget,
    RouteExplanation,
)

# Indicative public list prices (USD per 1k tokens, blended input/output).
# Used only for the "estimated cost" hint in `route explain`; real billing
# is always the provider's. Local inference is $0.
_COST_PER_1K: dict[str, float] = {
    "local": 0.0,
    "openai": 0.0075,
    "anthropic": 0.009,
    "gemini": 0.0035,
    "azure-openai": 0.0075,
    "bedrock": 0.008,
    "groq": 0.0006,
    "openrouter": 0.003,
    "huggingface": 0.0,
    "deepseek": 0.0006,
    "mistral": 0.002,
    "together": 0.0009,
    "fireworks": 0.0009,
}

_BUILTIN_YAML = """
policies:
  - name: private_mode
    match: {alias: local-private}
    route:
      allow: [{type: local_device}]
      deny: [{type: external_provider}, {type: cloud_relay}]
      prefer: [{provider: local}]
      fallback: false
    logging: {prompt_logging: false}

  - name: fast_mode
    match: {alias: fast}
    route:
      prefer:
        - {provider: local, device_tag: gpu}
        - {provider: groq}
        - {provider: openrouter}
      max_latency_ms: 2000

  - name: cheap_mode
    match: {alias: cheap}
    route:
      prefer:
        - {provider: local}
        - {provider: groq}
        - {provider: deepseek}
        - {provider: openrouter}
      max_cost_usd_per_1k_tokens: 0.01

  - name: best_mode
    match: {alias: best}
    route:
      prefer:
        - {provider: anthropic}
        - {provider: openai}
        - {provider: local, device_tag: gpu}

  - name: coding_mode
    match: {alias: coding}
    route:
      prefer:
        - {provider: local, device_tag: gpu}
        - {provider: anthropic}
        - {provider: openrouter}
      require: {tools: true}

  - name: reasoning_mode
    match: {alias: reasoning}
    route:
      prefer:
        - {provider: local}
        - {provider: anthropic}
        - {provider: deepseek}

  - name: vision_mode
    match: {alias: vision}
    route:
      prefer:
        - {provider: local}
        - {provider: openai}
        - {provider: gemini}
      require: {vision: true}

  - name: team_default
    match: {alias: team-default}
    route:
      prefer:
        - {provider: local}
        - {provider: anthropic}

  - name: cloud_relay_mode
    match: {alias: cloud-relay}
    route:
      allow: [{type: cloud_relay}, {type: local_device}]
      prefer: [{provider: local}]

  - name: local_gpu_mode
    match: {alias: local-gpu}
    route:
      allow: [{type: local_device}]
      deny: [{type: external_provider}]
      prefer: [{provider: local, device_tag: gpu}]
      fallback: false
"""

BUILTIN_ALIASES = (
    "local-private",
    "fast",
    "cheap",
    "best",
    "coding",
    "reasoning",
    "vision",
    "team-default",
    "cloud-relay",
    "local-gpu",
)


def builtin_policies() -> list[Policy]:
    return PoliciesFile.model_validate(yaml.safe_load(_BUILTIN_YAML)).policies


def load_policies(
    path: Path | None = None, *, include_builtin: bool = True
) -> list[Policy]:
    """User policies first (they win on alias collisions), then built-ins."""
    p = path or paths.policies_file()
    user: list[Policy] = []
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        user = PoliciesFile.model_validate(raw).policies
    if not include_builtin:
        return user
    taken = {pol.match.alias for pol in user if pol.match.alias}
    taken |= {pol.match.model for pol in user if pol.match.model}
    merged = list(user)
    for pol in builtin_policies():
        if pol.match.alias in taken or pol.match.model in taken:
            continue
        merged.append(pol)
    return merged


def validate_policies_file(path: Path | None = None) -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    p = path or paths.policies_file()
    problems: list[str] = []
    if not p.exists():
        return problems  # nothing to validate; built-ins apply
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"YAML parse error: {exc}"]
    except OSError as exc:
        return [f"cannot read {p}: {exc}"]
    if raw is None:
        return problems
    if not isinstance(raw, dict):
        return [f"{p} must contain a mapping with a top-level 'policies' list"]
    try:
        parsed = PoliciesFile.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            problems.append(f"{loc}: {err['msg']}")
        return problems
    for pol in parsed.policies:
        if pol.route.fallback is False and not pol.route.prefer and not pol.route.allow:
            problems.append(
                f"policy {pol.name!r}: fallback disabled but no prefer/allow targets"
            )
        if (
            pol.route.max_cost_usd_per_1k_tokens is not None
            and pol.route.max_cost_usd_per_1k_tokens < 0
        ):
            problems.append(
                f"policy {pol.name!r}: max_cost_usd_per_1k_tokens must be >= 0"
            )
    return problems


def find_policy(
    name_or_alias: str, policies: list[Policy] | None = None
) -> Policy | None:
    pols = policies if policies is not None else load_policies()
    for pol in pols:
        if pol.match.alias == name_or_alias or pol.match.model == name_or_alias:
            return pol
    for pol in pols:
        if pol.name == name_or_alias:
            return pol
    return None


@dataclass
class RouteContext:
    """A snapshot of what is actually available, gathered without sending prompts."""

    local_models: list[str] = field(default_factory=list)
    local_device_name: str = "this device"
    local_device_tags: list[str] = field(default_factory=list)
    configured_providers: set[str] = field(default_factory=set)
    cloud_paired: bool = False
    cloud_relay_connected: bool = False
    prompt_logging: bool = False


def gather_route_context() -> RouteContext:
    """Build a :class:`RouteContext` from the live local environment."""
    import socket

    import httpx

    from ollabridge.cloud.device_config import load_cloud_device_credentials
    from ollabridge.core.settings import settings

    ctx = RouteContext()
    try:
        ctx.local_device_name = socket.gethostname() or "this device"
    except Exception:
        pass

    # Local models straight from Ollama (no auth, no prompt sent).
    try:
        r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            ctx.local_models = [
                m.get("name", "") for m in r.json().get("models", []) if m.get("name")
            ]
    except Exception:
        pass

    # Configured providers: encrypted secret store + env vars.
    try:
        from ollabridge.providers_meta import configured_provider_names

        ctx.configured_providers = configured_provider_names()
    except Exception:
        pass

    ctx.cloud_paired = load_cloud_device_credentials() is not None
    return ctx


def _model_for_local(pref: PreferenceTarget, ctx: RouteContext) -> str | None:
    if pref.model and pref.model in ctx.local_models:
        return pref.model
    if pref.model:
        # exact tag missing; try prefix match (e.g. "llama3.1" vs "llama3.1:8b")
        for m in ctx.local_models:
            if m.startswith(pref.model):
                return m
        return None
    return ctx.local_models[0] if ctx.local_models else None


def explain_route(
    requested: str,
    *,
    context: RouteContext | None = None,
    policies: list[Policy] | None = None,
) -> RouteExplanation:
    """Resolve *requested* (alias or model id) and explain every decision."""
    ctx = context if context is not None else gather_route_context()
    pol = find_policy(requested, policies)

    exp = RouteExplanation(requested=requested)
    if pol is None:
        # Not an alias — treat as a direct model request.
        if requested in ctx.local_models:
            exp.selected_backend = "local_device"
            exp.selected_device = ctx.local_device_name
            exp.selected_model = requested
            exp.estimated_cost_usd_per_1k_tokens = 0.0
            exp.reasons.append(
                f"'{requested}' is available on local device {ctx.local_device_name!r}"
            )
        else:
            exp.error = (
                f"no policy matches {requested!r} and it is not a local model; "
                "it will be passed through to the gateway router as-is"
            )
            exp.reasons.append(
                "direct model request — gateway routing applies at request time"
            )
        return exp

    exp.policy_name = pol.name
    exp.prompt_logging = pol.logging.prompt_logging

    def denied(target_type: str, provider: str | None) -> bool:
        if any(
            f.matches(target_type=target_type, provider=provider)
            for f in pol.route.deny
        ):
            return True
        if pol.route.allow and not any(
            f.matches(target_type=target_type, provider=provider)
            for f in pol.route.allow
        ):
            return True
        return False

    candidates = pol.route.prefer or [PreferenceTarget(provider="local")]
    remaining: list[str] = []
    for pref in candidates:
        if exp.selected_backend:
            # Already selected — the rest are fallbacks (when allowed).
            if pol.route.fallback:
                remaining.append(pref.provider if pref.is_local is False else "local")
            continue

        if pref.is_local:
            if denied("local_device", None):
                exp.reasons.append("local device denied by policy")
                continue
            if pref.device_tag and pref.device_tag not in ctx.local_device_tags:
                (
                    exp.reasons.append(
                        f"local device skipped: tag {pref.device_tag!r} not present"
                    )
                    if ctx.local_models
                    else None
                )
                # tag mismatch is advisory; still allow plain local if models exist
            model = _model_for_local(pref, ctx)
            if not model:
                exp.reasons.append(
                    "local device skipped: no matching local model detected"
                )
                continue
            exp.selected_backend = "local_device"
            exp.selected_device = ctx.local_device_name
            exp.selected_model = model
            exp.estimated_cost_usd_per_1k_tokens = 0.0
            exp.reasons.append(
                f"policy {pol.name!r} prefers local; model {model!r} available on {ctx.local_device_name!r}"
            )
        else:
            provider = pref.provider.lower()
            if denied("external_provider", provider):
                exp.reasons.append(f"provider {provider!r} denied by policy")
                continue
            if provider not in ctx.configured_providers:
                exp.reasons.append(
                    f"provider {provider!r} skipped: no credential configured"
                )
                continue
            cost = _COST_PER_1K.get(provider)
            ceiling = pol.route.max_cost_usd_per_1k_tokens
            if ceiling is not None and cost is not None and cost > ceiling:
                exp.reasons.append(
                    f"provider {provider!r} skipped: est. ${cost}/1k tokens exceeds policy ceiling ${ceiling}"
                )
                continue
            exp.selected_backend = f"provider:{provider}"
            exp.selected_provider = provider
            exp.selected_model = pref.model
            exp.estimated_cost_usd_per_1k_tokens = cost
            exp.reasons.append(f"policy {pol.name!r} selected provider {provider!r}")

    if not exp.selected_backend:
        if pol.route.fallback:
            exp.error = (
                "no preferred backend available; gateway default routing would apply"
            )
        else:
            exp.error = (
                "no allowed backend available and fallback is disabled by policy"
            )

    exp.fallbacks = remaining
    exp.cloud_relay = bool(ctx.cloud_relay_connected)
    return exp
