"""Display currency.

Providers charge in US dollars, so the ledger always stores integer micro-USD
— converting stored amounts would bake a moving exchange rate into history.
Conversion happens only when a figure is shown, at one explicit rate that the
user sets. The rate is never fetched or guessed: a non-USD currency without a
rate is refused.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from ollabridge.core.settings import settings

from .store import UsageStore, get_usage_store

_KEY = "display_currency"
_CODE = re.compile(r"^[A-Z]{3}$")


def _valid(code: str, rate: float) -> None:
    if not _CODE.match(code):
        raise ValueError("currency must be a 3-letter ISO 4217 code, e.g. EUR")
    if not (0 < rate < 1_000_000):
        raise ValueError("rate must be a positive number: units of the currency per 1 USD")
    if code == "USD" and rate != 1:
        raise ValueError("USD is the ledger currency; its rate is always 1")


def get_display_currency(store: Optional[UsageStore] = None) -> Dict[str, Any]:
    """``{"code", "usd_rate", "source"}`` — a saved choice wins over the env."""
    store = store or get_usage_store()
    saved = store.get_setting(_KEY)
    if saved:
        try:
            data = json.loads(saved)
            code, rate = str(data["code"]), float(data["usd_rate"])
            _valid(code, rate)
            return {"code": code, "usd_rate": rate, "source": "saved"}
        except (ValueError, KeyError, TypeError):
            pass
    code, rate = settings.USAGE_DISPLAY_CURRENCY.upper(), float(settings.USAGE_DISPLAY_RATE)
    try:
        _valid(code, rate)
    except ValueError:
        return {"code": "USD", "usd_rate": 1.0, "source": "default"}
    return {"code": code, "usd_rate": rate, "source": "default" if code == "USD" else "environment"}


def set_display_currency(code: str, usd_rate: Optional[float], store: Optional[UsageStore] = None) -> Dict[str, Any]:
    """Save the display currency. ``usd_rate`` = units of ``code`` per 1 USD."""
    store = store or get_usage_store()
    code = code.strip().upper()
    if code == "USD":
        usd_rate = 1.0
    if usd_rate is None:
        raise ValueError(f"a rate is required for {code}: how many {code} is 1 USD?")
    _valid(code, float(usd_rate))
    store.set_setting(_KEY, json.dumps({"code": code, "usd_rate": float(usd_rate)}))
    return get_display_currency(store)


def format_money(micro_usd: Optional[int], currency: Dict[str, Any]) -> str:
    """Micro-USD as a figure in the display currency (for the CLI)."""
    if micro_usd is None:
        return "—"
    amount = micro_usd / 1_000_000 * currency["usd_rate"]
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency["code"])
    digits = 4 if amount and abs(amount) < 0.01 else 2
    figure = f"{amount:,.{digits}f}"
    return f"{symbol}{figure}" if symbol else f"{figure} {currency['code']}"
