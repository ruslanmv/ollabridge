"""
Cloud Bridge Lifecycle Manager — runs inside OllaBridge local gateway.

Manages the WebSocket connection to OllaBridge Cloud:
  - Start/stop the relay bridge as a background asyncio task
  - Expose status (connected, models shared, latency)
  - Auto-reconnect with exponential backoff
  - Persist credentials to ~/.ollabridge/cloud_device.json

This replaces the standalone CLI bridge connector with an in-process
manager that the gateway controls via /admin/cloud/* endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

try:
    from ollabridge.core.websocket_client import (
        connection_options,
        websocket_connect as ws_connect,
    )
except ImportError:
    ws_connect = None  # type: ignore[assignment]

from ollabridge.cloud.api_client import CloudApiClient, DevicePoll, DeviceStart
from ollabridge.cloud.device_config import (
    CloudDeviceCredentials,
    load_cloud_device_credentials,
    save_cloud_device_credentials,
)

log = logging.getLogger("ollabridge.cloud")

PING_INTERVAL = 25
RECONNECT_DELAYS = [2, 4, 8, 16, 30]

# WebSocket close codes the cloud relay uses to reject a device token
# (see ollabridge_cloud/api/relay.py). Receiving one of these means the token
# is permanently invalid — retrying with it is futile.
AUTH_REJECTION_CODES = frozenset({4401, 4403})


def _is_auth_rejection(exc: BaseException) -> bool:
    """True when *exc* is a WebSocket close indicating the token was rejected.

    Handles the several shapes the ``websockets`` library uses across
    versions: a ``rcvd``/``sent`` Close object with ``.code`` (newer), a bare
    ``.code`` attribute (older), or — as a last resort — the code appearing in
    the exception text (e.g. "received 4401 (private use) Invalid token").
    """
    codes: set[int] = set()
    for attr in ("rcvd", "sent"):
        frame = getattr(exc, attr, None)
        code = getattr(frame, "code", None)
        if isinstance(code, int):
            codes.add(code)
    direct = getattr(exc, "code", None)
    if isinstance(direct, int):
        codes.add(direct)
    if codes & AUTH_REJECTION_CODES:
        return True
    # Fallback: match the close code in the message when attributes are absent.
    text = str(exc)
    return any(str(code) in text for code in AUTH_REJECTION_CODES)


class BridgeState(str, Enum):
    DISCONNECTED = "disconnected"
    PAIRING = "pairing"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class BridgeStatus:
    state: BridgeState = BridgeState.DISCONNECTED
    cloud_url: str = ""
    device_id: str = ""
    models_shared: list[str] = field(default_factory=list)
    connected_since: Optional[float] = None
    last_error: str = ""
    pairing_code: str = ""
    pairing_expires_at: float = 0.0
    reconnect_attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "cloud_url": self.cloud_url,
            "device_id": self.device_id,
            "models_shared": self.models_shared,
            "models_count": len(self.models_shared),
            "connected_since": self.connected_since,
            "uptime_seconds": (
                round(time.time() - self.connected_since)
                if self.connected_since
                else None
            ),
            "last_error": self.last_error,
            "pairing_code": self.pairing_code,
            "pairing_expires_at": self.pairing_expires_at,
            "reconnect_attempt": self.reconnect_attempt,
        }


class CloudBridgeManager:
    """
    Manages the lifecycle of the WebSocket bridge to OllaBridge Cloud.

    Designed to be attached to the FastAPI app.state and controlled via
    /admin/cloud/* API endpoints.
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        homepilot_base_url: str = "http://localhost:8000",
        homepilot_api_key: str = "",
        homepilot_enabled: bool = False,
    ) -> None:
        self._ollama_url = ollama_base_url
        self._hp_url = homepilot_base_url
        self._hp_key = homepilot_api_key
        self._hp_enabled = homepilot_enabled

        self.status = BridgeStatus()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._ws: Any = None
        self._creds: Optional[CloudDeviceCredentials] = None
        # Optional reference to the local catalog — set after startup so the
        # heartbeat can ship a richer manifest than the legacy name list.
        self._local_catalog: Any = None
        self._local_catalog_node_id: str = ""

    # ── Local catalog integration ──────────────────────────────────────

    def set_local_catalog(self, repository: Any, *, node_id: str) -> None:
        """Attach the local catalog so heartbeats include the rich manifest."""
        self._local_catalog = repository
        self._local_catalog_node_id = node_id

    def _build_catalog_manifest(self) -> Optional[dict[str, Any]]:
        """Compose the catalog payload the cloud Admin ingests."""
        repo = self._local_catalog
        if repo is None or not self._local_catalog_node_id:
            return None
        try:
            stats = repo.stats(self._local_catalog_node_id).model_dump(mode="json")
            models = []
            for m in repo.list_models(self._local_catalog_node_id):
                models.append({
                    "router_model_id": m.router_model_id,
                    "external_model_id": m.external_model_id,
                    "display_name": m.display_name,
                    "family": m.family,
                    "parameter_size": m.parameter_size,
                    "quantization": m.quantization,
                    "context_window": m.context_window,
                    "supports_chat": bool(m.capabilities and m.capabilities.supports_chat),
                    "supports_tools": bool(m.capabilities and m.capabilities.supports_tools),
                    "supports_vision": bool(m.capabilities and m.capabilities.supports_vision),
                    "supports_embeddings": bool(m.capabilities and m.capabilities.supports_embeddings),
                    "enabled": m.enabled,
                    "is_top_recommended": m.is_top_recommended,
                    "rank": m.rank,
                    "score": round(m.score, 4),
                    "setup_status": m.setup_status.value,
                    "latency_ms": m.latency_observed_ms,
                })
            return {
                "node_id": self._local_catalog_node_id,
                "execution_location": "local",
                "stats": stats,
                "models": models,
            }
        except Exception as exc:
            log.warning("Failed to build local catalog manifest: %s", exc)
            return None

    # ── Auto-connect on startup ──────────────────────────────────────

    async def try_auto_connect(self) -> None:
        """If saved credentials exist, auto-start the bridge."""
        creds = load_cloud_device_credentials()
        if creds:
            log.info(
                "Found saved cloud credentials for device %s → %s",
                creds.device_id,
                creds.cloud_url,
            )
            await self.connect(creds.cloud_url, creds.device_token, creds.device_id)

    # ── Pairing Flow ─────────────────────────────────────────────────

    async def start_pairing(self, cloud_url: str) -> DeviceStart:
        """Step 1: Call /device/start on OllaBridge Cloud."""
        self.status.state = BridgeState.PAIRING
        self.status.cloud_url = cloud_url
        self.status.last_error = ""

        client = CloudApiClient(cloud_url)
        try:
            result = client.device_start()
            self.status.pairing_code = result.user_code
            self.status.pairing_expires_at = time.time() + result.expires_in
            self._pairing_device_code = result.device_code
            self._pairing_cloud_url = cloud_url
            return result
        except Exception as exc:
            self.status.state = BridgeState.ERROR
            self.status.last_error = str(exc)
            raise
        finally:
            client.close()

    async def poll_pairing(self) -> DevicePoll:
        """Step 2: Poll /device/poll until approved or expired."""
        device_code = getattr(self, "_pairing_device_code", "")
        cloud_url = getattr(self, "_pairing_cloud_url", "")
        if not device_code or not cloud_url:
            raise ValueError("No active pairing session — call start_pairing first")

        client = CloudApiClient(cloud_url)
        try:
            result = client.device_poll(device_code)
            if result.status == "approved" and result.approved:
                # Save credentials
                creds = CloudDeviceCredentials(
                    cloud_url=cloud_url,
                    device_id=result.approved.device_id,
                    device_token=result.approved.device_token,
                )
                save_cloud_device_credentials(creds)
                self._creds = creds
                self.status.pairing_code = ""

                # Auto-connect
                await self.connect(
                    cloud_url,
                    result.approved.device_token,
                    result.approved.device_id,
                )
            elif result.status == "expired":
                self.status.state = BridgeState.DISCONNECTED
                self.status.pairing_code = ""
            return result
        except Exception as exc:
            self.status.last_error = str(exc)
            raise
        finally:
            client.close()

    # ── Connect / Disconnect ─────────────────────────────────────────

    async def connect(
        self, cloud_url: str, device_token: str, device_id: str = ""
    ) -> None:
        """Start the relay bridge as a background task."""
        if ws_connect is None:
            raise RuntimeError(
                "websockets package not installed — run: pip install websockets"
            )

        # Stop any existing bridge
        await self.disconnect()

        self._creds = CloudDeviceCredentials(
            cloud_url=cloud_url,
            device_id=device_id,
            device_token=device_token,
        )
        self.status.cloud_url = cloud_url
        self.status.device_id = device_id
        self.status.state = BridgeState.CONNECTING
        self.status.last_error = ""
        self._stop_event.clear()

        self._task = asyncio.create_task(self._bridge_loop())

    async def disconnect(self) -> None:
        """Stop the bridge gracefully."""
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._ws = None
        self.status.state = BridgeState.DISCONNECTED
        self.status.connected_since = None
        self.status.models_shared = []
        self.status.reconnect_attempt = 0

    async def unlink(self) -> None:
        """Disconnect and delete saved credentials."""
        await self.disconnect()
        from ollabridge.cloud.device_config import DEFAULT_CLOUD_DEVICE_PATH

        try:
            DEFAULT_CLOUD_DEVICE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        self.status = BridgeStatus()
        self._creds = None

    # ── Internal Bridge Loop ─────────────────────────────────────────

    async def _fetch_cloud_manifest(self) -> list[dict[str, Any]]:
        """Return the admin-approved cloud manifest (enabled AND visible_cloud).

        This is the *only* source of truth for what this device advertises to
        OllaBridge Cloud. It calls the local gateway's filtered manifest
        endpoint, which applies the local access model (``enabled``,
        ``visible_cloud``, ``allowed_apps``, ``allow_routing``).

        FAIL CLOSED: if the manifest cannot be built (gateway starting, error,
        etc.) we return an empty list rather than falling back to sharing
        every Ollama model. Sharing all local models to the cloud by accident
        is a privacy leak, so the safe failure is to publish nothing.
        """
        from ollabridge.core.settings import settings

        gateway_url = f"http://127.0.0.1:{settings.PORT}"
        headers: dict[str, str] = {}
        keys = [k.strip() for k in settings.API_KEYS.split(",") if k.strip()]
        if keys:
            headers["X-API-Key"] = keys[0]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{gateway_url}/admin/model-access/manifest/cloud",
                    headers=headers,
                )
                resp.raise_for_status()
            manifest = resp.json().get("models", [])
            # Only keep well-formed entries with a model id.
            return [item for item in manifest if item.get("model_id")]
        except Exception as exc:
            log.error(
                "Unable to build approved cloud model manifest (publishing "
                "nothing — failing closed): %s",
                exc,
            )
            return []

    async def _discover_models(self) -> list[str]:
        """Model ids to advertise to the cloud: admin-approved manifest only.

        Never falls back to the full Ollama model list — see
        :meth:`_fetch_cloud_manifest`. Only models an administrator has
        explicitly marked ``visible_cloud`` are published.
        """
        manifest = await self._fetch_cloud_manifest()
        return [item["model_id"] for item in manifest]

    async def _handle_request(self, ws: Any, msg: dict) -> None:
        """Handle a single chat request from OllaBridge Cloud."""
        req_id = msg.get("id", "unknown")
        op = msg.get("op", "")
        payload = msg.get("payload", {})

        log.info("Cloud request %s: op=%s model=%s", req_id, op, payload.get("model"))

        try:
            if op == "chat":
                result = await self._forward_chat(payload)
                response = {"type": "res", "id": req_id, "ok": True, "data": result}
            elif op == "models":
                models = await self._discover_models()
                response = {
                    "type": "res",
                    "id": req_id,
                    "ok": True,
                    "data": {"models": models},
                }
            elif op == "media_fetch":
                result = await self._fetch_media(payload)
                response = {"type": "res", "id": req_id, "ok": True, "data": result}
            else:
                response = {
                    "type": "res",
                    "id": req_id,
                    "ok": False,
                    "error": f"Unsupported operation: {op}",
                }
        except Exception as exc:
            log.error("Cloud request %s failed: %s", req_id, exc)
            response = {"type": "res", "id": req_id, "ok": False, "error": str(exc)}

        try:
            await ws.send(json.dumps(response))
        except Exception as exc:
            log.error("Failed to send response for %s: %s", req_id, exc)

    async def _forward_chat(self, payload: dict) -> dict:
        """Route chat to local OllaBridge gateway (which handles Ollama + HomePilot)."""
        from ollabridge.core.settings import settings

        gateway_url = f"http://127.0.0.1:{settings.PORT}"
        # X-OllaBridge-Relay marks the request as cloud-relayed so the
        # gateway's trace records show cloud_relay=true.
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-OllaBridge-Relay": "1",
        }

        # Pass through client type header if present
        client_type = payload.pop("client_type", None)
        if client_type:
            headers["X-Client-Type"] = client_type

        # Use local-trust or first API key
        keys = settings.API_KEYS.split(",")
        if keys and keys[0].strip():
            headers["X-API-Key"] = keys[0].strip()

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                f"{gateway_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def _fetch_media(self, payload: dict) -> dict:
        """Fetch media from local HomePilot and return as base64.

        Called by the cloud via relay when it needs to serve media that
        is only accessible from the local network (HomePilot behind NAT).

        Args:
            payload: {"path": "files/projects/.../image.png", "max_size_mb": 10}

        Returns:
            {"content": "<base64>", "mime_type": "image/png", "size_bytes": 12345}
        """
        import base64

        media_path = payload.get("path", "")
        max_size = int(payload.get("max_size_mb", 10)) * 1024 * 1024

        if not media_path:
            raise ValueError("Missing 'path' in media_fetch payload")

        if ".." in media_path:
            raise ValueError("Invalid path")

        # Fetch from local OllaBridge gateway's media proxy (which reaches HomePilot)
        from ollabridge.core.settings import settings

        gateway_url = f"http://127.0.0.1:{settings.PORT}"
        url = f"{gateway_url}/v1/media/proxy/{media_path}"

        headers: dict[str, str] = {}
        keys = settings.API_KEYS.split(",")
        if keys and keys[0].strip():
            headers["X-API-Key"] = keys[0].strip()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            if len(resp.content) > max_size:
                raise ValueError(f"File exceeds {max_size // 1024 // 1024}MB limit")

            mime_type = resp.headers.get("content-type", "application/octet-stream")

            return {
                "content": base64.b64encode(resp.content).decode(),
                "mime_type": mime_type,
                "size_bytes": len(resp.content),
            }

    async def _bridge_loop(self) -> None:
        """Main bridge loop with auto-reconnect."""
        if not self._creds:
            return

        attempt = 0
        raw_url = self._creds.cloud_url.rstrip("/")

        # Build WebSocket relay URL from any input format
        # http://host:port → ws://host:port/relay/connect
        # https://host → wss://host/relay/connect
        # ws://host/relay/connect → ws://host/relay/connect (as-is)
        if raw_url.endswith("/relay/connect"):
            ws_url = raw_url
        else:
            # Strip scheme to get host:port
            for prefix in ("wss://", "ws://", "https://", "http://"):
                if raw_url.startswith(prefix):
                    host_part = raw_url[len(prefix):]
                    scheme = "wss" if prefix in ("wss://", "https://") else "ws"
                    break
            else:
                host_part = raw_url
                scheme = "ws"
            # Remove any trailing path
            host_part = host_part.split("/")[0]
            ws_url = f"{scheme}://{host_part}/relay/connect"

        log.info("Cloud relay URL resolved: %s", ws_url)

        while not self._stop_event.is_set():
            try:
                self.status.state = (
                    BridgeState.CONNECTING if attempt == 0 else BridgeState.RECONNECTING
                )
                self.status.reconnect_attempt = attempt

                log.info("Connecting to cloud relay: %s (attempt %d)", ws_url, attempt)

                connect_options = connection_options(
                    ws_connect,
                    headers={"Authorization": f"Bearer {self._creds.device_token}"},
                    ping_interval=PING_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                    proxy=None,
                )
                async with ws_connect(ws_url, **connect_options) as ws:
                    self._ws = ws
                    attempt = 0
                    self.status.state = BridgeState.CONNECTED
                    self.status.connected_since = time.time()
                    self.status.last_error = ""

                    # Discover and register models (approved manifest only)
                    manifest = await self._fetch_cloud_manifest()
                    models = [item["model_id"] for item in manifest]
                    self.status.models_shared = models

                    hello = {
                        "type": "hello",
                        "models": models,
                        # Structured manifest so the cloud can enforce the
                        # richer local policy (allowed_apps / allow_routing)
                        # rather than re-deriving it from the flat name list.
                        "published_models": manifest,
                        "capabilities": ["chat", "models", "media_fetch"],
                        "client_version": "ollabridge-gateway-1.0",
                        "platform": sys.platform,
                    }
                    catalog_manifest = self._build_catalog_manifest()
                    if catalog_manifest is not None:
                        hello["local_catalog"] = catalog_manifest
                    self._ws = ws
                    await ws.send(json.dumps(hello))
                    log.info(
                        "Registered %d models with cloud: %s",
                        len(models),
                        models[:8],
                    )

                    # Start periodic model refresh
                    refresh_task = asyncio.create_task(
                        self._model_refresh_loop(ws)
                    )

                    try:
                        async for raw in ws:
                            if self._stop_event.is_set():
                                break
                            try:
                                msg = json.loads(raw)
                            except json.JSONDecodeError:
                                continue

                            mtype = msg.get("type")
                            if mtype == "pong":
                                continue
                            if mtype == "req":
                                asyncio.create_task(self._handle_request(ws, msg))
                    finally:
                        refresh_task.cancel()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                # A 4401/4403 close means the cloud rejected our device token:
                # the device was unlinked or its access was revoked in
                # OllaBridge Cloud (or the token is stale). Retrying can never
                # succeed with the same token, so stop the reconnect loop and
                # surface an actionable status instead of spamming the log.
                if _is_auth_rejection(exc):
                    log.error(
                        "Cloud rejected the device token — this device was "
                        "unlinked or its access revoked in OllaBridge Cloud. "
                        "Stopping reconnect; re-pair to reconnect.",
                    )
                    self.status.state = BridgeState.ERROR
                    self.status.last_error = (
                        "Device unlinked from OllaBridge Cloud (access revoked). "
                        "Re-pair from the dashboard to reconnect."
                    )
                    self._ws = None
                    break
                log.warning("Cloud bridge error: %s", exc)
                self.status.last_error = str(exc)

            if self._stop_event.is_set():
                break

            # Reconnect with exponential backoff
            delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
            self.status.state = BridgeState.RECONNECTING
            log.info("Reconnecting in %ds...", delay)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                break  # stop_event was set during the wait
            except asyncio.TimeoutError:
                pass  # timeout expired, continue reconnecting

            attempt += 1

        self._ws = None
        self.status.state = BridgeState.DISCONNECTED
        self.status.connected_since = None

    async def _send_model_update(self, ws: Any) -> list[str]:
        """Push the current approved manifest to the cloud over *ws*."""
        manifest = await self._fetch_cloud_manifest()
        models = [item["model_id"] for item in manifest]
        self.status.models_shared = models
        hello = {
            "type": "hello",
            "models": models,
            "published_models": manifest,
            "capabilities": ["chat", "models", "media_fetch"],
            "client_version": "ollabridge-gateway-1.0",
            "platform": sys.platform,
        }
        await ws.send(json.dumps(hello))
        return models

    async def refresh_models_now(self) -> list[str]:
        """Re-publish the approved manifest immediately.

        Call this right after an administrator changes ``visible_cloud`` (or
        any access flag) so the cloud selector updates within seconds instead
        of waiting up to five minutes for the periodic refresh. No-op when the
        bridge is not currently connected.
        """
        ws = self._ws
        if ws is None or self.status.state != BridgeState.CONNECTED:
            return self.status.models_shared
        try:
            models = await self._send_model_update(ws)
            log.info("Re-published approved models to cloud: %s", models[:8])
            return models
        except Exception as exc:
            log.warning("refresh_models_now failed: %s", exc)
            return self.status.models_shared

    async def _model_refresh_loop(self, ws: Any, interval: int = 300) -> None:
        """Periodically re-publish the approved manifest to the cloud."""
        while True:
            await asyncio.sleep(interval)
            try:
                models = await self._send_model_update(ws)
                log.info("Refreshed models with cloud: %s", models[:8])
            except Exception:
                break
