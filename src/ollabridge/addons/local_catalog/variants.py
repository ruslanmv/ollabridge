"""Model copies: an installed model under a new name with its own context window.

A copy is what a two-line Modelfile makes (``FROM model``, ``PARAMETER
num_ctx``). It shares the original's files, so it costs no download and no
disk space, and it lets one set of weights run with a window that fits this
machine's memory, or under the name a client expects.

Whether a copy *loads* depends on the free memory of the machine, which no
metadata says. So the answer is measured: :func:`load_test` asks the runtime
for one tiny answer and records whether the model loaded, how long it took and
how much memory it used. The last result per model is kept in
``model_load_tests.json`` in the data folder.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ollabridge.core import runtime_settings as rts
from ollabridge.core.paths import data_dir

log = logging.getLogger("ollabridge.variants")

_RESULTS_FILE = "model_load_tests.json"
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*(:[A-Za-z0-9._-]+)?$"
_NAME_RE = re.compile(NAME_PATTERN)
_CONTEXT_SUFFIX_RE = re.compile(r"-\d+k?$", re.IGNORECASE)

#: Context sizes the wizard offers, in tokens.
CONTEXT_PRESETS = (2048, 4096, 6144, 8192, 16384, 32768)
MIN_CONTEXT = 512
#: The longest a load test waits: a model that only partly fits on the GPU loads slowly.
LOAD_TIMEOUT_S = 300.0

#: Fragments of a runtime error that mean "the model did not fit in memory".
_MEMORY_MARKERS = (
    "out of memory",
    "out-of-memory",
    "mem_buffer",
    "failed to allocate",
    "cudamalloc",
    "requires more system memory",
    "llama-server process has terminated",
    "llama runner process has terminated",
)

#: Replaced by the tests with an ``httpx.MockTransport``.
_transport: Optional[httpx.AsyncBaseTransport] = None


class VariantError(Exception):
    """A refusal with the HTTP status the route answers with."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def _http(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=rts.ollama_base_url(),
        timeout=httpx.Timeout(timeout, connect=5.0),
        transport=_transport,
    )


# ── Names ────────────────────────────────────────────────────────────────


def normalize(name: str) -> str:
    """``model`` and ``model:latest`` are one model; the runtime ignores case."""
    lower = name.strip().lower()
    return lower[: -len(":latest")] if lower.endswith(":latest") else lower


def display_name(name: str) -> str:
    return name[: -len(":latest")] if name.endswith(":latest") else name


def context_label(context: int) -> str:
    return f"{context // 1024}k" if context % 1024 == 0 else str(context)


def suggest_name(source: str, context: int) -> str:
    """``clef-flash:9b`` at 6144 becomes ``clef-flash-6k``; a copy's own size suffix is replaced."""
    base = source.strip().split("/")[-1].split(":")[0]
    base = _CONTEXT_SUFFIX_RE.sub("", base) or base
    return f"{base}-{context_label(context)}"


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name)) and len(name) <= 120


# ── Stored load results ──────────────────────────────────────────────────


def _results_path():
    return data_dir() / _RESULTS_FILE


def load_results() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_results_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_results(results: dict[str, dict[str, Any]]) -> None:
    path = _results_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    except OSError as exc:  # a read-only data folder must not fail the request
        log.warning("could not save load results to %s: %s", path, exc)


def _forget_result(name: str) -> None:
    results = load_results()
    if results.pop(normalize(name), None) is not None:
        _save_results(results)


# ── Reading the runtime ──────────────────────────────────────────────────


def _parameter(parameters: Any, key: str) -> Optional[int]:
    """One integer from ``/api/show``'s ``parameters`` text (``num_ctx   8192``)."""
    if not isinstance(parameters, str):
        return None
    for line in parameters.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == key:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def _max_context(model_info: Any) -> Optional[int]:
    if not isinstance(model_info, dict):
        return None
    for key, value in model_info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


def _kind(capabilities: list[str]) -> str:
    if "decision" in capabilities:
        return "decision"
    if "embedding" in capabilities and "completion" not in capabilities:
        return "embedding"
    return "chat"


async def _tags(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    try:
        response = await client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get("models")
    except (httpx.HTTPError, ValueError) as exc:
        raise VariantError(
            502, f"Ollama could not be reached at {rts.ollama_base_url()} ({type(exc).__name__})."
        ) from None
    return [m for m in models if isinstance(m, dict) and m.get("name")] if isinstance(models, list) else []


async def _show(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    try:
        response = await client.post("/api/show", json={"model": name})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _row(tag: dict[str, Any], show: dict[str, Any], installed: set[str], results: dict[str, Any]) -> dict[str, Any]:
    name = str(tag["name"])
    details = show.get("details") if isinstance(show.get("details"), dict) else {}
    parent = str(details.get("parent_model") or "").strip()
    capabilities = [str(c) for c in show.get("capabilities") or []]
    is_copy = bool(parent) and normalize(parent) in installed and normalize(parent) != normalize(name)
    return {
        "name": display_name(name),
        "built_from": display_name(parent) if parent else None,
        # A copy is built from a model that is installed here; a library build names a
        # parent that is not, and removing it would remove the files.
        "is_copy": is_copy,
        "context": _parameter(show.get("parameters"), "num_ctx"),
        "max_context": _max_context(show.get("model_info")),
        "size_bytes": tag.get("size") if isinstance(tag.get("size"), int) else None,
        "parameter_size": details.get("parameter_size") or None,
        "quantization": details.get("quantization_level") or None,
        "kind": _kind(capabilities),
        "load": results.get(normalize(name)),
    }


async def list_models() -> list[dict[str, Any]]:
    """Every installed model with what it was built from, its context window and
    the last load result. A model's copies follow it."""
    async with _http() as client:
        tags = await _tags(client)
        shows = await asyncio.gather(*(_show(client, str(t["name"])) for t in tags))
    installed = {normalize(str(t["name"])) for t in tags}
    results = load_results()
    rows = [_row(tag, show, installed, results) for tag, show in zip(tags, shows)]

    def order(row: dict[str, Any]) -> tuple[str, int, int, str]:
        root = row["built_from"] if row["is_copy"] else row["name"]
        return (str(root).lower(), 1 if row["is_copy"] else 0, row["context"] or 0, row["name"].lower())

    return sorted(rows, key=order)


async def _find(name: str) -> Optional[dict[str, Any]]:
    wanted = normalize(name)
    return next((row for row in await list_models() if normalize(row["name"]) == wanted), None)


# ── Create / remove ──────────────────────────────────────────────────────


async def create(source: str, context: int, name: Optional[str] = None) -> dict[str, Any]:
    """Make a copy of the installed ``source`` with its context window set."""
    rows = await list_models()
    by_name = {normalize(row["name"]): row for row in rows}
    origin = by_name.get(normalize(source))
    if origin is None:
        raise VariantError(404, f"{source} is not installed.")
    if context < MIN_CONTEXT:
        raise VariantError(400, f"The context window must be at least {MIN_CONTEXT} tokens.")
    if origin["max_context"] and context > origin["max_context"]:
        raise VariantError(
            400, f"{origin['name']} supports at most {origin['max_context']:,} tokens of context."
        )
    new_name = (name or "").strip() or suggest_name(origin["name"], context)
    if not valid_name(new_name):
        raise VariantError(400, "Use letters, digits, dots, dashes and underscores in the name.")
    if normalize(new_name) in by_name:
        raise VariantError(409, f"A model called {display_name(new_name)} already exists.")

    # Build on the original, not on a copy, so the "built from" of every copy is the same model.
    base = origin["built_from"] if origin["is_copy"] else origin["name"]
    body = {"model": new_name, "from": base, "parameters": {"num_ctx": context}, "stream": False}
    try:
        async with _http(timeout=120.0) as client:
            response = await client.post("/api/create", json=body)
    except httpx.HTTPError as exc:
        raise VariantError(502, f"Ollama could not be reached ({type(exc).__name__}).") from None
    if response.status_code >= 400:
        raise VariantError(502, f"Ollama could not create {new_name}: {_error_text(response)}")
    _forget_result(new_name)
    row = await _find(new_name)
    if row is None:
        raise VariantError(502, f"Ollama reported success but {new_name} is not listed.")
    return row


async def remove(name: str) -> None:
    """Remove a copy. Only a copy: its files belong to the model it was built from."""
    row = await _find(name)
    if row is None:
        raise VariantError(404, f"{name} is not installed.")
    if not row["is_copy"]:
        raise VariantError(400, f"{row['name']} is not a copy, so removing it would delete its files.")
    try:
        async with _http() as client:
            response = await client.request("DELETE", "/api/delete", json={"model": row["name"]})
    except httpx.HTTPError as exc:
        raise VariantError(502, f"Ollama could not be reached ({type(exc).__name__}).") from None
    if response.status_code >= 400:
        raise VariantError(502, f"Ollama could not remove {row['name']}: {_error_text(response)}")
    _forget_result(row["name"])


# ── Load test ────────────────────────────────────────────────────────────


def _error_text(response: httpx.Response) -> str:
    try:
        detail = response.json().get("error")
    except (ValueError, AttributeError):
        detail = None
    return str(detail or f"HTTP {response.status_code}")


def explain_failure(error: str) -> str:
    """The runtime's error in words a person can act on."""
    lower = error.lower()
    if any(marker in lower for marker in _MEMORY_MARKERS):
        return "Not enough free memory to load it."
    if "not found" in lower:
        return "The model is not installed."
    first_line = error.strip().splitlines()[0] if error.strip() else "The model did not answer."
    return first_line[:200]


def smaller_context(context: Optional[int]) -> Optional[int]:
    """The next preset below ``context``: what to try after a model did not fit."""
    if not context:
        return None
    below = [size for size in CONTEXT_PRESETS if size < context]
    return max(below) if below else None


def _probe(name: str, kind: str) -> tuple[str, dict[str, Any]]:
    """The smallest request that makes the runtime load the model."""
    if kind == "decision":
        return "/v1/systemone", {
            "model": name,
            "state": {"text": "ping"},
            "questions": {"ok": {"type": "noul", "instructions": "Is `text` a single word?"}},
        }
    if kind == "embedding":
        return "/api/embed", {"model": name, "input": "ping"}
    return "/api/generate", {
        "model": name,
        "prompt": "ping",
        "stream": False,
        "options": {"num_predict": 1},
    }


async def _loaded(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    """The model's entry in ``/api/ps`` (memory in use), or nothing."""
    try:
        response = await client.get("/api/ps")
        models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return {}
    wanted = normalize(name)
    return next((m for m in models if isinstance(m, dict) and normalize(str(m.get("name", ""))) == wanted), {})


async def load_test(name: str) -> dict[str, Any]:
    """Load the model once and record whether it fits on this machine."""
    row = await _find(name)
    if row is None:
        raise VariantError(404, f"{name} is not installed.")
    path, body = _probe(row["name"], row["kind"])
    started = time.monotonic()
    error: Optional[str] = None
    memory: dict[str, Any] = {}
    async with _http(timeout=LOAD_TIMEOUT_S) as client:
        try:
            response = await client.post(path, json=body)
            if response.status_code >= 400:
                error = _error_text(response)
        except httpx.TimeoutException:
            error = f"The model did not answer within {LOAD_TIMEOUT_S:.0f} seconds."
        except httpx.HTTPError as exc:
            raise VariantError(502, f"Ollama could not be reached ({type(exc).__name__}).") from None
        seconds = round(time.monotonic() - started, 1)
        if error is None:
            memory = await _loaded(client, row["name"])

    result: dict[str, Any] = {
        "loads": error is None,
        "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": seconds,
        "context": row["context"],
        "total_bytes": memory.get("size") if isinstance(memory.get("size"), int) else None,
        "gpu_bytes": memory.get("size_vram") if isinstance(memory.get("size_vram"), int) else None,
        "reason": explain_failure(error) if error else None,
        "try_context": smaller_context(row["context"] or row["max_context"]) if error else None,
    }
    if error:
        log.info("load test: %s did not load (%s)", row["name"], result["reason"])
    results = load_results()
    results[normalize(row["name"])] = result
    _save_results(results)
    return {**row, "load": result}
