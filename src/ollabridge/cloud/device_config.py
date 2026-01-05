from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ollabridge.core.settings import settings


DEFAULT_CLOUD_DEVICE_PATH: Path = settings.DATA_DIR / "cloud_device.json"


@dataclass(frozen=True)
class CloudDeviceCredentials:
    cloud_url: str
    device_id: str
    device_token: str


def load_cloud_device_credentials(path: Path | None = None) -> Optional[CloudDeviceCredentials]:
    p = path or DEFAULT_CLOUD_DEVICE_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cloud_url = (data.get("cloud_url") or "").strip()
        device_id = (data.get("device_id") or "").strip()
        device_token = (data.get("device_token") or "").strip()
        if not (cloud_url and device_id and device_token):
            return None
        return CloudDeviceCredentials(cloud_url=cloud_url, device_id=device_id, device_token=device_token)
    except Exception:
        return None


def save_cloud_device_credentials(creds: CloudDeviceCredentials, path: Path | None = None) -> Path:
    p = path or DEFAULT_CLOUD_DEVICE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "cloud_url": creds.cloud_url,
                "device_id": creds.device_id,
                "device_token": creds.device_token,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    # Best-effort: tighten permissions on unix
    try:
        p.chmod(0o600)
    except Exception:
        pass
    return p
