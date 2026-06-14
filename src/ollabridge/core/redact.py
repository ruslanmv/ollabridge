"""Secret redaction helpers.

Used by the CLI, doctor checks, tracing, and logging so that provider API
keys, device tokens, and pairing tokens never appear in full in any output.

Design rules:
- ``redact_secret`` keeps a short, non-reversible hint (first 4 chars) so a
  user can tell *which* key is configured without revealing it.
- ``redact_text`` scrubs known token shapes from free-form text (exception
  messages, upstream error bodies) before it is logged or displayed.
- ``RedactionFilter`` can be attached to any ``logging.Logger``/handler to
  scrub records defensively.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Known credential shapes across OllaBridge and supported providers.
# Order matters: more specific prefixes first.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # OllaBridge: local API keys, device tokens, bootstrap tokens, pairing tokens
    re.compile(r"\bsk-ollabridge-[A-Za-z0-9_\-]+"),
    re.compile(r"\bdvt_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bobt_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bmtx_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bob_[A-Za-z0-9_\-]{16,}"),
    # Providers
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"),  # Anthropic
    re.compile(r"\bsk-or-[A-Za-z0-9_\-]{8,}"),  # OpenRouter
    re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{8,}"),  # OpenAI project keys
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),  # OpenAI / generic sk-
    re.compile(r"\bhf_[A-Za-z0-9]{8,}"),  # Hugging Face
    re.compile(r"\bgsk_[A-Za-z0-9]{8,}"),  # Groq
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),  # Google API keys
    re.compile(r"\bAKIA[0-9A-Z]{16}"),  # AWS access key id
    # Header style: Authorization: Bearer <token> / X-API-Key: <token>
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)(x-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_\-\.=]{8,}"),
]

_REPLACEMENT = "[REDACTED]"


def redact_secret(value: str | None, *, hint_chars: int = 4) -> str:
    """Redact a single known-secret value, keeping a short prefix hint.

    >>> redact_secret("sk-ant-abc123def456")
    'sk-a…(redacted)'
    """
    if not value:
        return "(not set)"
    value = str(value)
    if len(value) <= hint_chars:
        return "…(redacted)"
    return f"{value[:hint_chars]}…(redacted)"


def redact_text(text: str | None) -> str:
    """Scrub anything that looks like a credential from free-form text."""
    if not text:
        return "" if text is None else text
    out = str(text)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            out = pattern.sub(lambda m: m.group(1) + _REPLACEMENT, out)
        else:
            out = pattern.sub(_REPLACEMENT, out)
    return out


def redact_mapping(
    data: dict[str, Any], *, extra_keys: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Return a copy of *data* with secret-looking keys redacted (recursive)."""
    sensitive = (
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "authorization",
        "device_token",
        "credential",
        "access_key",
    ) + tuple(k.lower() for k in extra_keys)

    def _walk(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: _walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, key) for v in value]
        if key and isinstance(value, str) and any(s in key.lower() for s in sensitive):
            return redact_secret(value)
        if isinstance(value, str):
            return redact_text(value)
        return value

    return _walk(dict(data))


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs credential shapes from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_text(str(record.msg))
            if record.args:
                record.args = tuple(
                    redact_text(a) if isinstance(a, str) else a for a in record.args
                )
        except Exception:
            # Never let redaction break logging itself.
            pass
        return True


def install_redaction_filter(logger: logging.Logger | None = None) -> RedactionFilter:
    """Attach a :class:`RedactionFilter` to *logger* (root by default)."""
    target = logger or logging.getLogger()
    filt = RedactionFilter()
    target.addFilter(filt)
    return filt
