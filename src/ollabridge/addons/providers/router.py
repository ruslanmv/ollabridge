"""
Provider router — selects the best provider for each request.

Supports:
- Model alias resolution (free-best, free-fast, local-private, etc.)
- Concrete model routing (finds providers that serve the requested model)
- Score-based ranking with health, latency, tier, and quota awareness
- Automatic failover to next-best candidate
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ollabridge.addons.providers import pacing
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderNetworkError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
)
from ollabridge.addons.providers.models import (
    HealthStatus,
    ProviderConfig,
    RouteResult,
)
from ollabridge.addons.providers.registry import ProviderRegistry
from ollabridge.addons.providers.scoring import compute_score
from ollabridge.core.connectivity import (
    NETWORK,
    OFFLINE,
    ONLINE,
    NetworkLost,
    NetworkMonitor,
    classify,
    is_remote,
)
from ollabridge.core.logsetup.request_facts import note as note_request

logger = logging.getLogger(__name__)


class ProvidersExhausted(RuntimeError):
    """Every candidate failed. Still a ``RuntimeError`` (what callers caught before), and it
    keeps the last provider's own error — a rate limit, a refusal, an outage — so the API can
    answer with what actually went wrong instead of guessing."""

    def __init__(self, message: str, *, last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class ProviderRouter:
    """Routes chat requests to the best available provider."""

    def __init__(self, registry: ProviderRegistry, *, network: NetworkMonitor | None = None) -> None:
        self.registry = registry
        # Online/offline state of this machine (core/connectivity.py). The
        # process-wide monitor probes the providers this router can use.
        self.network = network or NETWORK
        self.network.set_targets(self._remote_urls)

    @staticmethod
    def _url_of(adapter: Any, config: ProviderConfig | None = None) -> str:
        return str(getattr(adapter, "base_url", "") or getattr(config, "base_url", "") or "")

    def _remote_urls(self) -> list[str]:
        """Base URLs of the usable providers that live off this machine: what a
        connectivity probe connects to. Keyless or disabled ones are left out,
        so no host the user has not set up is ever contacted."""
        urls: list[str] = []
        for config in self.registry.list_enabled():
            if not self._is_available(config):
                continue
            url = self._url_of(self.registry.get_adapter(config.id), config)
            if url and is_remote(url):
                urls.append(url)
        return urls

    def _network_error(self, *, kind: str, reason: str | None) -> ProviderNetworkError:
        text = reason or "the network is unreachable"
        if kind == "connection_lost":
            return ProviderNetworkError(text, kind=kind, retry_after=2.0)
        return ProviderNetworkError(
            text, kind="network_offline", retry_after=float(self.network.retry_after_s())
        )

    def _is_available(self, config: ProviderConfig) -> bool:
        """Check if a provider can actually serve a request.

        A provider is unavailable if disabled, in a terminal health state, or
        — crucially — has no usable credential. Attempting a keyless external
        provider only produces 401/403 noise and a wasted round-trip, so we
        skip it here instead of failing over from it.
        """
        if not config.enabled:
            return False
        state = self.registry.get_state(config.id)
        if not state:
            return False
        if state.health in (
            HealthStatus.DOWN,
            HealthStatus.MAINTENANCE,
            HealthStatus.QUOTA_EXHAUSTED,
        ):
            return False
        adapter = self.registry.get_adapter(config.id)
        if adapter is not None and not getattr(adapter, "has_credential", True):
            logger.debug(
                "Skipping provider %s: no API key configured (set %s)",
                config.id,
                config.credential_env or "its API key",
            )
            return False
        return True

    def _rank_candidates(
        self, candidates: list[tuple[ProviderConfig, str]]
    ) -> list[RouteResult]:
        """Score and rank a list of (config, model) candidates."""
        scored: list[RouteResult] = []
        for config, model in candidates:
            state = self.registry.get_state(config.id)
            if not state:
                continue
            score = compute_score(config, state)
            scored.append(
                RouteResult(
                    provider_id=config.id,
                    provider_config=config,
                    model=model,
                    score=score,
                    reason=f"score={score:.3f} health={state.health.value} tier={config.tier.value}",
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    def resolve(self, model_or_alias: str) -> list[RouteResult]:
        """
        Resolve a model name or alias to a ranked list of routing candidates.

        If the name matches an alias, expand it to the candidate list.
        If not, look for any enabled provider that lists this model in its tags or
        fall back to providers with matching kind.

        Returns a list of RouteResult sorted by score (best first).
        """
        # 1. Check if it's an alias
        alias_candidates = self.registry.resolve_alias(model_or_alias)
        if alias_candidates:
            candidates: list[tuple[ProviderConfig, str]] = []
            for ac in alias_candidates:
                config = self.registry.get_config(ac.provider)
                if config and self._is_available(config):
                    candidates.append((config, ac.model))
            return self._rank_candidates(candidates)

        # 2. Not an alias. A provider that *declares* this exact model id wins
        #    outright — the id is data, not a guess. This is what routes
        #    "openai/gpt-oss-20b" to Groq: the name heuristic below would
        #    otherwise read the "openai/" namespace and offer it to an OpenAI
        #    source that does not serve it.
        available = [c for c in self.registry.list_enabled() if self._is_available(c)]
        declared = [
            (config, model_or_alias)
            for config in available
            if self._declares_model(config, model_or_alias)
        ]
        if declared:
            return self._rank_candidates(declared)

        # 3. Otherwise only offer the concrete model to a provider that
        #    plausibly serves it — i.e. the model id namespaces to the
        #    provider (e.g. "openai/...", "google/...") or the provider id /
        #    kind is named in the model string. We do NOT fan a bare model
        #    name out to every provider: an Ollama-style local model such as
        #    "granite3.2:latest" would otherwise be sent to Gemini/Groq/etc.,
        #    producing 401/403/404 noise before the gateway falls back to the
        #    local runtime. When nothing matches we return no candidates so
        #    the gateway uses its own local/relay routing.
        candidates = [
            (config, model_or_alias)
            for config in available
            if self._provider_serves_model(config, model_or_alias)
        ]
        return self._rank_candidates(candidates)

    @staticmethod
    def _declares_model(config: ProviderConfig, model: str) -> bool:
        """Does this provider's catalog entry name *model* outright?"""
        wanted = (model or "").strip().lower()
        if not wanted:
            return False
        return any(wanted == str(m).strip().lower() for m in (config.models or []))

    @staticmethod
    def _provider_serves_model(config: ProviderConfig, model: str) -> bool:
        """Heuristic: does this provider plausibly serve *model*?

        True when the model id references the provider by kind/id, or carries
        a vendor namespace prefix (``vendor/...``). Bare local-style names
        like ``llama3:latest`` match nothing here and stay on the local path.
        """
        m = model.lower()
        kind = (config.kind or "").lower()
        pid = (config.id or "").lower().split("-")[0]
        # A discovery provider owns its exact namespace prefix (e.g. an Open
        # WebUI source exposing "openwebui/<model>"): match it precisely.
        prefix = (getattr(config, "model_prefix", None) or "").lower().strip("/")
        if prefix and m.startswith(prefix + "/"):
            return True
        if kind and kind in m:
            return True
        if pid and pid in m:
            return True
        # Vendor-namespaced ids (openrouter/HF style: "google/gemma-3-27b-it")
        if "/" in model and config.kind in (
            "openrouter",
            "huggingface",
            "openai_compatible",
        ):
            return True
        return False

    async def route_chat(
        self,
        model_or_alias: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict:
        """
        Route a chat request to the best provider with automatic failover.

        Tries candidates in score order. On failure, moves to the next.
        Returns the first successful OpenAI-compatible response dict.
        Raises RuntimeError if all candidates fail.
        """
        candidates = self.resolve(model_or_alias)
        if not candidates:
            raise RuntimeError(
                f"No available provider for model/alias '{model_or_alias}'. "
                "Check provider health and quotas."
            )

        last_error: Exception | None = None
        network = self.network
        for route in candidates:
            adapter = self.registry.get_adapter(route.provider_id)
            if not adapter:
                continue

            url = self._url_of(adapter, getattr(route, "provider_config", None))
            remote = network.enabled and is_remote(url)
            # Name the provider on the request's log line also when it fails;
            # a success notes it again with the tokens.
            note_request(route=route.provider_id)

            # Circuit open: this machine is offline. Re-check first (once every
            # couple of seconds, shared by concurrent requests), so the first
            # request after the tunnel goes through at once.
            if remote and network.offline and await network.check() == OFFLINE:
                network.note_failed_fast()
                logger.debug(
                    "Skipping provider %s: network offline (%s)", route.provider_id, network.reason
                )
                last_error = self._network_error(kind="network_offline", reason=network.reason)
                continue

            start = time.monotonic()

            async def _attempt(adapter=adapter, route=route, url=url, remote=remote) -> dict:
                # Timed from the call itself, not from the time it spent
                # waiting for its turn, so pacing does not skew latency scores.
                nonlocal start
                start = time.monotonic()
                if not remote:
                    return await adapter.chat(route.model, messages, **kwargs)
                # Remote: a stall watchdog tells a dropped link (abort in ~25 s)
                # from a slow model (keep waiting).
                return await network.guard(
                    lambda: adapter.chat(route.model, messages, **kwargs),
                    url=url,
                    label=route.provider_id,
                )

            try:
                # Per-attempt detail: DEBUG. The request's own access line
                # names the provider that answered (see api/request_log.py);
                # a failover below is still a WARNING.
                logger.debug(
                    "Routing to %s (model=%s score=%.3f)",
                    route.provider_id,
                    route.model,
                    route.score,
                )
                # Within the provider's rate limits (Settings → Rate limits):
                # paced, capped, and retried on a rate limit when so set.
                result = await pacing.call(route.provider_id, _attempt)
                latency_ms = (time.monotonic() - start) * 1000

                # Extract token usage for quota tracking
                usage = result.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                await self.registry.record_request(
                    route.provider_id,
                    latency_ms=latency_ms,
                    tokens=total_tokens,
                    success=True,
                )

                logger.debug(
                    "Provider %s responded in %.0fms (tokens=%d)",
                    route.provider_id,
                    latency_ms,
                    total_tokens,
                )
                note_request(route=route.provider_id, tokens=total_tokens or None)
                return result

            except ProviderRateLimited as exc:
                # Temporary: the provider said "slow down", its budget is not
                # spent. Marking it quota-exhausted would take it out of
                # routing until a restart (every later request for its models
                # fell through to local Ollama); the cooldown in pacing keeps
                # it from being hammered instead.
                latency_ms = (time.monotonic() - start) * 1000
                if not exc.local:
                    await self.registry.record_request(
                        route.provider_id, latency_ms=latency_ms, success=False
                    )
                logger.warning(
                    "Provider %s is rate limiting%s: %s — failing over",
                    route.provider_id,
                    "" if exc.local else f" ({latency_ms:.0f}ms)",
                    exc,
                )
                last_error = exc

            except ProviderQuotaExceeded as exc:
                latency_ms = (time.monotonic() - start) * 1000
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, success=False
                )
                await self.registry.update_health(
                    route.provider_id,
                    HealthStatus.QUOTA_EXHAUSTED,
                    error=str(exc),
                )
                logger.warning(
                    "Provider %s quota exhausted (%.0fms): %s — failing over",
                    route.provider_id,
                    latency_ms,
                    exc,
                )
                last_error = exc

            except ProviderAuthError as exc:
                # Wrong/missing credentials: failing over to the same provider
                # via another model won't help. Skip remaining routes on this
                # provider but keep trying others.
                latency_ms = (time.monotonic() - start) * 1000
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, success=False
                )
                logger.warning(
                    "Provider %s auth error (%.0fms): %s — skipping provider",
                    route.provider_id,
                    latency_ms,
                    exc,
                )
                last_error = exc

            except ProviderBadRequest as exc:
                # 4xx that isn't auth/quota — usually a model-specific issue.
                # Move on to next route without penalising provider health.
                latency_ms = (time.monotonic() - start) * 1000
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, success=True
                )
                logger.warning(
                    "Provider %s rejected request for model %s (%.0fms): %s",
                    route.provider_id,
                    route.model,
                    latency_ms,
                    exc,
                )
                last_error = exc

            except NetworkLost as exc:
                # The link dropped while the answer was pending (watchdog).
                # Not the provider's fault: its health is left alone.
                latency_ms = (time.monotonic() - start) * 1000
                logger.warning(
                    "Provider %s: connection lost after %.0fms: %s — trying next candidate",
                    route.provider_id,
                    latency_ms,
                    exc,
                )
                last_error = self._network_error(kind="connection_lost", reason=str(exc))
                last_error.__cause__ = exc

            except (ProviderError, Exception) as exc:
                latency_ms = (time.monotonic() - start) * 1000
                fault = classify(exc) if remote else None
                seen_reachable = getattr(exc, "network_reachable", None) is True
                verdict: str | None = None
                if fault is not None and fault.suspects_network and not seen_reachable:
                    # No answer at all: is it this machine's network, or this
                    # provider? A probe of the configured providers decides.
                    verdict = await network.check(max_age=1.0)
                    if verdict == OFFLINE:
                        logger.debug(
                            "Provider %s unreachable (%s): the network is down, not counted "
                            "against the provider",
                            route.provider_id,
                            exc,
                        )
                        kind = (
                            "connection_lost"
                            if fault.kind in ("connection_lost", "read_timeout")
                            else "network_offline"
                        )
                        last_error = self._network_error(kind=kind, reason=network.reason)
                        last_error.__cause__ = exc
                        continue
                await self.registry.record_request(
                    route.provider_id, latency_ms=latency_ms, success=False
                )
                detail = str(exc).strip() or type(exc).__name__
                if seen_reachable and fault is not None:
                    detail += " (the provider's server stayed reachable: slow or overloaded, not a network problem)"
                elif fault is not None and verdict == ONLINE:
                    detail += f" ({fault.describe()}; the network itself is up)"
                logger.warning(
                    "Provider %s failed (%.0fms): %s — trying next candidate",
                    route.provider_id,
                    latency_ms,
                    detail,
                )
                last_error = exc

        raise ProvidersExhausted(
            f"All providers failed for '{model_or_alias}'. Last error: {last_error}",
            last_error=last_error,
        ) from last_error
