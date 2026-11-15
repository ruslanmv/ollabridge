"""Provider usage blocks → the contract's disjoint token dimensions.

VENDORED FILE — identical in both OllaBridge repositories; see ``contract.py``.

Providers disagree on whether cached and reasoning tokens are part of their
headline counts. Everything that knows about those differences lives here, so
the rest of the system only ever sees disjoint dimensions:

    total = input + cache_read + cache_write + output + reasoning

A value a provider did not report stays ``None``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional

from .contract import Usage


def _int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _minus(total: Optional[int], part: Optional[int]) -> Optional[int]:
    if total is None:
        return None
    return max(total - (part or 0), 0)


def detect_format(raw: Mapping[str, Any]) -> str:
    """Identify a usage block by its field names."""
    if "prompt_eval_count" in raw or "eval_count" in raw:
        return "ollama"
    if "promptTokenCount" in raw or "candidatesTokenCount" in raw:
        return "gemini"
    if "input_tokens" in raw or "cache_read_input_tokens" in raw:
        return "anthropic"
    return "openai"


def _openai(raw: Mapping[str, Any]) -> Usage:
    # prompt_tokens INCLUDES cached tokens; completion_tokens INCLUDES reasoning.
    prompt = _int(raw.get("prompt_tokens"))
    completion = _int(raw.get("completion_tokens"))
    prompt_details = raw.get("prompt_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or {}
    cached = _int(prompt_details.get("cached_tokens")) if isinstance(prompt_details, Mapping) else None
    cache_write = (
        _int(prompt_details.get("cache_write_tokens")) if isinstance(prompt_details, Mapping) else None
    )
    reasoning = (
        _int(completion_details.get("reasoning_tokens"))
        if isinstance(completion_details, Mapping)
        else None
    )
    return Usage(
        input_tokens=_minus(_minus(prompt, cached), cache_write),
        cache_read_tokens=cached,
        cache_write_tokens=cache_write,
        output_tokens=_minus(completion, reasoning),
        reasoning_tokens=reasoning,
    )


def _anthropic(raw: Mapping[str, Any]) -> Usage:
    # input_tokens EXCLUDES both cache dimensions: already disjoint.
    return Usage(
        input_tokens=_int(raw.get("input_tokens")),
        cache_read_tokens=_int(raw.get("cache_read_input_tokens")),
        cache_write_tokens=_int(raw.get("cache_creation_input_tokens")),
        output_tokens=_int(raw.get("output_tokens")),
    )


def _gemini(raw: Mapping[str, Any]) -> Usage:
    # promptTokenCount INCLUDES cachedContentTokenCount; thoughts are separate
    # from candidatesTokenCount.
    prompt = _int(raw.get("promptTokenCount"))
    cached = _int(raw.get("cachedContentTokenCount"))
    return Usage(
        input_tokens=_minus(prompt, cached),
        cache_read_tokens=cached,
        output_tokens=_int(raw.get("candidatesTokenCount")),
        reasoning_tokens=_int(raw.get("thoughtsTokenCount")),
    )


def _ollama(raw: Mapping[str, Any]) -> Usage:
    return Usage(
        input_tokens=_int(raw.get("prompt_eval_count")),
        output_tokens=_int(raw.get("eval_count")),
    )


_NORMALIZERS = {
    "openai": _openai,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "ollama": _ollama,
}


def normalize_usage(raw: Optional[Mapping[str, Any]], fmt: Optional[str] = None) -> Usage:
    """Normalise a provider usage block. Missing/empty input → all unknown."""
    if not raw or not isinstance(raw, Mapping):
        return Usage()
    return _NORMALIZERS.get(fmt or detect_format(raw), _openai)(raw)


def usd_to_micro(value: Any) -> Optional[int]:
    """Exact USD → integer micro-USD. ``None`` for anything unparseable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int((amount * 1_000_000).to_integral_value())


def reported_cost_micro(raw: Optional[Mapping[str, Any]]) -> Optional[int]:
    """Charge stated inside a usage block (OpenRouter's ``usage.cost``)."""
    if not raw or not isinstance(raw, Mapping):
        return None
    return usd_to_micro(raw.get("cost"))
