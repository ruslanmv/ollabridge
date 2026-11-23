"""Model health checks for Models → Testing.

One check sends a fixed, harmless message to one model through the gateway's
own chat route, then turns the outcome into one verdict and one plain
sentence. Only metadata is kept: no answer text is ever stored.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ollabridge.core import paths

CHECK_MESSAGE = "Reply with the single word OK."
#: Reasoning models spend ~20 tokens thinking before they say anything.
CHECK_MAX_TOKENS = 64
#: Our own limit per check; the gateway's provider timeout is longer.
CHECK_TIMEOUT_S = 60.0
#: An answer slower than this is "Slow".
SLOW_AFTER_MS = 15_000
#: Sent with every check so Usage shows checks as their own source.
CHECK_APP = "model-check"

_DETAIL_MAX = 300
_RETIRED_HINTS = ("no healthy deployments", "model not found", "does not exist", "unknown model")


def _source_name(source: Optional[str]) -> str:
    return source or "its provider"


def successor(model: str, inventory_ids: Iterable[str]) -> Optional[str]:
    """A listed id that extends this one (``x-kimi-k3`` → ``x-kimi-k3-1-pro``)."""
    candidates = sorted(i for i in inventory_ids if i != model and i.startswith(f"{model}-"))
    return candidates[0] if candidates else None


def _error_of(body: Any) -> tuple[Optional[str], str]:
    """(code, message) from an OpenAI-style or FastAPI error body."""
    if isinstance(body, Mapping):
        inner = body.get("detail", body)
        if isinstance(inner, Mapping):
            err = inner.get("error", inner)
            if isinstance(err, Mapping):
                return (str(err["code"]) if err.get("code") else None), str(err.get("message") or "")
            return None, str(inner)
        return None, str(inner)
    return None, str(body or "")


def verdict(
    *,
    status: Optional[int],
    body: Any,
    latency_ms: Optional[int],
    timed_out: bool = False,
    source: Optional[str] = None,
    inventory_ids: Iterable[str] = (),
    model: str = "",
) -> Dict[str, Any]:
    """→ ``{verdict, reason_code, plain, detail}``. Pure: no network, no I/O.

    ``verdict`` is ``working`` | ``slow`` | ``not_working``. ``reason_code`` is
    the gateway's own error code (or ``ok`` / ``empty_answer`` / ``slow`` /
    ``check_timeout``); ``plain`` is what a non-expert reads.
    """
    from ollabridge.core.redact import redact_text

    name = _source_name(source)
    seconds = f"{(latency_ms or 0) / 1000:.1f} s"

    if timed_out:
        return {"verdict": "not_working", "reason_code": "check_timeout",
                "plain": f"No answer within {int(CHECK_TIMEOUT_S)} s. {name} may be overloaded right now.",
                "detail": None}

    if status == 200:
        content = ""
        if isinstance(body, Mapping):
            choices = body.get("choices") or []
            if choices and isinstance(choices[0], Mapping):
                message = choices[0].get("message") or {}
                content = str(message.get("content") or "") if isinstance(message, Mapping) else ""
        if latency_ms is not None and latency_ms > SLOW_AFTER_MS:
            return {"verdict": "slow", "reason_code": "slow",
                    "plain": f"Answered, but took {seconds}. It may be busy right now.", "detail": None}
        if not content.strip():
            return {"verdict": "working", "reason_code": "empty_answer",
                    "plain": f"Answered in {seconds}, but the reply was empty (it used its whole limit thinking).",
                    "detail": None}
        return {"verdict": "working", "reason_code": "ok", "plain": f"Answered in {seconds}.", "detail": None}

    code, message = _error_of(body)
    detail = redact_text(f"HTTP {status}: {message}" if status else message)[:_DETAIL_MAX] or None
    lowered = message.lower()

    if code == "model_not_found" or any(hint in lowered for hint in _RETIRED_HINTS):
        plain = f"This model is no longer available from {name}. It may have been renamed."
        nxt = successor(model, inventory_ids)
        if nxt:
            plain += f" Try {nxt}."
        return {"verdict": "not_working", "reason_code": code or "retired", "plain": plain, "detail": detail}
    if code == "rate_limited" or status == 429:
        plain = f"{name} is limiting requests right now. Try again in a minute."
    elif code == "provider_timeout" or status == 504:
        plain = f"No answer in time. {name} may be overloaded right now."
    elif code == "ollama_unreachable":
        plain = "Ollama isn't running on this computer. Start it from Runtimes."
    elif code in ("network_offline", "connection_lost"):
        plain = f"Can't reach {name}. Check your network or VPN."
    elif code == "provider_auth" or status in (401, 403):
        plain = f"{name} refused the key. Check it in Sources."
    elif code == "provider_unavailable":
        plain = f"{name} is unavailable right now."
    elif code == "tools_unsupported":
        plain = "This model can't be used this way."
    else:
        plain = f"{name} returned an error."
    return {"verdict": "not_working", "reason_code": code or (f"http_{status}" if status else "error"),
            "plain": plain, "detail": detail}


# ── last result per model ───────────────────────────────────────────────

class CheckStore:
    """``<OLLABRIDGE_HOME>/model_checks.json``: the last check of each model."""

    _KEYS = ("model", "source", "verdict", "reason_code", "plain", "latency_ms",
             "http_status", "detail", "checked_at")

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (paths.data_dir() / "model_checks.json")
        self._lock = threading.Lock()

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
        return data if isinstance(data, dict) else {}

    def save(self, result: Mapping[str, Any]) -> None:
        entry = {k: result.get(k) for k in self._KEYS}  # metadata only, by construction
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            data[str(entry["model"])] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
