"""Outbound limits per provider: pacing, a concurrency cap, and what happens
when the provider answers "rate limit".

A provider may enforce a per-user limit whose numbers are not published and
that lasts minutes once tripped (an Open WebUI server answers it with HTTP
400 "Rate limit exceeded"). A heavy agent run that fires dozens of calls
through OllaBridge used to trip it and fail. With limits set for that
provider (Settings → Rate limits), calls wait their turn here
instead: they are spaced to at most N per minute, at most M run at once, and
a rate-limit answer either fails fast (the old behaviour) or is retried with
backoff, honouring Retry-After, within a time budget. A cooldown keeps a
provider that just said "slow down" from being called again at once.

Settings come from ``core.rate_limits``. A provider with none is not paced
and fails fast, exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from ollabridge.addons.providers.errors import (
    ProviderError,
    ProviderRateLimited,
    is_rate_limit,
)
from ollabridge.core import rate_limits
from ollabridge.core.rate_limits import ProviderLimit

logger = logging.getLogger(__name__)

T = TypeVar("T")

# First backoff step in wait-and-retry mode when no cooldown is set; each
# further retry doubles it.
BASE_BACKOFF_SECONDS = 5.0


def _iso(ts: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


class ProviderGate:
    """Limits and recent rate-limit history for one provider.

    Runs on the event loop only (no locks): every state change happens
    between awaits.
    """

    def __init__(
        self,
        provider_id: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.provider_id = provider_id
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self.next_start = 0.0  # when the next paced request may start (monotonic)
        self.cooldown_until = 0.0  # monotonic
        self.in_flight = 0
        self.waiting = 0
        self._waiters: deque[asyncio.Future[None]] = deque()
        self.events: deque[dict[str, Any]] = deque(maxlen=50)
        self.retries = 0
        self.recovered = 0
        self.refused_in_cooldown = 0
        self.refused_queue_full = 0

    # ── state ───────────────────────────────────────────────

    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - self._clock())

    def _local_refusal(self, message: str, retry_after: float) -> ProviderRateLimited:
        exc = ProviderRateLimited(message, retry_after=max(1.0, retry_after))
        exc.local = True  # OllaBridge's own refusal: the provider was not called
        return exc

    # ── taking a turn ───────────────────────────────────────

    def _refuse_if_cooling(self, limit: ProviderLimit) -> None:
        remaining = self.cooldown_remaining()
        if remaining > 0 and limit.on_rate_limit == "fail_fast":
            self.refused_in_cooldown += 1
            raise self._local_refusal(
                f"{self.provider_id} is cooling down after a rate limit ({math.ceil(remaining)}s left)",
                remaining,
            )

    def _give_up_waiting(self, fut: asyncio.Future[None]) -> None:
        if fut.done() and not fut.cancelled():
            self._release()  # the slot arrived just as this waiter gave up
            return
        fut.cancel()
        try:
            self._waiters.remove(fut)
        except ValueError:
            pass

    async def _acquire(self, limit: ProviderLimit, deadline: float) -> None:
        cap = limit.max_concurrent
        if cap <= 0 or (self.in_flight < cap and not self._waiters):
            self.in_flight += 1
            return
        timeout = deadline - self._clock()
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            if timeout <= 0:
                raise asyncio.TimeoutError
            # _release hands its slot over by resolving the future, so
            # in_flight already counts this request when it wakes.
            await asyncio.wait_for(asyncio.shield(fut), timeout)
        except asyncio.TimeoutError:
            self._give_up_waiting(fut)
            self.refused_queue_full += 1
            raise self._local_refusal(
                f"{self.provider_id} already has {cap} request(s) running and this one waited "
                f"longer than the max wait ({limit.max_wait_seconds}s)",
                limit.max_wait_seconds,
            ) from None
        except BaseException:
            # The client went away (cancelled) while queued.
            self._give_up_waiting(fut)
            raise

    def _release(self) -> None:
        while self._waiters:
            fut = self._waiters.popleft()
            if not fut.done():
                fut.set_result(None)  # the slot passes to the next waiter
                return
        self.in_flight = max(0, self.in_flight - 1)

    async def _wait_for_start(self, limit: ProviderLimit, deadline: float) -> None:
        """Wait out pacing and any cooldown. A cooldown that starts while this
        request sleeps sends it round again, so waiters released together
        after a cooldown are spaced out instead of firing at once."""
        interval = 60.0 / limit.requests_per_minute if limit.requests_per_minute > 0 else 0.0
        while True:
            self._refuse_if_cooling(limit)
            now = self._clock()
            start = max(now, self.cooldown_until, self.next_start if interval else now)
            if start - now > deadline - now:
                self.refused_queue_full += 1
                raise self._local_refusal(
                    f"{self.provider_id}'s queue in OllaBridge would take {math.ceil(start - now)}s, "
                    f"more than the max wait ({limit.max_wait_seconds}s)",
                    start - now,
                )
            if interval:
                self.next_start = start + interval
            if start <= now:
                return
            await self._sleep(start - now)
            if self.cooldown_until <= self._clock():
                return

    @asynccontextmanager
    async def turn(self, limit: ProviderLimit, deadline: float) -> AsyncIterator[None]:
        """Hold one of the provider's request slots, started on pace."""
        self._refuse_if_cooling(limit)
        self.waiting += 1
        try:
            await self._acquire(limit, deadline)
        finally:
            self.waiting -= 1
        try:
            self.waiting += 1
            try:
                await self._wait_for_start(limit, deadline)
            finally:
                self.waiting -= 1
            yield
        finally:
            self._release()

    # ── rate-limit answers ──────────────────────────────────

    def _backoff(self, limit: ProviderLimit, exc: ProviderError, attempt: int) -> float:
        base = float(limit.cooldown_seconds) or BASE_BACKOFF_SECONDS
        return max(float(getattr(exc, "retry_after", None) or 0.0), base * (2**attempt))

    def _note(self, exc: ProviderError, outcome: str) -> None:
        self.events.append(
            {
                "ts": self._wall(),
                "status": getattr(exc, "upstream_status", None),
                "retry_after": getattr(exc, "retry_after", None),
                "message": str(exc)[:200],
                "outcome": outcome,
                "cooldown_until": self._wall() + self.cooldown_remaining() if self.cooldown_remaining() else None,
            }
        )

    async def call(self, limit: ProviderLimit, fn: Callable[[], Awaitable[T]]) -> T:
        """Run ``fn`` (one upstream call) within this provider's limits."""
        began = self._clock()
        deadline = began + limit.max_wait_seconds
        attempt = 0
        while True:
            async with self.turn(limit, deadline):
                try:
                    result = await fn()
                except ProviderError as exc:
                    if not is_rate_limit(exc) or getattr(exc, "local", False):
                        raise
                    limited = exc
                else:
                    if attempt:
                        self.recovered += 1
                    return result

            now = self._clock()
            if limit.on_rate_limit == "wait_retry":
                delay = self._backoff(limit, limited, attempt)
                self.cooldown_until = max(self.cooldown_until, now + delay)
                if now + delay <= deadline:
                    attempt += 1
                    self.retries += 1
                    self._note(limited, f"retrying in {math.ceil(delay)}s (retry {attempt})")
                    logger.warning(
                        "Provider %s is rate limiting; retry %d in %.0fs: %s",
                        self.provider_id, attempt, delay, limited,
                    )
                    continue
                self._note(limited, f"gave up after {math.ceil(now - began)}s (max wait {limit.max_wait_seconds}s)")
            else:
                if limit.cooldown_seconds:
                    hold = max(float(limit.cooldown_seconds), float(getattr(limited, "retry_after", None) or 0.0))
                    self.cooldown_until = max(self.cooldown_until, now + hold)
                self._note(limited, "failed fast")
            # Tell the client how long to back off: the cooldown when there is
            # one, else whatever the provider said.
            remaining = self.cooldown_remaining()
            if remaining:
                limited.retry_after = max(remaining, float(getattr(limited, "retry_after", None) or 0.0))
            raise limited

    # ── dashboard ───────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        wall = self._wall()
        remaining = self.cooldown_remaining()
        events = list(self.events)
        return {
            "in_flight": self.in_flight,
            "waiting": self.waiting,
            "cooling_down_until": _iso(wall + remaining) if remaining else None,
            "cooldown_remaining_s": round(remaining, 1),
            "rate_limited_last_hour": sum(1 for e in events if e["ts"] > wall - 3600),
            "retries": self.retries,
            "recovered": self.recovered,
            "refused_in_cooldown": self.refused_in_cooldown,
            "refused_queue_full": self.refused_queue_full,
            "recent": [
                {
                    "at": _iso(e["ts"]),
                    "status": e["status"],
                    "retry_after": e["retry_after"],
                    "message": e["message"],
                    "outcome": e["outcome"],
                    "cooldown_until": _iso(e["cooldown_until"]),
                }
                for e in reversed(events[-10:])
            ],
        }


_gates: dict[str, ProviderGate] = {}


def gate(provider_id: str) -> ProviderGate:
    g = _gates.get(provider_id)
    if g is None:
        g = _gates[provider_id] = ProviderGate(provider_id)
    return g


def gates() -> dict[str, ProviderGate]:
    return dict(_gates)


async def call(provider_id: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Run one upstream call to *provider_id* within its saved limits."""
    return await gate(provider_id).call(rate_limits.provider_limit(provider_id), fn)


def reset() -> None:
    """Drop every gate (tests, or a provider that was removed)."""
    _gates.clear()
