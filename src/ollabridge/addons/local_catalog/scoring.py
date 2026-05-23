"""
Local model scoring.

Different goals from cloud scoring: a local node usually has only a handful
of models, and the operator cares more about "does it work on this machine"
than "does it serve cheap tokens". The default profile follows the spec:

::

    score =
        health_score      * 0.30   # have we verified it runs?
      + latency_score     * 0.25   # how fast was the last probe?
      + model_size_score  * 0.15   # smaller is friendlier to local hardware
      + capability_score  * 0.15   # chat + tools + vision bonuses
      + recency_score     * 0.10   # recently pulled / updated bias
      + manual_pin_score  * 0.05   # admin pin boost

A ``privacy`` profile leans harder on small models (better for offline /
low-spec hardware) and ignores recency.

The output is deterministic: ties break on ``router_model_id`` ascending,
so repeated runs produce the same top-N list (important for managed alias
regeneration).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable, Iterable

from ollabridge.addons.local_catalog.schemas import (
    LocalModel,
    LocalScoringProfile,
)

logger = logging.getLogger(__name__)


# ── Weight tables ───────────────────────────────────────────


@dataclass(frozen=True)
class _Weights:
    health: float
    latency: float
    size: float
    capability: float
    recency: float
    pin: float

    def normalised(self) -> "_Weights":
        total = self.health + self.latency + self.size + self.capability + self.recency + self.pin
        if total <= 0:
            raise ValueError("Weights must sum > 0")
        f = 1.0 / total
        return _Weights(
            self.health * f, self.latency * f, self.size * f,
            self.capability * f, self.recency * f, self.pin * f,
        )


_PROFILES: dict[LocalScoringProfile, _Weights] = {
    LocalScoringProfile.DEFAULT: _Weights(
        health=0.30, latency=0.25, size=0.15,
        capability=0.15, recency=0.10, pin=0.05,
    ).normalised(),
    LocalScoringProfile.PRIVACY: _Weights(
        health=0.30, latency=0.20, size=0.30,
        capability=0.10, recency=0.00, pin=0.10,
    ).normalised(),
}


# ── Component scorers ───────────────────────────────────────


def _health_score(m: LocalModel) -> float:
    """1.0 verified, 0.5 unknown, 0.0 broken/disabled/removed."""
    status = m.setup_status.value
    return {
        "verified": 1.0,
        "auto": 0.5,
        "pulling": 0.4,
        "not_installed": 0.2,
        "broken": 0.0,
        "disabled": 0.0,
        "removed": 0.0,
    }.get(status, 0.5)


def _latency_score(m: LocalModel) -> float:
    """Observed latency in ms → 0..1. <100ms is perfect; >5s is awful."""
    lat = m.latency_observed_ms or m.avg_latency_ms
    if lat is None or lat <= 0:
        return 0.5  # neutral when unknown
    if lat < 100:
        return 1.0
    if lat < 500:
        return 0.9
    if lat < 1000:
        return 0.7
    if lat < 2000:
        return 0.5
    if lat < 5000:
        return 0.3
    return 0.1


def _size_score(m: LocalModel) -> float:
    """
    Reward sweet-spot sizes (7B–14B) on local hardware.

    Tiny models score lower because their answers are usually too weak;
    huge models score lower because they hurt latency on consumer GPUs.
    """
    p = m.parameter_count or 0
    if p == 0:
        return 0.5
    if p < 1_500:        # <1.5B
        return 0.4
    if p < 4_000:        # 1.5B–4B
        return 0.8
    if p < 12_000:       # 4B–12B  (sweet spot)
        return 1.0
    if p < 30_000:       # 12B–30B
        return 0.9
    if p < 80_000:       # 30B–80B
        return 0.5
    return 0.2           # 80B+ — rare on local


def _capability_score(m: LocalModel) -> float:
    """Count of useful capabilities normalised against the max possible."""
    cap = m.capabilities
    if not cap:
        return 0.5
    points = 0.0
    if cap.supports_chat:
        points += 1.0
    if cap.supports_tools:
        points += 0.5
    if cap.supports_vision:
        points += 0.3
    if cap.supports_structured_output:
        points += 0.2
    if cap.supports_embeddings and not cap.supports_chat:
        # Embedding-only models can't serve chat traffic — score them low so
        # they don't end up in ``local-best`` by accident.
        points = 0.1
    return min(1.0, points / 1.8)


def _recency_score(m: LocalModel, *, now: dt.datetime) -> float:
    """Newer ``modified_at`` → higher score (decays over ~90 days)."""
    ts = m.modified_at
    if ts is None:
        return 0.5
    age_days = max(0.0, (now - _ensure_utc(ts)).total_seconds() / 86400.0)
    if age_days < 7:
        return 1.0
    if age_days < 30:
        return 0.8
    if age_days < 90:
        return 0.5
    return 0.2


def _pin_score(m: LocalModel) -> float:
    return 1.0 if m.pinned else 0.0


def _ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


# ── Public API ──────────────────────────────────────────────


def score_models(
    models: Iterable[LocalModel],
    *,
    profile: LocalScoringProfile = LocalScoringProfile.DEFAULT,
    now: dt.datetime | None = None,
) -> list[tuple[LocalModel, float]]:
    """
    Return ``(model, score)`` sorted descending by score.

    Hard filters: removed/broken models stay in the catalog but get a 0
    health score, which will keep them out of the top-N unless an admin
    explicitly pins them.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    weights = _PROFILES[profile]

    scored: list[tuple[LocalModel, float]] = []
    for m in models:
        score = (
            weights.health     * _health_score(m)
            + weights.latency  * _latency_score(m)
            + weights.size     * _size_score(m)
            + weights.capability * _capability_score(m)
            + weights.recency  * _recency_score(m, now=now)
            + weights.pin      * _pin_score(m)
        )
        scored.append((m, round(score, 6)))

    scored.sort(key=lambda t: (-t[1], t[0].router_model_id))
    return scored


def pick_top_n(
    scored: list[tuple[LocalModel, float]],
    n: int = 3,
    *,
    require_chat: bool = True,
    dedupe_family: bool = False,
    key_fn: Callable[[LocalModel], str] | None = None,
) -> list[tuple[LocalModel, float]]:
    """Slice ``scored`` to the top ``n``, with light filtering."""
    out: list[tuple[LocalModel, float]] = []
    seen: set[str] = set()
    key = key_fn or (lambda m: (m.family or m.external_model_id).lower())

    for m, s in scored:
        if require_chat and not m.is_chat_capable:
            continue
        if dedupe_family:
            k = key(m)
            if k in seen:
                continue
            seen.add(k)
        out.append((m, s))
        if len(out) >= n:
            break
    return out
