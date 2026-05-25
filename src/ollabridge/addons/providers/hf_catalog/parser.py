"""Normalize raw Hugging Face Hub model entries into :class:`HFInferenceModelRow`.

The Hub's ``inferenceProviderMapping`` is the source of truth for the
``model:provider`` pairs the HF Router accepts. Each Hub model can carry
several mappings (groq, together, novita, ...) — we expand one entry into
N rows and drop any mapping whose status is not ``live``/``staging``.

The parser is intentionally tolerant of HF schema swings: pricing,
context length, latency, throughput, and capability flags are read from
the 2026-05 nested locations first, with the legacy flat locations as
fallback.
"""

from __future__ import annotations

import logging
from typing import Any

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFInferenceModelRow,
    HFTask,
)

logger = logging.getLogger(__name__)


_PIPELINE_TO_TASK: dict[str, HFTask] = {
    "text-generation": HFTask.CHAT_COMPLETION,
    "conversational": HFTask.CHAT_COMPLETION,
    "image-text-to-text": HFTask.VLM,
    "feature-extraction": HFTask.EMBEDDING,
    "text-to-image": HFTask.IMAGE,
    "text-to-video": HFTask.VIDEO,
}

_ACCEPTED_STATUSES = {"live", "staging"}


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def _i(value: Any) -> int | None:
    if value is None:
        return None
    try:
        i = int(value)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


def _bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _dig(d: Any, *path: str) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _task_from(pipeline: str | None, mapping_task: str | None) -> HFTask:
    for hint in (mapping_task, pipeline):
        if not hint:
            continue
        mapped = _PIPELINE_TO_TASK.get(hint)
        if mapped:
            return mapped
    return HFTask.OTHER


def _capabilities(mapping: dict[str, Any], top_level: dict[str, Any]) -> tuple[bool, bool]:
    supports_tools = (
        _bool(_dig(mapping, "features", "toolCalling"))
        or _bool(mapping.get("supportsTools"))
        or _bool(mapping.get("supports_tools"))
        or "tool-use" in (top_level.get("tags") or [])
    )
    supports_structured = (
        _bool(_dig(mapping, "features", "structuredOutput"))
        or _bool(mapping.get("supportsStructuredOutput"))
        or _bool(mapping.get("supports_structured_output"))
        or _bool(mapping.get("supportsResponseFormat"))
    )
    return supports_tools, supports_structured


def _get_context_window(entry: dict[str, Any]) -> Any:
    cfg = entry.get("config") or {}
    for key in ("max_position_embeddings", "n_positions", "context_length"):
        v = cfg.get(key)
        if v:
            return v
    card = entry.get("cardData") or {}
    return card.get("context_window")


def _slim(entry: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "id", "modelId", "pipeline_tag", "tags", "likes", "downloads",
        "trendingScore", "library_name", "private", "gated",
    )
    return {k: entry.get(k) for k in keep_keys if k in entry}


def normalize(raw_models: list[dict[str, Any]]) -> list[HFInferenceModelRow]:
    """Expand raw Hub entries into per-(model, provider) normalized rows."""
    rows: list[HFInferenceModelRow] = []

    for entry in raw_models:
        model_id = entry.get("id") or entry.get("modelId")
        if not model_id:
            continue

        mappings = entry.get("inferenceProviderMapping") or []
        if not mappings:
            continue

        pipeline_tag = entry.get("pipeline_tag")
        trending = _f(entry.get("trendingScore"))
        likes = _i(entry.get("likes"))
        downloads = _i(entry.get("downloads"))
        ctx_top = _i(_get_context_window(entry))
        labels = list(entry.get("tags") or [])

        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue

            status = (mapping.get("status") or "").lower()
            if status and status not in _ACCEPTED_STATUSES:
                continue

            hf_provider = (mapping.get("provider") or mapping.get("name") or "").strip()
            if not hf_provider:
                continue

            external_model_id = mapping.get("providerId") or model_id
            router_model_id = f"{model_id}:{hf_provider}"

            in_price = _f(
                _dig(mapping, "providerDetails", "pricing", "input")
                or _dig(mapping, "pricing", "input")
                or mapping.get("inputPrice")
            )
            out_price = _f(
                _dig(mapping, "providerDetails", "pricing", "output")
                or _dig(mapping, "pricing", "output")
                or mapping.get("outputPrice")
            )
            context_window = (
                _i(_dig(mapping, "providerDetails", "context_length"))
                or _i(mapping.get("contextWindow"))
                or ctx_top
            )
            latency_ms = (
                _f(_dig(mapping, "performance", "firstTokenLatencyMs"))
                or _f(_dig(mapping, "performance", "requestLatencyMs"))
            )
            latency = (latency_ms / 1000.0) if latency_ms is not None else _f(mapping.get("latency"))
            throughput = (
                _f(_dig(mapping, "performance", "tokensPerSecond"))
                or _f(mapping.get("tokensPerSecond"))
                or _f(mapping.get("throughput"))
            )
            supports_tools, supports_structured = _capabilities(mapping, entry)
            task = _task_from(pipeline_tag, mapping.get("task"))

            try:
                rows.append(HFInferenceModelRow(
                    model_id=external_model_id,
                    hf_provider=hf_provider,
                    router_model_id=router_model_id,
                    task=task,
                    input_price_per_1m=in_price,
                    output_price_per_1m=out_price,
                    context_window=context_window,
                    latency_s=latency,
                    throughput_tps=throughput,
                    supports_tools=supports_tools,
                    supports_structured_output=supports_structured,
                    trending_score=trending,
                    likes=likes,
                    downloads=downloads,
                    labels=labels,
                    raw={"entry": _slim(entry), "mapping": mapping},
                ))
            except ValueError as exc:
                logger.debug("Skipping invalid HF row %s:%s — %s", model_id, hf_provider, exc)

    logger.info("HF parser: produced %d (model, provider) rows", len(rows))
    return rows
