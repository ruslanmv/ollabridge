from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


@dataclass(frozen=True)
class DeviceStart:
    user_code: str
    device_code: str
    verification_url: str
    expires_in: int


@dataclass(frozen=True)
class DevicePollApproved:
    device_id: str
    device_token: str


@dataclass(frozen=True)
class DevicePoll:
    status: str  # pending|approved|expired
    approved: Optional[DevicePollApproved] = None


class CloudApiClient:
    """
    Minimal HTTP client for OllaBridge Cloud device pairing endpoints:
      - POST /device/start
      - POST /device/poll
    """

    def __init__(self, cloud_url: str, timeout: float = 30.0) -> None:
        self.cloud_url = cloud_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def device_start(self) -> DeviceStart:
        r = self._client.post(_join(self.cloud_url, "/device/start"), json={})
        r.raise_for_status()
        data = r.json()
        return DeviceStart(
            user_code=str(data["user_code"]),
            device_code=str(data["device_code"]),
            verification_url=str(data["verification_url"]),
            expires_in=int(data.get("expires_in") or 0),
        )

    def device_poll(self, device_code: str) -> DevicePoll:
        r = self._client.post(_join(self.cloud_url, "/device/poll"), json={"device_code": device_code})
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        status = str(data.get("status") or "pending")
        if status == "approved":
            device_id = data.get("device_id")
            device_token = data.get("device_token")
            if device_id and device_token:
                return DevicePoll(status="approved", approved=DevicePollApproved(device_id=str(device_id), device_token=str(device_token)))
        return DevicePoll(status=status, approved=None)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
