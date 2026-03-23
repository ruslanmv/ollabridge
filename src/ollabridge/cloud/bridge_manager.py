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
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    try:
        from websockets.client import connect as ws_connect  # type: ignore[assignment]
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

    async def _discover_models(self) -> list[str]:
        """Discover models from the local OllaBridge gateway's own /v1/models."""
        from ollabridge.core.settings import settings

        gateway_url = f"http://127.0.0.1:{settings.PORT}"
        headers: dict[str, str] = {}
        keys = settings.API_KEYS.split(",")
        if keys and keys[0].strip():
            headers["X-API-Key"] = keys[0].strip()

        models: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{gateway_url}/v1/models", headers=headers)
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        models.append(m["id"])
        except Exception as exc:
            log.warning("Model discovery via local gateway failed: %s", exc)

            # Fallback: try Ollama directly
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(f"{self._ollama_url}/api/tags")
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            models.append(m["name"])
            except Exception:
                pass

        return models

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
        headers: dict[str, str] = {"Content-Type": "application/json"}

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

                async with ws_connect(
                    ws_url,
                    additional_headers={"Authorization": f"Bearer {self._creds.device_token}"},
                    ping_interval=PING_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                    proxy=None,
                ) as ws:
                    self._ws = ws
                    attempt = 0
                    self.status.state = BridgeState.CONNECTED
                    self.status.connected_since = time.time()
                    self.status.last_error = ""

                    # Discover and register models
                    models = await self._discover_models()
                    self.status.models_shared = models

                    hello = {
                        "type": "hello",
                        "models": models,
                        "capabilities": ["chat", "models"],
                        "client_version": "ollabridge-gateway-1.0",
                        "platform": sys.platform,
                    }
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

    async def _model_refresh_loop(self, ws: Any, interval: int = 300) -> None:
        """Periodically re-discover models and update cloud."""
        while True:
            await asyncio.sleep(interval)
            try:
                models = await self._discover_models()
                self.status.models_shared = models
                hello = {
                    "type": "hello",
                    "models": models,
                    "capabilities": ["chat", "models"],
                    "client_version": "ollabridge-gateway-1.0",
                    "platform": sys.platform,
                }
                await ws.send(json.dumps(hello))
                log.info("Refreshed models with cloud: %s", models[:8])
            except Exception:
                break
