"""Free-tier model catalog — which models a provider serves for free.

Backed by ``catalog/free_models.yaml``. Two callers:

* the Sources API, to pick a source's default model when the user does not
  name one (free by default — paid usage is always an opt-in), and to flag
  each discovered model so the settings picker can badge and filter it;
* the router, to recognise a concrete model id as belonging to a provider
  whose name it does not contain (``openai/gpt-oss-20b`` is a Groq model).

Live discovery stays the source of truth for *what exists*; this catalog
only says which of those are free and which to prefer.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_FILE = Path(__file__).resolve().parent / "catalog" / "free_models.yaml"


class FreeTierSpec:
    """The free-tier rules for one provider kind."""

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
        """Is *model_id* on this provider's free tier?"""
        mid = (model_id or "").strip().lower()
        if not mid:
            return False
        if any(mid == m.lower() for m in self.models):
            return True
        if any(mid.startswith(p) for p in self.prefixes):
            return True
        return any(mid.endswith(s) for s in self.suffixes)


@lru_cache(maxsize=1)
def _catalog() -> dict[str, FreeTierSpec]:
    try:
        raw = yaml.safe_load(_CATALOG_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("free-tier catalog unreadable (%s) — treating as empty", exc)
        return {}
    kinds = raw.get("kinds") if isinstance(raw, dict) else None
    if not isinstance(kinds, dict):
        return {}
    return {str(k).lower(): FreeTierSpec(v) for k, v in kinds.items()}


def spec_for(kind: str | None) -> FreeTierSpec:
    return _catalog().get((kind or "").lower(), FreeTierSpec())


def free_models(kind: str | None) -> list[str]:
    """Known free model ids for *kind*, in preference order."""
    return list(spec_for(kind).models)


def is_free(kind: str | None, model_id: str) -> bool:
    return spec_for(kind).covers(model_id)


def preferred_default(kind: str | None, available: list[str] | None = None) -> str:
    """The free model to use by default for *kind*.

    ``available`` distinguishes three states, which is the whole point of the
    parameter: ``None`` means discovery has not run, so the catalog's first
    choice is the best guess; a list means it has, so only a model the provider
    actually still serves may be chosen — including the empty list, which is
    the honest answer "this key can reach nothing free" rather than a default
    that 400s on first use.
    """
    spec = spec_for(kind)
    if available is None:
        return spec.models[0] if spec.models else ""
    offered = {str(m).strip().lower(): str(m).strip() for m in available if m}
    for candidate in spec.models:
        hit = offered.get(candidate.lower())
        if hit:
            return hit
    for mid in available:
        if spec.covers(str(mid)):
            return str(mid)
    return ""


def annotate(kind: str | None, models: list[dict]) -> list[dict]:
    """Stamp ``free`` on each normalized model dict, in place."""
    spec = spec_for(kind)
    for m in models:
        if isinstance(m, dict):
            m["free"] = spec.covers(str(m.get("upstream_model_id") or m.get("id") or ""))
    return models
