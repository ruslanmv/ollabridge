"""What one measured request, and one concurrency level, look like."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OK = "ok"
RATE_LIMITED = "rate_limited"
TIMEOUT = "timeout"
NETWORK = "network"
HTTP_ERROR = "http_error"
PROTOCOL_ERROR = "protocol_error"


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (``q`` in 0..1); ``None`` for no data."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


@dataclass
class RateHeaders:
    """A rate limit an endpoint publishes in its response headers."""

    limit: float | None = None
    remaining: float | None = None
    reset_seconds: float | None = None
    # ``None`` when the header family does not state its window.
    window_seconds: float | None = None
    family: str = ""

    @property
    def per_minute(self) -> float | None:
        if self.limit is None:
            return None
        return self.limit * 60.0 / (self.window_seconds or 60.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_seconds": _r(self.reset_seconds, 1),
            "window_seconds": self.window_seconds,
            "family": self.family,
        }


@dataclass
class Sample:
    """One operation against the endpoint (one or more HTTP requests)."""

    outcome: str
    seconds: float
    status: int | None = None
    ttft: float | None = None  # time to the first streamed token
    tokens_in: int | None = None
    tokens_out: int | None = None
    retry_after: float | None = None  # the Retry-After header, when sent
    detail: str = ""
    limits: RateHeaders | None = None
    http_requests: int = 1
    # Requests the server answered without rate limiting: what counts toward
    # its window.
    accepted_requests: int = 0
    session: str | None = None  # MCP session id, when one was issued
    data: Any = None  # decoded result, for the caller; never reported

    @property
    def ok(self) -> bool:
        return self.outcome == OK


@dataclass
class LevelResult:
    """Every sample taken at one concurrency."""

    concurrency: int
    requested: int
    samples: list[Sample] = field(default_factory=list)
    wall_seconds: float = 0.0
    stopped: str = ""  # why the level ended early, if it did
    # Requests the endpoint had accepted in the last minute when it first
    # answered "rate limit" during this level.
    accepted_before_limit: int | None = None

    @property
    def ok_samples(self) -> list[Sample]:
        return [s for s in self.samples if s.ok]

    @property
    def errors(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.samples:
            if not s.ok:
                out[s.outcome] = out.get(s.outcome, 0) + 1
        return out

    @property
    def error_rate(self) -> float:
        return (len(self.samples) - len(self.ok_samples)) / len(self.samples) if self.samples else 0.0

    @property
    def clean(self) -> bool:
        """Every request answered, none refused or failed."""
        return bool(self.samples) and len(self.ok_samples) == len(self.samples)

    @property
    def throughput(self) -> float:
        """Successful operations per second of wall time."""
        return len(self.ok_samples) / self.wall_seconds if self.wall_seconds > 0 else 0.0

    def latency(self, q: float) -> float | None:
        return percentile([s.seconds for s in self.ok_samples], q)

    def to_dict(self) -> dict[str, Any]:
        oks = [s.seconds for s in self.ok_samples]
        return {
            "concurrency": self.concurrency,
            "requests": len(self.samples),
            "ok": len(oks),
            "errors": self.errors,
            "error_rate": round(self.error_rate, 3),
            "p50_s": _r(percentile(oks, 0.5)),
            "p95_s": _r(percentile(oks, 0.95)),
            "min_s": _r(min(oks) if oks else None),
            "max_s": _r(max(oks) if oks else None),
            "per_minute": round(self.throughput * 60, 1),
            "wall_s": _r(self.wall_seconds, 2),
            "stopped": self.stopped,
            "first_error": next((s.detail for s in self.samples if not s.ok and s.detail), ""),
        }


@dataclass
class LimitProbe:
    """The result of deliberately driving an endpoint to its rate limit."""

    found: bool = False
    sent: int = 0
    seconds: float = 0.0
    accepted_in_window: int = 0
    status: int | None = None
    retry_after: float | None = None
    detail: str = ""
    recovered_after: float | None = None
    stopped: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "sent": self.sent,
            "seconds": _r(self.seconds, 1),
            "accepted_in_window": self.accepted_in_window,
            "status": self.status,
            "retry_after_s": _r(self.retry_after, 1),
            "detail": self.detail,
            "recovered_after_s": _r(self.recovered_after, 1),
            "stopped": self.stopped,
        }
