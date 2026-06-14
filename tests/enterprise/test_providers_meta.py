"""BYOK provider metadata and operations: storage, redaction, health tests."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from ollabridge.addons.providers.secret_store import SecretStore
from ollabridge.core import paths
from ollabridge.provider_ops import (
    export_redacted,
    get_secret,
    rotate_secret,
    set_secret,
)
from ollabridge.provider_ops import test_provider as probe_provider
from ollabridge.providers_meta import (
    PROVIDER_CATALOG,
    ProviderRecord,
    configured_provider_names,
    load_providers,
    upsert_record,
)

REQUIRED_PROVIDERS = [
    "openai",
    "anthropic",
    "gemini",
    "azure-openai",
    "bedrock",
    "groq",
    "openrouter",
    "huggingface",
    "deepseek",
    "mistral",
    "together",
    "fireworks",
    "custom",
]


def test_catalog_covers_required_providers():
    for name in REQUIRED_PROVIDERS:
        assert name in PROVIDER_CATALOG, name


def test_providers_yaml_never_contains_secret(ollabridge_home):
    set_secret("groq", "gsk_supersecret1234567890")
    upsert_record(ProviderRecord(name="groq", kind="groq"))
    text = paths.providers_file().read_text(encoding="utf-8")
    assert "gsk_supersecret" not in text
    assert "SECRETS ARE NEVER STORED IN THIS FILE" in text


def test_secret_store_is_encrypted_with_olla_secret(ollabridge_home):
    set_secret("openai", "sk-verysecretvalue1234567890")
    raw = (ollabridge_home / "secrets.enc").read_text(encoding="utf-8")
    assert "sk-verysecretvalue" not in raw


def test_get_secret_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "env-key-123")
    assert get_secret("mistral") == "env-key-123"


def test_configured_provider_names(monkeypatch):
    set_secret("groq", "gsk_x1234567890")
    upsert_record(ProviderRecord(name="groq", kind="groq"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env12345678901234567890")
    names = configured_provider_names()
    assert "groq" in names
    assert "openai" in names
    assert "anthropic" not in names


def test_rotate_stamps_rotation_time():
    set_secret("deepseek", "sk-old1234567890")
    upsert_record(ProviderRecord(name="deepseek", kind="deepseek"))
    rec = rotate_secret("deepseek", "sk-new1234567890")
    assert rec.rotated_at is not None
    assert get_secret("deepseek") == "sk-new1234567890"


def test_export_redacted_never_leaks_keys():
    set_secret("anthropic", "sk-ant-supersecret123456")
    upsert_record(ProviderRecord(name="anthropic", kind="anthropic"))
    out = export_redacted()
    assert "supersecret" not in str(out)
    entry = out["providers"][0]
    assert entry["key_configured"] is True
    assert entry["key"].startswith("sk-a")


# ── test_provider with mocked HTTP ──────────────────────────────────────


def _mock_get(status_code: int, text: str = "{}"):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(status_code, text=text, request=httpx.Request("GET", url))

    return fake_get


def test_test_provider_without_key():
    ok, detail = probe_provider("groq")
    assert not ok
    assert "missing" in detail


def test_test_provider_success():
    set_secret("groq", "gsk_x1234567890")
    upsert_record(ProviderRecord(name="groq", kind="groq"))
    with patch("ollabridge.provider_ops.httpx.get", _mock_get(200)):
        ok, detail = probe_provider("groq")
    assert ok
    assert "key valid" in detail
    # record was updated
    rec = [r for r in load_providers() if r.name == "groq"][0]
    assert rec.last_test_ok is True


def test_test_provider_rejected_key():
    set_secret("openai", "sk-bad12345678901234567890")
    upsert_record(ProviderRecord(name="openai", kind="openai"))
    with patch("ollabridge.provider_ops.httpx.get", _mock_get(401)):
        ok, detail = probe_provider("openai")
    assert not ok
    assert "rejected" in detail


def test_test_provider_quota_failure():
    set_secret("openai", "sk-quota345678901234567890")
    upsert_record(ProviderRecord(name="openai", kind="openai"))
    with patch("ollabridge.provider_ops.httpx.get", _mock_get(429)):
        ok, detail = probe_provider("openai")
    assert not ok
    assert "quota" in detail or "rate limited" in detail


def test_test_provider_error_detail_is_redacted():
    secret = "sk-ant-leakyleakyleaky123456"
    set_secret("anthropic", secret)
    upsert_record(ProviderRecord(name="anthropic", kind="anthropic"))
    with patch(
        "ollabridge.provider_ops.httpx.get",
        _mock_get(500, text=f"upstream error with {secret}"),
    ):
        ok, detail = probe_provider("anthropic")
    assert not ok
    assert secret not in detail


def test_test_provider_unknown_kind():
    ok, detail = probe_provider("nonsense-provider")
    assert not ok and "unknown provider" in detail


def test_custom_provider_requires_base_url():
    set_secret("custom", "anykey12345678")
    upsert_record(ProviderRecord(name="custom", kind="custom", base_url=""))
    ok, detail = probe_provider("custom")
    assert not ok and "base_url" in detail


def test_secret_store_file_permissions(ollabridge_home):
    set_secret("groq", "gsk_x1234567890")
    assert paths.permissions_ok(ollabridge_home / "secrets.enc")


def test_plaintext_fallback_warns_but_works(monkeypatch, tmp_path):
    monkeypatch.delenv("OLLA_SECRET", raising=False)
    store = SecretStore(path=tmp_path / "s.enc", secret="")
    assert store.is_encrypted is False
    store.set("k", "v")
    assert store.get("k") == "v"
