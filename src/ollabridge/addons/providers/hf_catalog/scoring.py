"""Deterministic scoring for Hugging Face inference-model candidates.

Two profiles ship by default:

- ``default``  — balanced (perf + caps + cost + popularity).
- ``free_lab`` — leans on latency and cost for free-tier exploration.

Score components are normalised to ``[0.0, 1.0]`` via min/max scaling over
the input batch, so the absolute scale of HF metrics doesn't matter. Missing
values fall back to 0.5 (neutral) so a row with one gap isn't unfairly buried.

The output is stable: ties break on ``router_model_id`` so two runs with the
same input produce identical top-N lists — required by the alias rewrite step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFInferenceModelRow,
    HFTask,
    ScoringProfile,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Weights:
    throughput: float
    latency: float
    context: float
    cost: float
    tools: float
    structured: float
    popularity: float

    def normalised(self) -> "_Weights":
        total = (
            self.throughput + self.latency + self.context + self.cost
            + self.tools + self.structured + self.popularity
        )
        if total <= 0:
            raise ValueError("Weights must sum to > 0")
        f = 1.0 / total
        return _Weights(
            self.throughput * f, self.latency * f, self.context * f, self.cost * f,
            self.tools * f, self.structured * f, self.popularity * f,
        )


_PROFILES: dict[ScoringProfile, _Weights] = {
    ScoringProfile.DEFAULT: _Weights(
        throughput=0.25, latency=0.25, context=0.15,
        cost=0.15, tools=0.10, structured=0.05, popularity=0.05,
    ).normalised(),
    ScoringProfile.FREE_LAB: _Weights(
        throughput=0.25, latency=0.25, context=0.10,
        cost=0.20, tools=0.15, structured=0.05, popularity=0.00,
    ).normalised(),
}


def _minmax(values: Iterable[float | None]) -> tuple[float, float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return (0.0, 0.0)
    return (min(nums), max(nums))


def _scale(value: float | None, lo: float, hi: float, *, higher_is_better: bool) -> float:
    if value is None:
        return 0.5
    if hi <= lo:
        return 0.5
    norm = (value - lo) / (hi - lo)
    norm = max(0.0, min(1.0, norm))
    return norm if higher_is_better else (1.0 - norm)


def score_rows(
    rows: list[HFInferenceModelRow],
    profile: ScoringProfile = ScoringProfile.FREE_LAB,
) -> list[tuple[HFInferenceModelRow, float]]:
    """Return ``(row, score)`` pairs sorted descending by score.

    Hard filters applied before scoring:

    - Task must be chat-completion or VLM (embedding/image models can't
      serve chat traffic).
    - Row must have at least one of latency, throughput, or trending score
      — otherwise we'd be ranking on pure noise.
    """
    weights = _PROFILES[profile]

    eligible: list[HFInferenceModelRow] = []
    for r in rows:
        if r.task not in (HFTask.CHAT_COMPLETION, HFTask.VLM):
            continue
        if r.latency_s is None and r.throughput_tps is None and r.trending_score is None:
            continue
        eligible.append(r)

    if not eligible:
        return []

    lat_lo, lat_hi = _minmax(r.latency_s for r in eligible)
    tps_lo, tps_hi = _minmax(r.throughput_tps for r in eligible)
    ctx_lo, ctx_hi = _minmax(r.context_window for r in eligible)
    in_lo, in_hi = _minmax(r.input_price_per_1m for r in eligible)
    out_lo, out_hi = _minmax(r.output_price_per_1m for r in eligible)
    pop_lo, pop_hi = _minmax(
        (r.trending_score if r.trending_score is not None else r.likes)
        for r in eligible
    )

    def _cost_score(r: HFInferenceModelRow) -> float:
        scores = []
        if r.input_price_per_1m is not None:
            scores.append(_scale(r.input_price_per_1m, in_lo, in_hi, higher_is_better=False))
        if r.output_price_per_1m is not None:
            scores.append(_scale(r.output_price_per_1m, out_lo, out_hi, higher_is_better=False))
        return sum(scores) / len(scores) if scores else 0.5

    def _popularity(r: HFInferenceModelRow) -> float:
        v = r.trending_score if r.trending_score is not None else r.likes
        return _scale(v, pop_lo, pop_hi, higher_is_better=True)

    scored: list[tuple[HFInferenceModelRow, float]] = []
    for r in eligible:
        score = (
            weights.throughput * _scale(r.throughput_tps, tps_lo, tps_hi, higher_is_better=True)
            + weights.latency  * _scale(r.latency_s, lat_lo, lat_hi, higher_is_better=False)
            + weights.context  * _scale(r.context_window, ctx_lo, ctx_hi, higher_is_better=True)
            + weights.cost     * _cost_score(r)
            + weights.tools    * (1.0 if r.supports_tools else 0.0)
            + weights.structured * (1.0 if r.supports_structured_output else 0.0)
            + weights.popularity * _popularity(r)
        )
        scored.append((r, score))

    scored.sort(key=lambda t: (-t[1], t[0].router_model_id))
    return scored


def pick_top_n(
    scored: list[tuple[HFInferenceModelRow, float]],
    n: int = 5,
    *,
    dedupe_by_model: bool = True,
    key_fn: Callable[[HFInferenceModelRow], str] | None = None,
) -> list[tuple[HFInferenceModelRow, float]]:
    """Slice the scored list to the top N, optionally keeping at most one
    upstream provider per ``model_id``."""
    if not scored:
        return []
    key = key_fn or (lambda r: r.model_id)

    out: list[tuple[HFInferenceModelRow, float]] = []
    seen: set[str] = set()
    for row, s in scored:
        if dedupe_by_model:
            k = key(row)
            if k in seen:
                continue
            seen.add(k)
        out.append((row, s))
        if len(out) >= n:
            break
    return out
