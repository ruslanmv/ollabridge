"""Model defaults — which model a source should use, and which are free.

Backed by ``catalog/model_defaults.yaml``. Callers:

* the Sources API, to pick a source's default model when the user does not
  name one, and to flag each discovered model so the settings picker can
  badge and filter the free ones;
* the router, to recognise a concrete model id as belonging to a provider
  whose name it does not contain (``openai/gpt-oss-20b`` is a Groq model).

Live discovery stays the source of truth for *what exists and what this
account may use*; this catalog only ranks those and says which are free.
No provider's model id is hard-coded in application code — a retirement is
a change here, or none at all where the match is by family prefix.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_FILE = Path(__file__).resolve().parent / "catalog" / "model_defaults.yaml"


class ModelMatcher:
    """An ordered set of model-id rules: exact ids, prefixes, suffixes."""

    __slots__ = ("models", "prefixes", "suffixes")

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        raw = raw or {}
        self.models: list[str] = [str(m) for m in (raw.get("models") or [])]
        self.prefixes: tuple[str, ...] = tuple(
            str(p).lower() for p in (raw.get("prefixes") or [])
        )
        self.suffixes: tuple[str, ...] = tuple(
            str(s).lower() for s in (raw.get("suffixes") or [])
        )

    def __bool__(self) -> bool:
        return bool(self.models or self.prefixes or self.suffixes)

    def covers(self, model_id: str) -> bool:
        """Does *model_id* match any of this matcher's rules?"""
        mid = (model_id or "").strip().lower()
        if not mid:
            return False
        if any(mid == m.lower() for m in self.models):
            return True
        if any(mid.startswith(p) for p in self.prefixes):
            return True
        return any(mid.endswith(s) for s in self.suffixes)

    def rank(self, model_id: str) -> int | None:
        """Preference rank of *model_id*, lower is better; None when unmatched.

        Exact ids rank ahead of prefix matches, and a longer (more specific)
        prefix ahead of a shorter one — so ``ibm/granite-4`` wins over the
        catch-all ``ibm/granite`` without the order of the two mattering.
        """
        mid = (model_id or "").strip().lower()
        if not mid:
            return None
        for i, m in enumerate(self.models):
            if mid == m.lower():
                return i
        matches = [
            len(self.models) + i
            for i, p in enumerate(self.prefixes)
            if mid.startswith(p)
        ]
        if matches:
            return min(matches)
        for i, s in enumerate(self.suffixes):
            if mid.endswith(s):
                return len(self.models) + len(self.prefixes) + i
        return None


class KindSpec:
    """The free-tier and default-preference rules for one provider kind."""

    __slots__ = ("free", "preferred")

    def __init__(self, raw: dict[str, Any] | None = None) -> None:
        raw = raw or {}
        self.free = ModelMatcher(raw.get("free"))
        # A provider with no free tier (watsonx) ranks its default on its own
        # terms; everywhere else the free models *are* the preferred ones.
        self.preferred = ModelMatcher(raw.get("preferred")) or self.free


@lru_cache(maxsize=1)
def _catalog() -> dict[str, KindSpec]:
    try:
        raw = yaml.safe_load(_CATALOG_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "model defaults catalog unreadable (%s) — treating as empty", exc
        )
        return {}
    kinds = raw.get("kinds") if isinstance(raw, dict) else None
    if not isinstance(kinds, dict):
        return {}
    return {str(k).lower(): KindSpec(v) for k, v in kinds.items()}


def spec_for(kind: str | None) -> KindSpec:
    return _catalog().get((kind or "").lower(), KindSpec())


def free_models(kind: str | None) -> list[str]:
    """Known free model ids for *kind*, in preference order."""
    return list(spec_for(kind).free.models)


def suggested_models(kind: str | None) -> list[str]:
    """Model ids to suggest for *kind* before anything has been discovered.

    The preferred exact ids, which for a free-tier provider are its free
    models. A kind that ranks only by family prefix has none to suggest —
    its real answer comes from the provider's live catalog.
    """
    return list(spec_for(kind).preferred.models)


def is_free(kind: str | None, model_id: str) -> bool:
    return spec_for(kind).free.covers(model_id)


def preferred_default(kind: str | None, available: list[str] | None = None) -> str:
    """The model *kind* should default to, "" when none is known.

    ``available`` distinguishes three states, which is the whole point of
    the parameter: ``None`` means discovery has not run, so the catalog's
    top choice is the best guess; a list means it has, so only a model the
    provider actually offers this account may be chosen — including the
    empty list, which is the honest answer "nothing preferred is reachable"
    rather than a default that fails on first use.
    """
    pref = spec_for(kind).preferred
    if available is None:
        return pref.models[0] if pref.models else ""
    ranked = [
        (rank, str(mid).strip())
        for mid in available
        if mid and (rank := pref.rank(str(mid))) is not None
    ]
    if not ranked:
        return ""
    # Ties (two ids matching the same prefix) resolve by id, so the choice is
    # stable across calls rather than dependent on the provider's ordering.
    return min(ranked, key=lambda r: (r[0], r[1]))[1]


def annotate(kind: str | None, models: list[dict]) -> list[dict]:
    """Stamp ``free`` on each normalized model dict, in place."""
    spec = spec_for(kind)
    for m in models:
        if isinstance(m, dict):
            m["free"] = spec.free.covers(
                str(m.get("upstream_model_id") or m.get("id") or "")
            )
    return models
