"""Opt-in upload of usage **metadata** to OllaBridge Cloud.

Nothing leaves the device unless all of these hold:

* the device is paired (``ollabridge login``),
* cloud sync is enabled, and
* the ``usage_metadata`` category is switched on — it is off by default even
  when sync is already enabled, so an upgrade never opts anyone in.

Events stay ``pending`` until the cloud acknowledges each one, so an outage or
an older cloud that lacks the endpoint only delays the upload.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from .store import UsageStore, get_usage_store, row_to_event

log = logging.getLogger(__name__)

ENDPOINT = "/v1/ledger/events"
BATCH = 500
_ACKNOWLEDGED = {"accepted", "merged", "duplicate"}


def sync_allowed() -> tuple[bool, str]:
    """(allowed, reason). The single consent gate for usage upload."""
    from ollabridge.cloud.device_config import load_cloud_device_credentials
    from ollabridge.cloud.sync_config import load_sync_config

    config = load_sync_config()
    if not config.enabled:
        return False, "cloud sync is disabled"
    if not config.usage_metadata:
        return False, "usage_metadata sync is off (ollabridge sync set usage_metadata true)"
    if load_cloud_device_credentials() is None:
        return False, "device is not paired (ollabridge login)"
    return True, "ok"


async def sync_once(
    store: Optional[UsageStore] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
    max_batches: int = 20,
) -> Dict[str, Any]:
    """Upload pending events. Returns a summary; never raises on network errors."""
    allowed, reason = sync_allowed()
    if not allowed:
        return {"synced": 0, "rejected": 0, "skipped": reason}

    from ollabridge.cloud.device_config import load_cloud_device_credentials

    creds = load_cloud_device_credentials()
    store = store or get_usage_store()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    synced = rejected = 0
    try:
        for _ in range(max_batches):
            rows = store.pending(BATCH)
            if not rows:
                break
            try:
                response = await client.post(
                    creds.cloud_url.rstrip("/") + ENDPOINT,
                    json={"events": [row_to_event(r) for r in rows]},
                    headers={"Authorization": f"Bearer {creds.device_token}"},
                )
            except httpx.HTTPError as exc:
                return {"synced": synced, "rejected": rejected, "error": type(exc).__name__}
            if response.status_code != 200:
                # 404 = a cloud without the ledger; 5xx = try again later.
                return {"synced": synced, "rejected": rejected, "error": f"http_{response.status_code}"}

            results = response.json().get("results") or []
            done = [r["event_id"] for r in results if r.get("status") in _ACKNOWLEDGED and r.get("event_id")]
            refused = [r["event_id"] for r in results if r.get("status") == "rejected" and r.get("event_id")]
            store.mark_synced(done, "synced")
            store.mark_synced(refused, "rejected")
            synced += len(done)
            rejected += len(refused)
            if not done and not refused:
                break  # nothing advanced; avoid spinning on the same batch
    finally:
        if owns_client:
            await client.aclose()
    return {"synced": synced, "rejected": rejected}


async def run_forever(interval_seconds: float = 60.0) -> None:
    """Background loop started by the gateway. Quiet when sync is not allowed."""
    import asyncio

    while True:
        await asyncio.sleep(interval_seconds)
        try:
            result = await sync_once()
            if result.get("synced") or result.get("error"):
                log.debug("usage sync: %s", result)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            log.debug("usage sync failed", exc_info=True)
