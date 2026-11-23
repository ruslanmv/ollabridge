"""Versioned price catalog and cost computation.

VENDORED FILE — identical in both OllaBridge repositories; see ``contract.py``.

Prices are data, not code. The catalog is a YAML document::

    version: "2026-11-15"
    prices:
      - provider: example
        model: "example-model-*"        # fnmatch pattern
        effective_from: "2026-01-01"    # optional, inclusive
        effective_to: null              # optional, exclusive
        per_million_micro_usd:          # integer micro-USD per 1M tokens
          input: 0
          output: 0
          cache_read: 0                 # optional → falls back to input
          cache_write: 0                # optional → falls back to input
          reasoning: 0                  # optional → falls back to output

The bundled seed ships with no prices: fill it from each provider's published
price list. Until a model has a price its estimated cost is ``None``.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from .contract import Usage

_DIMENSION_PRICE = {
    "input_tokens": ("input",),
    "cache_read_tokens": ("cache_read", "input"),
    "cache_write_tokens": ("cache_write", "input"),
    "output_tokens": ("output",),
    "reasoning_tokens": ("reasoning", "output"),
}


def _date(value: Any) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str
    prices: Mapping[str, int]
    effective_from: Optional[dt.date] = None
    effective_to: Optional[dt.date] = None

    def matches(self, provider: str, model: str, day: dt.date) -> bool:
        if self.provider != provider.lower():
            return False
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_to and day >= self.effective_to:
            return False
        return fnmatch.fnmatchcase(model.lower(), self.model.lower())


@dataclass
class PriceCatalog:
    version: str = "empty"
    entries: List[PriceEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "PriceCatalog":
        data = data or {}
        entries: List[PriceEntry] = []
        for row in data.get("prices") or []:
            prices = {
                str(k): int(v)
                for k, v in (row.get("per_million_micro_usd") or {}).items()
                if v is not None
            }
            if "input" not in prices or "output" not in prices:
                raise ValueError(
                    f"price entry for {row.get('provider')}/{row.get('model')} "
                    "needs both 'input' and 'output'"
                )
            if any(v < 0 for v in prices.values()):
                raise ValueError("prices must be non-negative")
            entries.append(
                PriceEntry(
                    provider=str(row["provider"]).lower(),
                    model=str(row["model"]),
                    prices=prices,
                    effective_from=_date(row.get("effective_from")),
                    effective_to=_date(row.get("effective_to")),
                )
            )
        return cls(version=str(data.get("version") or "empty"), entries=entries)

    @classmethod
    def from_file(cls, path: Path | str) -> "PriceCatalog":
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "prices": [
                {
                    "provider": e.provider,
                    "model": e.model,
                    "effective_from": e.effective_from.isoformat() if e.effective_from else None,
                    "effective_to": e.effective_to.isoformat() if e.effective_to else None,
                    "per_million_micro_usd": dict(e.prices),
                }
                for e in self.entries
            ],
        }

    def find(self, provider: str, model: Optional[str], day: dt.date) -> Optional[PriceEntry]:
        """First matching entry; list more specific patterns first."""
        if not model:
            return None
        for entry in self.entries:
            if entry.matches(provider, model, day):
                return entry
        return None

    def cost_micro(
        self, provider: str, model: Optional[str], usage: Usage, day: dt.date
    ) -> Tuple[Optional[int], Optional[str]]:
        """``(micro_usd, pricing_version)`` or ``(None, None)`` when unpriced.

        Integer arithmetic throughout; rounded half-up once, on the total.
        """
        if not usage.known:
            return None, None
        entry = self.find(provider, model, day)
        if entry is None:
            return None, None
        numerator = 0
        for dimension, price_keys in _DIMENSION_PRICE.items():
            tokens = getattr(usage, dimension)
            if not tokens:
                continue
            price = next((entry.prices[k] for k in price_keys if k in entry.prices), 0)
            numerator += tokens * price
        return (numerator + 500_000) // 1_000_000, self.version
