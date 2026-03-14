"""Bridge session mapping — reconnects VR devices to HomePilot conversations.

This is a lightweight mapping layer, NOT a memory engine. HomePilot owns
sessions and Memory V2. OllaBridge only maps (device_id, model) → the
HomePilot conversation_id so that restarting the Quest or refreshing the
browser continues the same conversation lineage.

Storage: JSON file at ~/.ollabridge/sessions.json
Convention: follows the ConsumerRegistry / PairingManager pattern.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge.session_bridge")

# Sessions older than 24 hours are considered expired
_SESSION_TTL_SECONDS = 86_400


@dataclass
class BridgeSession:
    """A single device+model → conversation mapping."""

    device_id: str
    model: str
    bridge_session_id: str
    homepilot_conversation_id: str
    last_active: float

    @property
    def expired(self) -> bool:
        return time.time() - self.last_active > _SESSION_TTL_SECONDS

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "model": self.model,
            "bridge_session_id": self.bridge_session_id,
            "homepilot_conversation_id": self.homepilot_conversation_id,
            "last_active": self.last_active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BridgeSession":
        return cls(
            device_id=d["device_id"],
            model=d["model"],
            bridge_session_id=d.get("bridge_session_id", ""),
            homepilot_conversation_id=d.get("homepilot_conversation_id", ""),
            last_active=d.get("last_active", 0),
        )


def _session_key(device_id: str, model: str) -> str:
    return f"{device_id}::{model}"


class SessionBridge:
    """Thread-safe bridge-session registry.

    Stores a mapping of (device_id, model) → homepilot_conversation_id
    so that the same Quest device talking to the same persona resumes
    the same HomePilot conversation after reconnect.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir or settings.DATA_DIR
        self._store_file = self._data_dir / "sessions.json"
        self._sessions: dict[str, BridgeSession] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_session(self, device_id: str, model: str) -> Optional[BridgeSession]:
        """Look up an existing session for this device + model pair."""
        key = _session_key(device_id, model)
        sess = self._sessions.get(key)
        if sess is None:
            return None
        if sess.expired:
            del self._sessions[key]
            self._save()
            return None
        return sess

    def upsert_session(
        self,
        device_id: str,
        model: str,
        homepilot_conversation_id: str,
        bridge_session_id: Optional[str] = None,
    ) -> BridgeSession:
        """Create or update a session mapping."""
        key = _session_key(device_id, model)
        existing = self._sessions.get(key)

        if existing and not existing.expired:
            existing.homepilot_conversation_id = homepilot_conversation_id
            existing.last_active = time.time()
            self._save()
            return existing

        sess = BridgeSession(
            device_id=device_id,
            model=model,
            bridge_session_id=bridge_session_id or f"bs-{uuid.uuid4().hex[:12]}",
            homepilot_conversation_id=homepilot_conversation_id,
            last_active=time.time(),
        )
        self._sessions[key] = sess
        self._save()
        log.info("New bridge session: %s → %s", key, homepilot_conversation_id)
        return sess

    def touch_session(self, device_id: str, model: str) -> None:
        """Update last_active timestamp for a session."""
        key = _session_key(device_id, model)
        sess = self._sessions.get(key)
        if sess:
            sess.last_active = time.time()
            self._save()

    # ------------------------------------------------------------------
    # Persistence (JSON file, same pattern as ConsumerRegistry)
    # ------------------------------------------------------------------

    def _save(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": [s.to_dict() for s in self._sessions.values()],
        }
        self._store_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._store_file.exists():
            return
        try:
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            for entry in data.get("sessions", []):
                sess = BridgeSession.from_dict(entry)
                if not sess.expired:
                    key = _session_key(sess.device_id, sess.model)
                    self._sessions[key] = sess
            log.info("Loaded %d bridge session(s)", len(self._sessions))
        except Exception as e:
            log.warning("Failed to load bridge sessions: %s", e)
