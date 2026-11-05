"""``/admin/rate-limits`` — the dashboard's Settings → Rate limits section.

GET returns the saved settings, every provider they can apply to, and live
state: requests running and waiting per provider, its recent rate-limit
answers, "cooling down until …", and the clients the inbound limit refused.
PUT replaces the settings, persists them in the runtime settings store
(``runtime_settings.json``, beside the dashboard's other settings) and
applies them at once, without a restart.

Metadata only: no prompt, API key or token passes through here. A client
that sent a key is shown by a short SHA-256 fingerprint of it.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from ollabridge.addons.providers import pacing
from ollabridge.core import rate_limits
from ollabridge.core.rate_limits import (
    DEFAULT_PROVIDER_LIMIT,
    SUGGESTED_PROVIDER_LIMIT,
    InboundLimit,
    RateLimitSettings,
)
from ollabridge.core.security import require_api_key

log = logging.getLogger("ollabridge.rate_limits")

router = APIRouter(prefix="/admin/rate-limits", tags=["rate-limits"])


def _provider_row(
    pid: str,
    *,
    name: str,
    kind: str,
    enabled: bool,
    registered: bool,
    requests: int,
    cfg: RateLimitSettings,
    gates: dict[str, pacing.ProviderGate],
) -> dict[str, Any]:
    limit = cfg.providers.get(pid)
    gate = gates.get(pid) or pacing.ProviderGate(pid)
    return {
        "id": pid,
        "name": name,
        "kind": kind,
        "enabled": enabled,
        "registered": registered,
        # Calls routed to it since the gateway started: the dashboard lists
        # the providers in use, whatever kind they are.
        "requests": requests,
        "configured": limit is not None,
        "limits": (limit or DEFAULT_PROVIDER_LIMIT).model_dump(),
        "state": gate.snapshot(),
    }


def _view(request: Request) -> dict[str, Any]:
    cfg = rate_limits.current()
    gates = pacing.gates()
    registry = getattr(request.app.state, "provider_registry", None)
    rows: list[dict[str, Any]] = []
    for config in registry.list_providers() if registry is not None else []:
        state = registry.get_state(config.id)
        rows.append(
            _provider_row(
                config.id, name=config.name, kind=config.kind, enabled=config.enabled,
                registered=True, requests=int(getattr(state, "request_count", 0) or 0),
                cfg=cfg, gates=gates,
            )
        )
    # Settings saved for a provider that is not registered right now (a
    # source switched off, or the provider add-on still starting) stay
    # visible and editable.
    known = {row["id"] for row in rows}
    for pid in sorted((set(cfg.providers) | set(gates)) - known):
        rows.append(
            _provider_row(
                pid, name=pid, kind="", enabled=False, registered=False, requests=0, cfg=cfg, gates=gates
            )
        )
    rows.sort(
        key=lambda r: (
            not r["configured"],
            not r["state"]["recent"],
            not r["requests"],
            not r["enabled"],
            r["name"].lower(),
        )
    )
    return {
        "settings": cfg.model_dump(),
        "defaults": {
            "inbound": InboundLimit().model_dump(),
            "provider": DEFAULT_PROVIDER_LIMIT.model_dump(),
            # "Use suggested" in the dashboard, offered for every provider.
            "suggested": SUGGESTED_PROVIDER_LIMIT.model_dump(),
        },
        "providers": rows,
        "inbound": rate_limits.INBOUND.snapshot(cfg.inbound),
    }


@router.get("", dependencies=[Depends(require_api_key)])
async def get_rate_limits(request: Request) -> dict[str, Any]:
    return _view(request)


@router.put("", dependencies=[Depends(require_api_key)])
async def put_rate_limits(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError:  # not JSON, or not UTF-8
        raise HTTPException(status_code=400, detail="Expected JSON body") from None
    if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
        payload = payload["settings"]
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Rate limits must be a JSON object")
    try:
        new = RateLimitSettings.model_validate(payload)
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise HTTPException(status_code=422, detail=detail)

    saved = rate_limits.save(new)
    log.info(
        "Rate limits changed via admin API (no restart): inbound %s, %d provider(s) limited",
        f"{saved.inbound.requests_per_minute}/minute per client" if saved.inbound.enabled else "off",
        len(saved.providers),
    )
    return {"ok": True, **_view(request)}
