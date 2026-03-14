"""Device-pairing authentication for OllaBridge.

Flow:
  1. Gateway starts in AUTH_MODE=pairing and prints a short-lived code to the console.
  2. Client POSTs the code to /pair with a friendly label.
  3. Gateway returns a persistent bearer token (mtx_<random>).
  4. Client stores the token and uses it for all subsequent requests.
  5. Tokens are SHA-256 hashed before storage (only the client has the raw token).
  6. Tokens can be revoked via /pair/revoke.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import string
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge.pairing")


@dataclass
class PairingCode:
    """A short-lived code displayed in the gateway console."""

    code: str
    created_at: float
    ttl: int  # seconds

    @property
    def expired(self) -> bool:
        return time.time() > self.created_at + self.ttl


@dataclass
class PairedDevice:
    """A device that has been paired."""

    device_id: str
    label: str
    token_hash: str  # SHA-256 of raw token
    paired_at: float


class PairingManager:
    """Manages pairing codes and paired-device tokens."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir or settings.DATA_DIR
        self._tokens_file = self._data_dir / "pair_tokens.json"
        self._current_code: Optional[PairingCode] = None
        self._devices: dict[str, PairedDevice] = {}
        self._load()

    # ------------------------------------------------------------------
    # Code lifecycle
    # ------------------------------------------------------------------

    def generate_code(self) -> PairingCode:
        """Generate (or refresh) the pairing code displayed in the console."""
        charset = string.digits
        code = "".join(secrets.choice(charset) for _ in range(settings.PAIRING_CODE_LENGTH))
        self._current_code = PairingCode(
            code=code,
            created_at=time.time(),
            ttl=settings.PAIRING_CODE_TTL_SECONDS,
        )
        log.info("New pairing code generated (expires in %ds)", settings.PAIRING_CODE_TTL_SECONDS)
        return self._current_code

    @property
    def current_code(self) -> Optional[PairingCode]:
        if self._current_code and self._current_code.expired:
            self._current_code = None
        return self._current_code

    # ------------------------------------------------------------------
    # Pairing exchange
    # ------------------------------------------------------------------

    def exchange(self, code: str, label: str = "device") -> Optional[str]:
        """Exchange a valid pairing code for a persistent bearer token.

        Returns the raw token string on success, or None on failure.
        """
        active = self.current_code
        if active is None or code != active.code:
            return None

        # Consume the code (single-use)
        self._current_code = None

        # Generate token
        raw_token = f"{settings.PAIRING_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        token_hash = self._hash(raw_token)
        device_id = f"dev-{secrets.token_hex(4)}"

        self._devices[device_id] = PairedDevice(
            device_id=device_id,
            label=label,
            token_hash=token_hash,
            paired_at=time.time(),
        )
        self._save()
        log.info("Device paired: %s (%s)", device_id, label)
        return raw_token

    # ------------------------------------------------------------------
    # Token validation
    # ------------------------------------------------------------------

    def validate_token(self, raw_token: str) -> bool:
        """Check if a raw bearer token matches any paired device."""
        h = self._hash(raw_token)
        return any(d.token_hash == h for d in self._devices.values())

    def get_device_for_token(self, raw_token: str) -> Optional[str]:
        """Return the device_id for a valid paired token, or None."""
        h = self._hash(raw_token)
        for d in self._devices.values():
            if d.token_hash == h:
                return d.device_id
        return None

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, device_id: str) -> bool:
        """Revoke a paired device by ID."""
        if device_id in self._devices:
            del self._devices[device_id]
            self._save()
            log.info("Device revoked: %s", device_id)
            return True
        return False

    def list_devices(self) -> list[dict]:
        """Return a summary of all paired devices (no secrets)."""
        return [
            {
                "device_id": d.device_id,
                "label": d.label,
                "paired_at": d.paired_at,
            }
            for d in self._devices.values()
        ]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "devices": {
                did: {
                    "device_id": d.device_id,
                    "label": d.label,
                    "token_hash": d.token_hash,
                    "paired_at": d.paired_at,
                }
                for did, d in self._devices.items()
            }
        }
        self._tokens_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._tokens_file.exists():
            return
        try:
            data = json.loads(self._tokens_file.read_text(encoding="utf-8"))
            for did, info in data.get("devices", {}).items():
                self._devices[did] = PairedDevice(
                    device_id=info["device_id"],
                    label=info.get("label", "device"),
                    token_hash=info["token_hash"],
                    paired_at=info.get("paired_at", 0),
                )
        except Exception as e:
            log.warning("Failed to load pair tokens: %s", e)

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()
