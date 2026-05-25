"""Structured exceptions raised by provider adapters.

These let the router make routing decisions (retry vs. fail-over vs. abort)
based on what actually went wrong upstream, instead of inspecting raw
HTTP status codes or string-matching error messages.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for provider adapter errors."""

    retryable: bool = False
    quota_related: bool = False
    upstream_status: int | None = None


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


class ProviderBadRequest(ProviderError):
    """Upstream 4xx that is not auth/quota — usually means the request
    is malformed for this specific model. Do not retry the same model."""

    retryable = False


class ProviderTimeout(ProviderError):
    """Upstream took too long. Safe to fail-over to another route."""

    retryable = True
