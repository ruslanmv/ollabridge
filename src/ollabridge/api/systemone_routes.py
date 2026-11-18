"""``POST /v1/systemone`` — decision requests, passed through to whoever hosts the model.

A decision model does not write text. It takes
a ``state`` and a set of typed ``questions`` and returns one probability per
option::

    {"model": "my-decision-model",
     "state": {"text": "..."},
     "questions": {"is_request": {"type": "noul", "instructions": "..."}}}
    -> {"answers": {"is_request": {"type": "noul", "noul": 0.97}}}

Two kinds of host can answer:

* **Ollama** (0.35.1 and later) serves this endpoint itself.
* **A source** from the Sources hub that has a *Decision endpoint* set: any
  server that takes the same request, at whatever path it uses.

The gateway adds what a client lacks: one address that is reachable from a
container or another host, the gateway's API key, and the choice of host. The
request body and the answer pass through unchanged, so a client written against
either host works against the gateway by changing the URL only.

Which host answers:

1. ``"<source>/<model>"`` names the source outright; the prefix is removed.
2. A model installed in Ollama is answered by Ollama.
3. Any other model is offered to each source with a decision endpoint, in the
   order they were added; the first that knows the model answers.
4. With no such source, the request goes to Ollama as before.

Failures keep their meaning:

* the host's own status and body are returned as they are (``404`` for a model
  it does not have, ``500`` when the model could not be loaded);
* ``502`` when the host cannot be reached, with the address that was tried;
* ``504`` when the host did not answer within ``SYSTEMONE_TIMEOUT_S``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ollabridge.core import runtime_settings as rts
from ollabridge.core.logsetup.request_facts import note as note_request
from ollabridge.core.redact import redact_text
from ollabridge.core.security import require_api_key

log = logging.getLogger("ollabridge.systemone")

router = APIRouter(tags=["systemone"])

#: The longest the gateway waits for a host. A decision model that does not fit
#: in GPU memory answers slowly, and the first request also loads the model.
#: A client that wants to give up sooner sets its own, shorter timeout.
DEFAULT_TIMEOUT_S = 300.0

#: How long the list of models installed in Ollama is remembered.
_OLLAMA_MODELS_TTL_S = 30.0
_ollama_models_cache: dict[str, tuple[float, frozenset[str]]] = {}


@dataclass
class Target:
    """One host a decision request can be sent to."""

    label: str  # for the log line: "ollama" or "source:<name>"
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    #: What an error may show: Ollama's address, or a source's name (never its address).
    shown_url: str = ""


def _timeout_s() -> float:
    try:
        value = float(os.environ.get("SYSTEMONE_TIMEOUT_S", "") or DEFAULT_TIMEOUT_S)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


async def _post(
    url: str, payload: dict[str, Any], timeout_s: float, headers: dict[str, str]
) -> httpx.Response:
    """One POST to a host. Its own function so the tests can replace it."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
        return await client.post(url, json=payload, headers=headers)


def _normalize(name: str) -> str:
    lower = name.strip().lower()
    return lower[: -len(":latest")] if lower.endswith(":latest") else lower


async def _ollama_models(base: str) -> frozenset[str]:
    """The models installed in Ollama, remembered briefly. Empty when it does not answer."""
    cached = _ollama_models_cache.get(base)
    if cached and time.monotonic() - cached[0] < _OLLAMA_MODELS_TTL_S:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            response = await client.get(f"{base}/api/tags")
            response.raise_for_status()
            models = response.json().get("models") or []
        names = frozenset(_normalize(str(m.get("name", ""))) for m in models if isinstance(m, dict))
    except (httpx.HTTPError, ValueError, AttributeError):
        names = frozenset()
    _ollama_models_cache[base] = (time.monotonic(), names)
    return names


def _secret_for(name: str) -> str | None:
    """The source's API key. Its own function so the tests can replace it."""
    from ollabridge.provider_ops import get_secret

    return get_secret(name)


def _decision_sources() -> list[Target]:
    """Every enabled source that has a decision endpoint, in the order they were added."""
    from ollabridge.providers_meta import decision_url, load_providers, request_headers

    targets: list[Target] = []
    for rec in load_providers():
        if not rec.enabled:
            continue
        url = decision_url(rec)
        if not url:
            continue
        try:
            headers = dict(request_headers(rec))
        except ValueError:
            headers = {}
        secret = _secret_for(rec.name)
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        targets.append(Target(label=f"source:{rec.name}", url=url, headers=headers, shown_url=rec.name))
    return targets


def _ollama_target() -> Target:
    base = rts.ollama_base_url()
    return Target(label="ollama", url=f"{base}/v1/systemone", shown_url=redact_text(base))


async def _targets(model: str) -> tuple[list[Target], str]:
    """The hosts to try for ``model``, in order, and the model name to send them."""
    sources = _decision_sources()
    if "/" in model:
        prefix, rest = model.split("/", 1)
        named = [t for t in sources if t.label.lower() == f"source:{prefix.lower()}"]
        if named and rest.strip():
            return named[:1], rest.strip()
    if not sources:
        return [_ollama_target()], model
    if _normalize(model) in await _ollama_models(rts.ollama_base_url()):
        return [_ollama_target()], model
    return sources, model


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": "systemone_error", "code": code, **extra}},
    )


async def _ask(target: Target, payload: dict[str, Any], model: str) -> JSONResponse:
    """Send the request to one host and return its answer unchanged."""
    local = target.label == "ollama"
    host = "Ollama" if local else f"The source {target.shown_url}"
    # Ollama's address helps fix a wrong setting; a source is named, its address is not shown.
    where = {"base_url": target.shown_url} if local else {"source": target.shown_url}
    started = time.time()
    try:
        upstream = await _post(target.url, payload, _timeout_s(), target.headers)
    except httpx.TimeoutException:
        log.warning("systemone: %s did not answer in %.0f s (model %s)", target.label, _timeout_s(), model)
        raise _error(
            504,
            "ollama_timeout" if local else "upstream_timeout",
            f"{host} did not answer within {_timeout_s():.0f} s.",
            **where,
        ) from None
    except httpx.HTTPError as exc:
        log.warning("systemone: %s unreachable (%s)", target.label, type(exc).__name__)
        at = f" at {target.shown_url}" if local else ""
        raise _error(
            502,
            "ollama_unreachable" if local else "upstream_unreachable",
            f"{host} could not be reached{at}.",
            **where,
        ) from None

    try:
        body = upstream.json()
    except ValueError:
        raise _error(
            502,
            "ollama_bad_response" if local else "upstream_bad_response",
            f"{host} answered HTTP {upstream.status_code} with a body that is not JSON.",
        ) from None

    latency_ms = int((time.time() - started) * 1000)
    if upstream.status_code >= 400:
        log.warning(
            "systemone: %s answered HTTP %s for model %s in %d ms",
            target.label, upstream.status_code, model, latency_ms,
        )
    else:
        log.info("systemone: model %s answered by %s in %d ms", model, target.label, latency_ms)
    return JSONResponse(status_code=upstream.status_code, content=body)


@router.post("/v1/systemone")
async def systemone(request: Request, _key: str = Depends(require_api_key)) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - any unreadable body is the client's error
        raise _error(400, "invalid_json", "The request body is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise _error(400, "invalid_request", "The request body must be a JSON object.")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise _error(400, "missing_model", "The request needs a `model`.")
    if not isinstance(payload.get("questions"), dict) or not payload["questions"]:
        raise _error(400, "missing_questions", "The request needs at least one question.")

    targets, upstream_model = await _targets(model.strip())
    if upstream_model != model:
        payload = {**payload, "model": upstream_model}

    answer: JSONResponse | None = None
    for target in targets:
        note_request(route=f"{target.label}/systemone", model=upstream_model)
        answer = await _ask(target, payload, upstream_model)
        # "I do not have that model" from one source: the next one may.
        if answer.status_code != 404:
            break
    assert answer is not None  # `_targets` never returns an empty list
    return answer
