"""Sync config: privacy-safe defaults, persistence, and consent semantics."""

from __future__ import annotations

from ollabridge.cloud.sync_config import (
    SENSITIVE_FIELDS,
    CloudSyncConfig,
    load_sync_config,
    save_sync_config,
)
from ollabridge.core import paths


def test_defaults_are_privacy_safe():
    cfg = CloudSyncConfig()
    assert cfg.enabled is False
    # Metadata defaults on (but inert until enabled)
    assert cfg.device_status and cfg.model_metadata
    assert cfg.routing_profiles and cfg.health_metrics
    # Sensitive categories all off
    for field in SENSITIVE_FIELDS:
        assert getattr(cfg, field) is False, field
    assert cfg.sensitive_enabled() == []


def test_missing_file_yields_defaults():
    cfg = load_sync_config()
    assert cfg.enabled is False
    assert cfg.prompt_logging is False


def test_save_load_roundtrip():
    cfg = CloudSyncConfig(enabled=True, model_metadata=False)
    save_sync_config(cfg)
    loaded = load_sync_config()
    assert loaded.enabled is True
    assert loaded.model_metadata is False
    assert loaded.prompt_logging is False


def test_corrupt_file_yields_defaults():
    p = paths.sync_file()
    p.write_text(":::: not yaml [", encoding="utf-8")
    cfg = load_sync_config()
    assert cfg.enabled is False


def test_saved_file_has_strict_permissions():
    save_sync_config(CloudSyncConfig())
    assert paths.permissions_ok(paths.sync_file())


def test_saved_file_documents_sensitive_fields():
    p = save_sync_config(CloudSyncConfig())
    text = p.read_text(encoding="utf-8")
    assert "NEVER enabled automatically" in text
    assert "prompt_logging: false" in text
