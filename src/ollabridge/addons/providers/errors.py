"""Structured exceptions raised by provider adapters.

These let the router make routing decisions (retry vs. fail-over vs. abort)
based on what actually went wrong upstream, instead of inspecting raw
HTTP status codes or string-matching error messages.
"""

from __future__ import annotations

import email.utils
import re
import time

# How providers word a rate limit when they do not use HTTP 429: Open WebUI
# answers HTTP 400 {"detail": "Rate limit exceeded. Please try again later."}.
RATE_LIMIT_TEXT = re.compile(r"rate[ _-]?limit|too many requests", re.IGNORECASE)


class ProviderError(Exception):
    """Base class for provider adapter errors."""

    retryable: bool = False
    quota_related: bool = False
    upstream_status: int | None = None
    # Seconds the provider (or OllaBridge's own limits) asked the client to wait.
    retry_after: float | None = None


class ProviderUnavailable(ProviderError):
    """Network failure, DNS error, or upstream 5xx — safe to fail-over."""

    retryable = True


class ProviderAuthError(ProviderError):
    """Bad or missing credentials — do not fall over to another route on
    the same provider, and surface a clear error to the user."""

    retryable = False


class ProviderQuotaExceeded(ProviderError):
    """Provider rejected the request because the free-credit budget or
    rate-limit was exhausted (HTTP 402 / 429). Caller should mark the
    provider quota_exhausted and fail-over."""

    retryable = True
    quota_related = True


class ProviderRateLimited(ProviderQuotaExceeded):
    """The provider is rate limiting requests right now (HTTP 429, or Open
    WebUI's HTTP 400 "Rate limit exceeded"). Temporary, unlike a spent budget:
    the router does not mark the provider quota-exhausted for it, and
    ``addons.providers.pacing`` decides whether to wait and retry.

    ``local`` is set when OllaBridge refused the call itself (cooldown, or a
    queue longer than the max wait) without contacting the provider."""

    local: bool = False

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        if upstream_status is not None:
            self.upstream_status = upstream_status


def is_rate_limit(exc: BaseException) -> bool:
    """Is *exc* a provider saying "slow down"? By type, by HTTP 429, or by its
    words for an adapter that maps the answer to a generic error."""
    if isinstance(exc, ProviderRateLimited):
        return True
    if not isinstance(exc, ProviderError):
        return False
    return exc.upstream_status == 429 or bool(RATE_LIMIT_TEXT.search(str(exc)))


def parse_retry_after(value: str | None) -> float | None:
    """A ``Retry-After`` header (seconds, or an HTTP date) as seconds from now."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


class ProviderBadRequest(ProviderError):
    """Upstream 4xx that is not auth/quota — usually means the request
    is malformed for this specific model. Do not retry the same model."""

    retryable = False


class ProviderTimeout(ProviderError):
    """Upstream took too long. Safe to fail-over to another route."""

    retryable = True
