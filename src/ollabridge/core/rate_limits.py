"""Rate limits: OllaBridge's own inbound request limit, and the per-provider
outbound limits the provider router applies (addons/providers/pacing.py).

Both live under one ``rate_limits`` key in the runtime settings store
(``runtime_settings.json``), are edited from Settings → Rate limits in the
dashboard (``/admin/rate-limits``) and apply live, without a restart.

The defaults change nothing: the inbound limit is off and no provider is
paced or retried, so a gateway that never opens the section behaves exactly
as before. A caller that makes many calls is never newly throttled by an
upgrade.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ollabridge.core import runtime_settings as rts
from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge")

SETTINGS_KEY = "rate_limits"

# The inbound limit counts requests that start in any 60-second window.
WINDOW_SECONDS = 60.0

_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def rpm_from_env(raw: str | None) -> int:
    """``RATE_LIMIT`` in slowapi syntax (``60/minute``, ``2/second``,
    ``600/hour``) as requests per minute: the inbound limit's starting value.
    Anything unreadable gives 60, the documented default."""
    m = re.fullmatch(r"\s*(\d+)\s*(?:/|per)\s*(second|minute|hour|day)s?\s*", raw or "", re.IGNORECASE)
    if not m:
        return 60
    n, unit = int(m.group(1)), m.group(2).lower()
    per_minute = {"second": n * 60.0, "minute": float(n), "hour": n / 60.0, "day": n / 1440.0}[unit]
    return max(1, math.ceil(per_minute))


class InboundLimit(BaseModel):
    """OllaBridge's own limit on model calls (POST /v1/...), per client."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    requests_per_minute: int = Field(
        default_factory=lambda: rpm_from_env(settings.RATE_LIMIT), ge=1, le=100_000
    )


OnRateLimit = Literal["fail_fast", "wait_retry"]


class ProviderLimit(BaseModel):
    """Outbound limits toward one provider (a provider registry id, such as
    ``openwebui``). Zero means "no limit" for the two caps."""

    model_config = ConfigDict(extra="forbid")

    # Requests are spaced evenly: at most one starts every 60/N seconds.
    requests_per_minute: int = Field(0, ge=0, le=10_000)
    max_concurrent: int = Field(0, ge=0, le=1_000)
    # What to do when the provider answers "rate limit": hand the client a
    # 429 at once (what OllaBridge always did), or wait and retry with
    # backoff, honouring Retry-After, until max_wait_seconds is spent.
    on_rate_limit: OnRateLimit = "fail_fast"
    # The longest one request waits inside OllaBridge (queue, pacing,
    # cooldown and retries together) before it is answered with a 429.
    max_wait_seconds: int = Field(120, ge=1, le=3_600)
    # After a rate-limit answer the provider is left alone this long; in
    # fail-fast mode requests meanwhile get a 429 without calling it. In
    # wait-and-retry mode it is also the first backoff step.
    cooldown_seconds: int = Field(0, ge=0, le=3_600)


DEFAULT_PROVIDER_LIMIT = ProviderLimit()

# A cautious starting point for any provider whose limit is not published
# (a self-hosted chat server's per-user limit is often set by its admins):
# a steady trickle that a heavy agent run can live with, waiting instead of
# failing.
SUGGESTED_PROVIDER_LIMIT = ProviderLimit(
    requests_per_minute=12,
    max_concurrent=2,
    on_rate_limit="wait_retry",
    max_wait_seconds=180,
    cooldown_seconds=60,
)


class RateLimitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbound: InboundLimit = Field(default_factory=InboundLimit)
    providers: dict[str, ProviderLimit] = Field(default_factory=dict)

    @field_validator("providers")
    @classmethod
    def _provider_ids(cls, value: dict[str, ProviderLimit]) -> dict[str, ProviderLimit]:
        for pid in value:
            if not _PROVIDER_ID.match(pid):
                raise ValueError(f"invalid provider id: {pid!r}")
        return value


_current: RateLimitSettings | None = None


def current() -> RateLimitSettings:
    """The saved rate-limit settings (defaults when none were saved). A stored
    value that no longer validates is ignored with a warning rather than
    breaking every request."""
    global _current
    if _current is None:
        raw = rts.get(SETTINGS_KEY) or {}
        try:
            _current = RateLimitSettings.model_validate(raw)
        except ValidationError as exc:
            log.warning("Ignoring invalid saved rate limits (%d error(s)); using defaults", exc.error_count())
            _current = RateLimitSettings()
    return _current


def save(new: RateLimitSettings) -> RateLimitSettings:
    """Persist *new* in the runtime settings store and apply it at once.
    Provider entries equal to the defaults are dropped, so "configured" in
    the dashboard means "differs from today's behaviour"."""
    global _current
    pruned = {pid: lim for pid, lim in new.providers.items() if lim != DEFAULT_PROVIDER_LIMIT}
    data = new.model_copy(update={"providers": pruned})
    rts.update({SETTINGS_KEY: data.model_dump()})
    _current = data
    return data


def reload() -> None:
    """Forget the cached settings; the next read goes to the store again."""
    global _current
    _current = None


def provider_limit(provider_id: str) -> ProviderLimit:
    return current().providers.get(provider_id) or DEFAULT_PROVIDER_LIMIT


# ── Inbound limit ───────────────────────────────────────────────────────


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def client_identity(host: str | None, x_api_key: str | None, authorization: str | None) -> tuple[str, str]:
    """``(bucket, label)`` for one caller: its address, and the API key when it
    sends one, so two containers behind one bridge address with different
    keys are counted apart. The key itself is never kept or shown, only a
    short SHA-256 fingerprint of it."""
    addr = host or "unknown"
    key = (x_api_key or "").strip()
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization.split(" ", 1)[1].strip()
    if not key:
        return addr, addr
    fp = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return f"{addr}|{fp}", f"{addr} (key #{fp})"


class InboundLimiter:
    """A sliding 60-second window per caller: at most N model calls start in
    any minute. A refused request is not counted, so a client that backs off
    for the Retry-After it was given gets in."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._last_prune = 0.0
        self.refusals: deque[dict[str, Any]] = deque(maxlen=200)

    def hit(self, bucket: str, rpm: int, *, label: str | None = None) -> float | None:
        """Count one request for *bucket*. ``None`` when it may proceed, else
        the seconds until it would be allowed."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(bucket, deque())
            while hits and hits[0] <= now - WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= rpm:
                # The limit may have been lowered below what the window holds:
                # wait until enough old hits have aged out.
                retry_after = max(hits[len(hits) - rpm] + WINDOW_SECONDS - now, 0.001)
                self.refusals.append({"ts": self._wall(), "client": label or bucket, "retry_after": retry_after})
                return retry_after
            hits.append(now)
            if now - self._last_prune > WINDOW_SECONDS:
                self._prune(now)
            return None

    def _prune(self, now: float) -> None:
        self._last_prune = now
        for bucket in [b for b, hits in self._hits.items() if not hits or hits[-1] <= now - WINDOW_SECONDS]:
            del self._hits[bucket]

    def snapshot(self, limit: InboundLimit) -> dict[str, Any]:
        now, wall = self._clock(), self._wall()
        with self._lock:
            active = sum(1 for hits in self._hits.values() if hits and hits[-1] > now - WINDOW_SECONDS)
            refusals = list(self.refusals)
        return {
            "enabled": limit.enabled,
            "requests_per_minute": limit.requests_per_minute,
            "active_clients": active,
            "refused_last_hour": sum(1 for r in refusals if r["ts"] > wall - 3600),
            "recent": [
                {"at": _iso(r["ts"]), "client": r["client"], "retry_after": round(r["retry_after"], 1)}
                for r in reversed(refusals[-10:])
            ],
        }

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self.refusals.clear()


INBOUND = InboundLimiter()
