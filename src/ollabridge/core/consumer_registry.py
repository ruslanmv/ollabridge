"""ConsumerRegistry — persistent registry of consumer nodes.

Consumer nodes represent downstream clients (mobile apps, avatars, watches, etc.)
that consume LLM output from OllaBridge. This registry replaces the hardcoded
TEMPLATES pattern with a backend-driven, persistent store.

Storage: JSON file at ~/.ollabridge/consumer_nodes.json
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from ollabridge.core.settings import settings

log = logging.getLogger("ollabridge.consumers")

_STORE_FILE = settings.DATA_DIR / "consumer_nodes.json"


class ConsumerNode:
    """A single consumer node entry."""

    __slots__ = (
        "id", "name", "kind", "protocol", "description",
        "enabled", "paired_device_id", "created_at", "last_seen",
    )

    def __init__(
        self,
        *,
        id: str | None = None,
        name: str = "",
        kind: str = "custom",
        protocol: str = "WebSocket",
        description: str = "",
        enabled: bool = True,
        paired_device_id: str | None = None,
        created_at: float | None = None,
        last_seen: float | None = None,
    ) -> None:
        self.id = id or f"cn-{uuid.uuid4().hex[:12]}"
        self.name = name
        self.kind = kind
        self.protocol = protocol
        self.description = description
        self.enabled = enabled
        self.paired_device_id = paired_device_id
        self.created_at = created_at or time.time()
        self.last_seen = last_seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "protocol": self.protocol,
            "description": self.description,
            "enabled": self.enabled,
            "paired_device_id": self.paired_device_id,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsumerNode:
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            kind=data.get("kind", "custom"),
            protocol=data.get("protocol", "WebSocket"),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            paired_device_id=data.get("paired_device_id"),
            created_at=data.get("created_at"),
            last_seen=data.get("last_seen"),
        )


# Mapping from paired-device labels to consumer node kinds
_LABEL_KIND_MAP: dict[str, tuple[str, str, str]] = {
    "avatar": ("avatar", "WebSocket", "Interactive 3D avatar with voice and persona support."),
    "3d": ("avatar", "WebSocket", "Interactive 3D avatar with voice and persona support."),
    "mobile": ("mobile", "WebSocket", "Real-time AI summaries delivered to mobile."),
    "phone": ("mobile", "WebSocket", "Real-time AI summaries delivered to mobile."),
    "watch": ("watch", "SSE", "Context-aware LLM summaries on your wrist."),
    "wrist": ("watch", "SSE", "Context-aware LLM summaries on your wrist."),
    "web": ("web", "WebSocket", "Browser-based interface for AI interactions."),
    "browser": ("web", "WebSocket", "Browser-based interface for AI interactions."),
    "email": ("email", "Webhook", "Automated digest emails from live LLM output."),
    "mail": ("email", "Webhook", "Automated digest emails from live LLM output."),
}


def _infer_kind(label: str) -> tuple[str, str, str]:
    """Infer consumer node kind, protocol, and description from device label."""
    lower = label.lower()
    for keyword, info in _LABEL_KIND_MAP.items():
        if keyword in lower:
            return info
    return ("custom", "WebSocket", f"Consumer node from paired device: {label}")


class ConsumerRegistry:
    """Thread-safe, file-persisted consumer node registry."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or _STORE_FILE
        self._nodes: dict[str, ConsumerNode] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for entry in raw:
                node = ConsumerNode.from_dict(entry)
                self._nodes[node.id] = node
            log.info("Loaded %d consumer node(s) from %s", len(self._nodes), self._path)
        except Exception as e:
            log.warning("Failed to load consumer nodes: %s", e)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = [n.to_dict() for n in self._nodes.values()]
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning("Failed to save consumer nodes: %s", e)

    def list_all(self) -> list[ConsumerNode]:
        return list(self._nodes.values())

    def get(self, node_id: str) -> ConsumerNode | None:
        return self._nodes.get(node_id)

    def add(self, node: ConsumerNode) -> ConsumerNode:
        self._nodes[node.id] = node
        self._save()
        log.info("Added consumer node %s (%s)", node.id, node.name)
        return node

    def update(self, node_id: str, patch: dict[str, Any]) -> ConsumerNode | None:
        node = self._nodes.get(node_id)
        if node is None:
            return None
        allowed = ("name", "kind", "protocol", "description", "enabled", "paired_device_id")
        for key in allowed:
            if key in patch:
                setattr(node, key, patch[key])
        self._save()
        return node

    def remove(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        self._save()
        log.info("Removed consumer node %s", node_id)
        return True

    def touch(self, node_id: str) -> None:
        """Update last_seen timestamp."""
        node = self._nodes.get(node_id)
        if node:
            node.last_seen = time.time()
            self._save()

    def find_by_device(self, device_id: str) -> ConsumerNode | None:
        for node in self._nodes.values():
            if node.paired_device_id == device_id:
                return node
        return None

    def ensure_from_pair(self, device_id: str, label: str) -> ConsumerNode:
        """Create a consumer node from a paired device if one doesn't exist."""
        existing = self.find_by_device(device_id)
        if existing is not None:
            existing.last_seen = time.time()
            self._save()
            return existing

        kind, protocol, description = _infer_kind(label)
        node = ConsumerNode(
            name=label or "Paired Device",
            kind=kind,
            protocol=protocol,
            description=description,
            enabled=True,
            paired_device_id=device_id,
        )
        return self.add(node)
