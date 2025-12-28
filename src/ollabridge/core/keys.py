from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .settings import settings


@dataclass
class ApiKeys:
    keys: Dict[str, str]  # key_id -> key_value


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_keys() -> ApiKeys:
    data = _load(settings.KEYS_FILE)
    return ApiKeys(keys={str(k): str(v) for k, v in data.get("keys", {}).items()})


def save_keys(api_keys: ApiKeys) -> None:
    payload = {"keys": api_keys.keys}
    settings.KEYS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_key(label: str = "default") -> tuple[str, str]:
    """Create a new API key.

    Returns (key_id, key_value)
    """
    api_keys = load_keys()
    key_id = f"{label}-{secrets.token_hex(4)}"
    key_value = secrets.token_urlsafe(32)
    api_keys.keys[key_id] = key_value
    save_keys(api_keys)
    return key_id, key_value


def revoke_key(key_id: str) -> bool:
    api_keys = load_keys()
    if key_id in api_keys.keys:
        del api_keys.keys[key_id]
        save_keys(api_keys)
        return True
    return False


def validate_bearer(token: str) -> bool:
    api_keys = load_keys()
    return token in api_keys.keys.values()
