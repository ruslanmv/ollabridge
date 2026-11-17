"""``POST /v1/systemone`` — decision requests, passed through to Ollama.

A decision model (``clef-flash`` and its copies) does not write text. It takes
a ``state`` and a set of typed ``questions`` and returns one probability per
option::

    {"model": "clef-flash-8k",
     "state": {"conversation": "..."},
     "questions": {"is_request": {"type": "noul", "instructions": "..."}}}
    -> {"answers": {"is_request": {"type": "noul", "noul": 0.97}}}

Ollama (0.35.1 and later) serves this endpoint itself. The gateway adds what
a client outside the machine lacks: one address that is reachable from a
container or another host, and the gateway's API key. The request body and
Ollama's answer pass through unchanged, so a client written against Ollama
works against the gateway by changing the URL only.

Failures keep their meaning:

* Ollama's own status and body are returned as they are (``404`` for a model
  that is not installed, ``500`` when the model could not be loaded);
* ``502`` when Ollama cannot be reached, with the address that was tried;
* ``504`` when Ollama did not answer within ``SYSTEMONE_TIMEOUT_S``.
"""

from __future__ import annotations

import logging
import os
import time
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

#: The longest the gateway waits for Ollama. A decision model that does not fit
#: in GPU memory answers slowly, and the first request also loads the model.
#: A client that wants to give up sooner sets its own, shorter timeout.
DEFAULT_TIMEOUT_S = 300.0


def _timeout_s() -> float:
    try:
        value = float(os.environ.get("SYSTEMONE_TIMEOUT_S", "") or DEFAULT_TIMEOUT_S)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


async def _post_to_ollama(url: str, payload: dict[str, Any], timeout_s: float) -> httpx.Response:
    """One POST to Ollama. Its own function so the tests can replace it."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
        return await client.post(url, json=payload)


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"message": message, "type": "systemone_error", "code": code, **extra}},
    )


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

    base = rts.ollama_base_url()
    url = f"{base}/v1/systemone"
    note_request(route="ollama/systemone", model=model)
    started = time.time()
    try:
        upstream = await _post_to_ollama(url, payload, _timeout_s())
    except httpx.TimeoutException:
        log.warning("systemone: Ollama did not answer in %.0f s (model %s)", _timeout_s(), model)
        raise _error(
            504,
            "ollama_timeout",
            f"Ollama did not answer within {_timeout_s():.0f} s.",
            base_url=redact_text(base),
        ) from None
    except httpx.HTTPError as exc:
        log.warning("systemone: Ollama unreachable at %s (%s)", redact_text(base), type(exc).__name__)
        raise _error(
            502,
            "ollama_unreachable",
            f"Ollama could not be reached at {redact_text(base)}.",
            base_url=redact_text(base),
        ) from None

    try:
        body = upstream.json()
    except ValueError:
        raise _error(
            502,
            "ollama_bad_response",
            f"Ollama answered HTTP {upstream.status_code} with a body that is not JSON.",
        ) from None

    latency_ms = int((time.time() - started) * 1000)
    if upstream.status_code >= 400:
        log.warning(
            "systemone: Ollama answered HTTP %s for model %s in %d ms",
            upstream.status_code, model, latency_ms,
        )
    else:
        log.info("systemone: model %s answered in %d ms", model, latency_ms)
    return JSONResponse(status_code=upstream.status_code, content=body)
