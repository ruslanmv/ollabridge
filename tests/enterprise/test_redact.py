"""Security tests: secrets must never survive redaction."""

from __future__ import annotations

import logging

from ollabridge.core.redact import (
    RedactionFilter,
    redact_mapping,
    redact_secret,
    redact_text,
)


def test_redact_secret_keeps_short_hint():
    out = redact_secret("sk-ant-abcdef1234567890")
    assert out.startswith("sk-a")
    assert "abcdef" not in out
    assert "(redacted)" in out


def test_redact_secret_handles_empty():
    assert redact_secret(None) == "(not set)"
    assert redact_secret("") == "(not set)"
    assert "redacted" in redact_secret("ab")


def test_redact_text_scrubs_known_token_shapes():
    samples = [
        "sk-ollabridge-AbCdEf123456789012345",
        "dvt_AbCdEf123456789012345678901234567890123",
        "obt_AbCdEf123456789012345678901234567890123",
        "mtx_AbCdEf12345678",
        "sk-ant-api03-abcdef123456",
        "sk-or-v1-abcdef123456",
        "hf_AbCdEf123456",
        "gsk_AbCdEf123456",
        "AIzaSyAbCdEf12345678901234567890123456789",
        "AKIAIOSFODNN7EXAMPLE",
    ]
    for token in samples:
        scrubbed = redact_text(f"error calling provider with {token} now")
        assert token not in scrubbed, token
        assert "[REDACTED]" in scrubbed


def test_redact_text_scrubs_bearer_headers():
    out = redact_text("Authorization: Bearer supersecrettoken123")
    assert "supersecrettoken123" not in out


def test_redact_text_preserves_normal_text():
    msg = "model llama3.1:8b not found on device"
    assert redact_text(msg) == msg


def test_redact_mapping_recursively_redacts_sensitive_keys():
    data = {
        "api_key": "sk-abcdef12345678901234567890",
        "nested": {"device_token": "dvt_abc123456789", "model": "llama3"},
        "items": [{"password": "hunter2hunter2"}],
    }
    out = redact_mapping(data)
    assert "abcdef" not in str(out)
    assert "hunter2" not in str(out)
    assert out["nested"]["model"] == "llama3"


def test_logging_filter_scrubs_records(caplog):
    logger = logging.getLogger("test.redact")
    logger.addFilter(RedactionFilter())
    with caplog.at_level(logging.INFO, logger="test.redact"):
        logger.info("token is sk-ant-secret123456789")
    assert "secret123456789" not in caplog.text
    assert "[REDACTED]" in caplog.text
