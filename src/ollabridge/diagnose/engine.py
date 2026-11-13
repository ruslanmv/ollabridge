"""Run operations against an endpoint under a hard budget.

Three building blocks, all of which stop on their own:

* :func:`run_level` runs N operations with at most C in flight;
* :func:`sweep` raises C level by level and stops at the first rate-limit
  answer, at a level where a fifth of the requests fail, or once throughput
  falls (the endpoint is past its capacity: more load only hurts it);
* :func:`find_limit` is the one deliberate limit test, opt-in: it sends
  until the first rate-limit answer, then stops and (``measure_recovery``)
  waits for the endpoint to accept a request again.

The :class:`Budget` counts HTTP requests, not operations: an MCP call that
opens its own session costs four.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from ollabridge.diagnose.models import (
    NETWORK,
    RATE_LIMITED,
    TIMEOUT,
    LevelResult,
    LimitProbe,
    Sample,
)

Operation = Callable[[], Awaitable[Sample]]

#: A level whose error rate reaches this ends the sweep.
ERROR_RATE_STOP = 0.2
#: Throughput below this share of the best level so far ends the sweep.
THROUGHPUT_DROP_STOP = 0.8


class BudgetSpent(Exception):
    """The run used the HTTP requests or the time it was allowed."""


class Budget:
    """How much load one diagnosis may put on an endpoint."""

    def __init__(
        self,
        max_requests: int,
        max_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self._clock = clock
        self.started = clock()
        self.used = 0
        self.spent: str | None = None
        self.accepted_total = 0
        self._accepted: deque[float] = deque()

    def elapsed(self) -> float:
        return self._clock() - self.started

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - self.used)

    def take(self, n: int = 1) -> None:
        """Reserve *n* HTTP requests, or raise :class:`BudgetSpent`."""
        if self.spent is None:
            if self.elapsed() >= self.max_seconds:
                self.spent = f"time budget spent ({self.max_seconds:g} s)"
            elif self.used + n > self.max_requests:
                self.spent = f"request budget spent ({self.max_requests} HTTP requests)"
        if self.spent is not None:
            raise BudgetSpent(self.spent)
        self.used += n

    def note_accepted(self, n: int = 1) -> None:
        now = self._clock()
        self.accepted_total += max(0, n)
        self._accepted.extend([now] * max(0, n))

    def accepted_within(self, window: float = 60.0) -> int:
        """Requests the endpoint accepted in the last *window* seconds."""
        cutoff = self._clock() - window
        while self._accepted and self._accepted[0] <= cutoff:
            self._accepted.popleft()
        return len(self._accepted)


def plan_levels(levels: list[int], per_level: int, available: int, cost: int = 1) -> list[tuple[int, int]]:
    """``(concurrency, operations)`` for each level that fits in *available*
    HTTP requests. A level needs two rounds to mean anything, so it runs at
    least ``2 × concurrency`` operations."""
    plan: list[tuple[int, int]] = []
    left = available
    for c in sorted({int(x) for x in levels if int(x) > 0}):
        n = max(per_level, 2 * c)
        if n * cost > left:
            break
        plan.append((c, n))
        left -= n * cost
    return plan


async def run_level(
    op: Operation,
    *,
    concurrency: int,
    count: int,
    budget: Budget,
    stop_on_rate_limit: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> LevelResult:
    """Run *count* operations with at most *concurrency* in flight."""
    level = LevelResult(concurrency=concurrency, requested=count)
    cost = int(getattr(op, "cost", 1))
    issued = 0
    limited = False

    async def worker() -> None:
        nonlocal issued, limited
        while not level.stopped and issued < count:
            try:
                budget.take(cost)
            except BudgetSpent as exc:
                level.stopped = str(exc)
                return
            issued += 1
            sample = await op()
            level.samples.append(sample)
            budget.note_accepted(sample.accepted_requests)
            if sample.outcome == RATE_LIMITED and stop_on_rate_limit and not level.stopped:
                level.stopped = "the endpoint answered with a rate limit"
                limited = True

    started = clock()
    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    level.wall_seconds = clock() - started
    if limited:
        # Counted once every request in flight has returned, so the ones the
        # endpoint accepted just before refusing are in.
        level.accepted_before_limit = budget.accepted_within(60.0)
    return level


async def sweep(
    op: Operation,
    plan: list[tuple[int, int]],
    budget: Budget,
    *,
    on_level: Callable[[LevelResult], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[LevelResult], str]:
    """Raise the concurrency level by level; return the levels and why it ended."""
    results: list[LevelResult] = []
    best = 0.0
    reason = "every planned level ran"
    for concurrency, count in plan:
        level = await run_level(op, concurrency=concurrency, count=count, budget=budget, clock=clock)
        results.append(level)
        if on_level is not None:
            on_level(level)
        if level.stopped:
            reason = f"stopped at concurrency {concurrency}: {level.stopped}"
            break
        if level.error_rate >= ERROR_RATE_STOP:
            reason = (
                f"stopped at concurrency {concurrency}: {level.error_rate:.0%} of its requests failed"
            )
            break
        if best and level.throughput < THROUGHPUT_DROP_STOP * best:
            reason = (
                f"stopped at concurrency {concurrency}: throughput fell to "
                f"{level.throughput * 60:.0f}/min from {best * 60:.0f}/min, the endpoint is past its capacity"
            )
            break
        best = max(best, level.throughput)
    return results, reason


async def find_limit(
    op: Operation,
    *,
    concurrency: int,
    budget: Budget,
    window: float = 60.0,
    clock: Callable[[], float] = time.monotonic,
) -> LimitProbe:
    """Send until the first rate-limit answer, then stop at once.

    Ends without one when the budget is spent, when a full *window* (plus a
    margin) passed, or when the endpoint stops answering."""
    probe = LimitProbe()
    cost = int(getattr(op, "cost", 1))
    started = clock()
    deadline = started + window + 10.0
    failures = 0

    async def worker() -> None:
        nonlocal failures
        while not probe.found and not probe.stopped:
            if clock() >= deadline:
                probe.stopped = f"no rate limit met in {window + 10:g} s"
                return
            try:
                budget.take(cost)
            except BudgetSpent as exc:
                probe.stopped = str(exc)
                return
            probe.sent += 1
            sample = await op()
            budget.note_accepted(sample.accepted_requests)
            if sample.outcome == RATE_LIMITED:
                if not probe.found:
                    probe.found = True
                    probe.status = sample.status
                    probe.retry_after = sample.retry_after
                    probe.detail = sample.detail
            elif sample.outcome in (NETWORK, TIMEOUT):
                failures += 1
                if failures >= 3 and not probe.stopped:
                    probe.stopped = f"the endpoint stopped answering ({sample.detail})"

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    probe.seconds = clock() - started
    # Counted once every request in flight has returned.
    probe.accepted_in_window = budget.accepted_within(window)
    return probe


async def measure_recovery(
    op: Operation,
    probe: LimitProbe,
    budget: Budget,
    *,
    max_wait: float = 90.0,
    step: float = 15.0,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """After a rate-limit answer: how long until one request is accepted again.

    Waits the ``Retry-After`` the endpoint sent (when it sent one) before the
    first try, then tries once every *step* seconds: a few single requests,
    never a burst."""
    if not probe.found:
        return
    started = clock()
    first = min(probe.retry_after + 0.5, 120.0) if probe.retry_after else step
    wait = first
    while True:
        await sleep(wait)
        try:
            budget.take(int(getattr(op, "cost", 1)))
        except BudgetSpent:
            return
        sample = await op()
        budget.note_accepted(sample.accepted_requests)
        if sample.outcome != RATE_LIMITED:
            probe.recovered_after = clock() - started
            return
        if clock() - started >= max(max_wait, first):
            return
        wait = step
