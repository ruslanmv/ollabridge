"""
Normalize Ollama ``/api/tags`` rows into ``LocalModelRow``.

We extract three things the scorer relies on:

- **family**       — base architecture (llama, qwen, gemma, mistral, ...). Pulled
                     from ``/api/show`` ``details.family`` when present, otherwise
                     inferred from the leading segment of the tag.
- **parameter size** — both the raw label (``7b``, ``14b``) and a numeric form
                     in millions, so models can be ranked / bucketed.
- **quantization**  — from ``details.quantization_level`` or the tag suffix.

Heuristics live here, not in the scorer — that way scoring stays pure and
testable while parsing logic absorbs the messiness of real-world tag names.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Optional

from ollabridge.addons.local_catalog.schemas import (
    LocalModelRow,
    LocalRuntime,
    ModelCapabilities,
)

logger = logging.getLogger(__name__)


# ── Capability dictionaries ─────────────────────────────────


# Families with strong tool-call support. Conservative — only well-known cases.
_TOOL_FAMILIES = {
    "llama", "llama3", "llama3.1", "llama3.2", "llama3.3",
    "qwen", "qwen2", "qwen2.5", "qwen3",
    "mistral", "mixtral",
    "command-r", "command-r-plus",
    "firefunction",
}

# Families typically used for embeddings (won't take a chat call gracefully).
_EMBEDDING_FAMILIES = {
    "nomic-embed-text", "mxbai-embed-large", "snowflake-arctic-embed", "bge",
    "all-minilm",
}

# Vision-capable families (multimodal chat).
_VISION_FAMILIES = {
    "llava", "bakllava", "minicpm-v", "moondream", "llama3.2-vision", "qwen-vl",
}

# Param-size suffixes we recognise (``:7b``, ``-7b-instruct``, ``-q4_K_M``).
_PARAM_RE = re.compile(r"(?:^|[-:_])(\d+(?:\.\d+)?)\s*([bm])\b", re.IGNORECASE)
_QUANT_RE = re.compile(
    r"\b(q\d(?:_[KMS\d]+)?|fp16|f16|fp32|f32|bf16|int8|int4)\b",
    re.IGNORECASE,
)


# ── Public API ──────────────────────────────────────────────


def normalize(
    node_id: str,
    tags: list[dict[str, Any]],
    *,
    runtime: LocalRuntime = LocalRuntime.OLLAMA,
    show_details: Optional[dict[str, dict[str, Any]]] = None,
) -> list[LocalModelRow]:
    """
    Convert a runtime listing into ``LocalModelRow`` objects.

    Arguments:
        node_id: stable identifier of the node we're cataloging.
        tags: raw entries from ``/api/tags``.
        runtime: which runtime produced the listing.
        show_details: optional ``{model_name: /api/show payload}`` mapping
            used to enrich rows beyond what /api/tags exposes.
    """
    show_details = show_details or {}
    rows: list[LocalModelRow] = []

    for entry in tags:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not name:
            continue

        details = entry.get("details") or {}
        show = show_details.get(name) or {}
        show_details_payload = show.get("details") or {}
        # ``/api/show`` is authoritative when present; ``/api/tags`` details fill gaps.
        merged_details: dict[str, Any] = {**details, **show_details_payload}

        family = _family(name, merged_details)
        param_label, param_count = _param_size(name, merged_details)
        quantization = _quant(name, merged_details)
        context_window = _context_window(merged_details, show)
        capabilities = _capabilities(family, merged_details, show)

        rows.append(LocalModelRow(
            node_id=node_id,
            runtime=runtime,
            external_model_id=name,
            router_model_id=f"{node_id}:{name}",
            display_name=_display_name(name, family, param_label),
            family=family,
            parameter_size=param_label,
            parameter_count=param_count,
            quantization=quantization,
            context_window=context_window,
            disk_size_bytes=_int(entry.get("size")),
            modified_at=_parse_time(entry.get("modified_at")),
            capabilities=capabilities,
            raw={"tag": _slim_tag(entry), "show": _slim_show(show)},
        ))

    logger.debug("local parser normalised %d rows for node=%s", len(rows), node_id)
    return rows


# ── Field extractors ────────────────────────────────────────


def _family(name: str, details: dict[str, Any]) -> Optional[str]:
    fam = details.get("family") or details.get("families")
    if isinstance(fam, list) and fam:
        fam = fam[0]
    if isinstance(fam, str) and fam:
        return fam.lower()
    # Fallback: take the part before ``:`` and strip any size suffix.
    head = name.split(":", 1)[0].lower()
    head = head.split("/")[-1]
    head = re.sub(r"[-_]?\d+(?:\.\d+)?[bm]\b.*$", "", head)
    return head or None


def _param_size(name: str, details: dict[str, Any]) -> tuple[Optional[str], Optional[int]]:
    raw = details.get("parameter_size") or details.get("parameters")
    if isinstance(raw, str):
        m = _PARAM_RE.search(raw)
        if m:
            return m.group(0).lstrip("-:_").lower(), _to_millions(float(m.group(1)), m.group(2))

    # Fallback: scan the tag name itself.
    m = _PARAM_RE.search(name)
    if m:
        return m.group(0).lstrip("-:_").lower(), _to_millions(float(m.group(1)), m.group(2))
    return None, None


def _to_millions(value: float, unit: str) -> int:
    unit = unit.lower()
    if unit == "b":
        return int(round(value * 1000))    # billions → millions
    if unit == "m":
        return int(round(value))
    return int(round(value))


def _quant(name: str, details: dict[str, Any]) -> Optional[str]:
    q = details.get("quantization_level") or details.get("quantization")
    if isinstance(q, str) and q:
        return q
    m = _QUANT_RE.search(name)
    return m.group(1).lower() if m else None


def _context_window(details: dict[str, Any], show: dict[str, Any]) -> Optional[int]:
    """Look in a few common places for context length."""
    # /api/show returns ``parameters`` as a free-form string sometimes.
    params = show.get("parameters")
    if isinstance(params, str):
        m = re.search(r"num_ctx\s+(\d+)", params)
        if m:
            return int(m.group(1))
    return _int(details.get("context_length")) or _int(details.get("num_ctx"))


def _capabilities(
    family: Optional[str], details: dict[str, Any], show: dict[str, Any],
) -> ModelCapabilities:
    fam = (family or "").lower()
    is_embed = fam in _EMBEDDING_FAMILIES or "embed" in fam
    is_vision = fam in _VISION_FAMILIES or _bool_marker(details, "vision") or _bool_marker(show, "vision")
    # Tool support: trust ``/api/show`` template hints when available.
    tmpl = (show.get("template") or "").lower() if isinstance(show.get("template"), str) else ""
    has_tools_template = "tool" in tmpl or "function" in tmpl
    supports_tools = fam in _TOOL_FAMILIES or has_tools_template

    return ModelCapabilities(
        supports_chat=not is_embed,
        supports_embeddings=is_embed,
        supports_tools=supports_tools and not is_embed,
        supports_vision=is_vision,
        supports_structured_output=False,   # not yet exposed by Ollama
        supports_streaming=not is_embed,
    )


def _bool_marker(d: dict[str, Any], key: str) -> bool:
    v = d.get(key)
    return bool(v) if isinstance(v, bool) else False


def _display_name(name: str, family: Optional[str], param: Optional[str]) -> str:
    pieces = []
    if family:
        pieces.append(family.capitalize())
    if param:
        pieces.append(param.upper())
    if not pieces:
        return name
    return " ".join(pieces)


def _int(value: Any) -> Optional[int]:
    try:
        i = int(value)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str):
        return None
    # Ollama returns ISO-8601 with nanoseconds; trim to microseconds.
    cleaned = value.replace("Z", "+00:00")
    cleaned = re.sub(r"(\.\d{6})\d+", r"\1", cleaned)
    try:
        return dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _slim_tag(entry: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "model", "size", "digest", "modified_at", "details")
    return {k: entry.get(k) for k in keys if k in entry}


def _slim_show(show: dict[str, Any]) -> dict[str, Any]:
    """Drop heavy fields we never read so YAML stays manageable."""
    if not isinstance(show, dict):
        return {}
    keys = ("details", "parameters", "license", "template")
    out = {k: show.get(k) for k in keys if k in show}
    # ``template`` and ``parameters`` can be huge — cap them.
    if isinstance(out.get("template"), str) and len(out["template"]) > 500:
        out["template"] = out["template"][:500] + "…"
    if isinstance(out.get("parameters"), str) and len(out["parameters"]) > 500:
        out["parameters"] = out["parameters"][:500] + "…"
    return out
