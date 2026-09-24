"""Cloud-relay adapter for the HomePilot Cloud Mirror plane.

OllaBridge Cloud's owner-scoped mirror routes (``/v1/mirror/nodes/*``) relay
five op-codes to the paired gateway. This module maps them onto HomePilot's
localhost-only node endpoints on the same machine:

    homepilot.mirror.manifest    GET  /v1/node/manifest
    homepilot.mirror.rpc         POST /v1/node/rpc
    homepilot.mirror.job.create  POST /v1/node/jobs
    homepilot.mirror.job.get     GET  /v1/node/jobs/{job_id}
    homepilot.mirror.job.cancel  POST /v1/node/jobs/{job_id}/cancel

The mapping matches ``ollabridge-cloud/connector/bridge.py`` so both bridges
behave the same. HomePilot keeps its own allow-lists (read-only RPC
operations, whitelisted job operations); this adapter adds none of its own
beyond the five op-codes and never logs params (they may carry prompts or
photos).

ADDITIVE and dark by default: nothing here runs unless
``HOMEPILOT_MIRROR_RELAY_ENABLED`` and ``HOMEPILOT_ENABLED`` are both true.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

RELAY_CAPABILITY = "homepilot.mirror"
MANIFEST_OP = "homepilot.mirror.manifest"
RPC_OP = "homepilot.mirror.rpc"
JOB_CREATE_OP = "homepilot.mirror.job.create"
JOB_GET_OP = "homepilot.mirror.job.get"
JOB_CANCEL_OP = "homepilot.mirror.job.cancel"
MIRROR_OPS = frozenset({MANIFEST_OP, RPC_OP, JOB_CREATE_OP, JOB_GET_OP, JOB_CANCEL_OP})

_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_OPERATION = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class MirrorRelayError(RuntimeError):
    """A mirror op could not be served; the message is safe to relay."""


def enabled(homepilot_enabled: bool) -> bool:
    """True when this gateway should serve the HomePilot mirror ops."""
    from ollabridge.core.settings import settings

    return bool(homepilot_enabled and settings.HOMEPILOT_MIRROR_RELAY_ENABLED)


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _job_id(payload: dict[str, Any]) -> str:
    job_id = str(payload.get("job_id") or "")
    if not _JOB_ID.match(job_id):
        raise MirrorRelayError("invalid_job_id")
    return job_id


def _operation(payload: dict[str, Any]) -> str:
    operation = str(payload.get("operation") or "")
    if not _OPERATION.match(operation):
        raise MirrorRelayError("invalid_operation")
    return operation


def _params(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise MirrorRelayError("invalid_params")
    return params


def build_request(
    op: str, payload: dict[str, Any]
) -> tuple[str, str, dict[str, Any] | None, float]:
    """Return (method, path, json_body, timeout) for a mirror op-code."""
    if op == MANIFEST_OP:
        return "GET", "/v1/node/manifest", None, 30.0
    if op == RPC_OP:
        return (
            "POST",
            "/v1/node/rpc",
            {"operation": _operation(payload), "params": _params(payload)},
            30.0,
        )
    if op == JOB_CREATE_OP:
        body: dict[str, Any] = {
            "operation": _operation(payload),
            "params": _params(payload),
        }
        resource_uri = payload.get("resource_uri")
        if isinstance(resource_uri, str) and resource_uri:
            body["resource_uri"] = resource_uri
        return "POST", "/v1/node/jobs", body, 60.0
    if op == JOB_GET_OP:
        return "GET", f"/v1/node/jobs/{_job_id(payload)}", None, 30.0
    if op == JOB_CANCEL_OP:
        return "POST", f"/v1/node/jobs/{_job_id(payload)}/cancel", None, 30.0
    raise MirrorRelayError(f"unknown_mirror_op: {op}")


async def dispatch(
    op: str, payload: dict[str, Any], *, base_url: str, api_key: str = ""
) -> dict[str, Any]:
    """Serve one mirror op against the local HomePilot node endpoints."""
    method, path, body, timeout = build_request(op, payload or {})
    url = f"{base_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0)
        ) as client:
            response = await client.request(
                method, url, json=body, headers=_headers(api_key)
            )
    except httpx.HTTPError as exc:
        raise MirrorRelayError(f"homepilot_unreachable: {type(exc).__name__}") from None

    if response.status_code >= 400:
        # Relay HomePilot's own error code (e.g. node_jobs_disabled,
        # unknown_operation) so the cloud can show an honest reason.
        code = ""
        try:
            data = response.json()
            if isinstance(data, dict):
                code = str(data.get("error") or data.get("detail") or "")[:120]
        except ValueError:
            pass
        raise MirrorRelayError(
            f"homepilot_http_{response.status_code}" + (f": {code}" if code else "")
        )

    try:
        data = response.json()
    except ValueError:
        raise MirrorRelayError("homepilot_invalid_response") from None
    if not isinstance(data, dict):
        raise MirrorRelayError("homepilot_invalid_response")
    return data
