"""Explicit, consent-based cloud sync configuration.

Stored at ``~/.ollabridge/sync.yaml``. The defaults implement the OllaBridge
privacy contract:

* Safe **metadata** (device status, model names, routing profiles, health
  metrics without prompt content) syncs only after the user logs in to
  OllaBridge Cloud — and even then only while ``enabled: true``.
* **Sensitive data** (prompt content, conversation history, provider secrets,
  RAG documents, persona memory) NEVER syncs unless the user flips the
  corresponding flag explicitly. There is no code path that enables these
  flags automatically.

See ``docs/CLOUD_SYNC.md`` and ``docs/PRIVACY.md``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ollabridge.core import paths

# Fields that are safe metadata (sync allowed once cloud sync is enabled).
METADATA_FIELDS = (
    "device_status",
    "model_metadata",
    "routing_profiles",
    "health_metrics",
)

# Fields that carry sensitive content; default False, never auto-enabled.
SENSITIVE_FIELDS = (
    "conversation_history",
    "prompt_logging",
    "provider_secrets_cloud_vault",
    "rag_documents",
    "persona_memory",
)


class CloudSyncConfig(BaseModel):
    """The ``cloud_sync`` block of ``~/.ollabridge/sync.yaml``."""

    enabled: bool = False

    # Safe metadata (on by default *once sync is enabled*)
    device_status: bool = True
    model_metadata: bool = True
    routing_profiles: bool = True
    health_metrics: bool = True

    # Sensitive — explicit opt-in only
    conversation_history: bool = False
    prompt_logging: bool = False
    provider_secrets_cloud_vault: bool = False
    rag_documents: bool = False
    persona_memory: bool = False

    def sensitive_enabled(self) -> list[str]:
        """Names of sensitive sync categories the user opted in to."""
        return [f for f in SENSITIVE_FIELDS if getattr(self, f)]

    def summary_rows(self) -> list[tuple[str, bool, bool]]:
        """(field, value, is_sensitive) rows for status displays."""
        rows: list[tuple[str, bool, bool]] = []
        for f in METADATA_FIELDS:
            rows.append((f, getattr(self, f), False))
        for f in SENSITIVE_FIELDS:
            rows.append((f, getattr(self, f), True))
        return rows


class SyncFile(BaseModel):
    cloud_sync: CloudSyncConfig = Field(default_factory=CloudSyncConfig)


def load_sync_config(path: Path | None = None) -> CloudSyncConfig:
    """Load sync config; missing or unreadable file yields safe defaults."""
    p = path or paths.sync_file()
    if not p.exists():
        return CloudSyncConfig()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return CloudSyncConfig()
    if not isinstance(raw, dict):
        return CloudSyncConfig()
    return SyncFile.model_validate(raw).cloud_sync


def save_sync_config(config: CloudSyncConfig, path: Path | None = None) -> Path:
    p = path or paths.sync_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = SyncFile(cloud_sync=config).model_dump()
    header = (
        "# OllaBridge cloud sync configuration.\n"
        "# Metadata fields sync only while enabled: true.\n"
        "# Sensitive fields (conversation_history, prompt_logging,\n"
        "# provider_secrets_cloud_vault, rag_documents, persona_memory)\n"
        "# are NEVER enabled automatically. See docs/CLOUD_SYNC.md.\n"
    )
    p.write_text(header + yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    paths.tighten_permissions(p)
    return p
