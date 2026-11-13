"""Read the rate limit an endpoint publishes, without ever hitting it.

Many gateways state their limit on every response. Three header families are
in use, and they disagree on names and units:

* OpenAI style: ``x-ratelimit-limit-requests``, ``-remaining-requests``,
  ``-reset-requests`` (a duration such as ``6m0s``). The window is not in the
  header: most providers mean a minute, some a day.
* The older de-facto trio: ``x-ratelimit-limit`` / ``-remaining`` /
  ``-reset`` (seconds, or an epoch time).
* IETF ``RateLimit-*``: ``RateLimit-Limit``, ``RateLimit-Remaining``,
  ``RateLimit-Reset`` and ``RateLimit-Policy: 60;w=60``, whose ``w`` is the
  window in seconds; the newer draft writes ``"name";q=60;w=60``.

``window_seconds`` stays ``None`` when the family does not say, and the
report then states that a minute was assumed.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping

from ollabridge.addons.providers.errors import RATE_LIMIT_TEXT, parse_retry_after
from ollabridge.diagnose.models import RateHeaders

__all__ = ["RATE_LIMIT_TEXT", "is_rate_limit", "parse_duration", "rate_headers", "retry_after"]

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_duration(value: str | None) -> float | None:
    """``"6m0s"``, ``"250ms"``, ``"1h2m3s"`` or a plain number of seconds."""
    raw = (value or "").strip().lower()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(raw)
    if not parts or "".join(n + u for n, u in parts) != raw:
        return None
    scale = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    return sum(float(n) * scale[u] for n, u in parts)


def _first_number(value: str | None) -> float | None:
    m = _NUMBER.search(value or "")
    return float(m.group(0)) if m else None


def _param(value: str | None, name: str) -> float | None:
    m = re.search(rf"(?:^|[;,\s]){name}=(\d+(?:\.\d+)?)", value or "")
    return float(m.group(1)) if m else None


def _reset(value: str | None) -> float | None:
    """Seconds until the window resets: a delta, a duration, or an epoch time."""
    seconds = parse_duration(value)
    if seconds is None:
        return None
    if seconds > 1_000_000_000:  # an epoch timestamp
        return max(0.0, seconds - time.time())
    return seconds


def rate_headers(headers: Mapping[str, str] | None) -> RateHeaders | None:
    """The published request limit in *headers*, or ``None`` when there is none."""
    if not headers:
        return None
    h = {str(k).lower(): str(v) for k, v in headers.items()}

    # IETF RateLimit-* (both drafts).
    policy = h.get("ratelimit-policy")
    if "ratelimit-limit" in h or "ratelimit" in h or policy:
        combined = h.get("ratelimit")
        limit = _first_number(h.get("ratelimit-limit")) if "ratelimit-limit" in h else None
        if limit is None:
            limit = _param(policy, "q") or _first_number(policy)
        remaining = _first_number(h.get("ratelimit-remaining")) if "ratelimit-remaining" in h else _param(combined, "r")
        reset = _reset(h.get("ratelimit-reset")) if "ratelimit-reset" in h else _param(combined, "t")
        window = _param(policy, "w") or _param(h.get("ratelimit-limit"), "w")
        if limit is not None:
            return RateHeaders(limit, remaining, reset, window, "RateLimit-*")

    # OpenAI style: requests and tokens are limited apart; requests matter here.
    if "x-ratelimit-limit-requests" in h:
        return RateHeaders(
            _first_number(h.get("x-ratelimit-limit-requests")),
            _first_number(h.get("x-ratelimit-remaining-requests")),
            _reset(h.get("x-ratelimit-reset-requests")),
            None,
            "x-ratelimit-*-requests",
        )

    if "x-ratelimit-limit" in h:
        raw = h.get("x-ratelimit-limit")
        return RateHeaders(
            _first_number(raw),
            _first_number(h.get("x-ratelimit-remaining")),
            _reset(h.get("x-ratelimit-reset")),
            _param(raw, "w"),
            "x-ratelimit-*",
        )
    return None


def retry_after(headers: Mapping[str, str] | None) -> float | None:
    if not headers:
        return None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            return parse_retry_after(str(value))
    return None


def is_rate_limit(status: int, body: str | None) -> bool:
    """HTTP 429, or another status whose body says so (an Open WebUI server
    answers HTTP 400 ``{"detail": "Rate limit exceeded..."}``)."""
    if status == 429:
        return True
    return status in (400, 403, 503) and bool(RATE_LIMIT_TEXT.search(body or ""))
