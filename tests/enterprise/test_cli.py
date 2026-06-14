"""CLI tests via typer's CliRunner — no network, no real keys."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from typer.testing import CliRunner

from ollabridge.cli.main import app

runner = CliRunner()


# ── doctor ──────────────────────────────────────────────────────────────


def test_doctor_security_json():
    result = runner.invoke(app, ["doctor", "security", "--json"])
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["sections"][0]["name"] == "Security"
    names = [c["name"] for c in payload["sections"][0]["checks"]]
    assert "Secrets are not plaintext" in names
    assert "Prompt logging" in names


def test_doctor_cloud_without_credentials_explains_login():
    result = runner.invoke(app, ["doctor", "cloud"])
    assert result.exit_code == 1
    assert "ollabridge login" in result.stdout


def test_doctor_relay_without_credentials_explains_login():
    result = runner.invoke(app, ["doctor", "relay", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    checks = payload["sections"][0]["checks"]
    assert checks[0]["status"] == "fail"
    assert "login" in checks[0]["hint"]


def test_doctor_providers_lists_missing():
    result = runner.invoke(app, ["doctor", "providers"])
    assert "providers add" in result.stdout


# ── sync ────────────────────────────────────────────────────────────────


def test_sync_status_shows_disabled_by_default():
    result = runner.invoke(app, ["sync", "status"])
    assert result.exit_code == 0
    assert "disabled" in result.stdout


def test_sync_enable_disable_roundtrip():
    assert runner.invoke(app, ["sync", "enable"]).exit_code == 0
    out = runner.invoke(app, ["sync", "status", "--json"])
    payload = json.loads(out.stdout[out.stdout.index("{") :])
    assert payload["cloud_sync"]["enabled"] is True
    assert payload["cloud_sync"]["prompt_logging"] is False
    assert runner.invoke(app, ["sync", "disable"]).exit_code == 0
    out = runner.invoke(app, ["sync", "status", "--json"])
    payload = json.loads(out.stdout[out.stdout.index("{") :])
    assert payload["cloud_sync"]["enabled"] is False


def test_sync_config_sensitive_requires_confirmation():
    result = runner.invoke(
        app, ["sync", "config", "prompt_logging", "true"], input="n\n"
    )
    assert "sensitive" in result.stdout
    out = runner.invoke(app, ["sync", "status", "--json"])
    payload = json.loads(out.stdout[out.stdout.index("{") :])
    assert payload["cloud_sync"]["prompt_logging"] is False


def test_sync_config_rejects_unknown_field():
    result = runner.invoke(app, ["sync", "config", "bogus_field", "true"])
    assert result.exit_code == 1


def test_sync_push_requires_pairing():
    result = runner.invoke(app, ["sync", "push"])
    assert result.exit_code == 1
    assert "login" in result.stdout


# ── providers ───────────────────────────────────────────────────────────


def test_providers_add_and_list_redacts_key():
    key = "gsk_verysecretkey1234567890"
    result = runner.invoke(
        app, ["providers", "add", "groq", "--api-key", key, "--storage", "1"]
    )
    assert result.exit_code == 0
    assert key not in result.stdout
    listed = runner.invoke(app, ["providers", "list"])
    assert key not in listed.stdout
    assert "groq" in listed.stdout


def test_providers_add_unknown_provider_fails():
    result = runner.invoke(
        app, ["providers", "add", "fakeai", "--api-key", "x", "--storage", "1"]
    )
    assert result.exit_code == 1


def test_providers_add_cloud_vault_mode_is_honest():
    result = runner.invoke(
        app,
        [
            "providers",
            "add",
            "openai",
            "--api-key",
            "sk-test1234567890123456",
            "--storage",
            "2",
        ],
    )
    assert result.exit_code == 0
    assert "LOCAL-ONLY" in result.stdout  # not paired → key stays local


def test_providers_test_uses_mock(monkeypatch):
    runner.invoke(
        app,
        ["providers", "add", "groq", "--api-key", "gsk_k1234567890", "--storage", "1"],
    )

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(200, text="{}", request=httpx.Request("GET", url))

    with patch("ollabridge.provider_ops.httpx.get", fake_get):
        result = runner.invoke(app, ["providers", "test", "groq"])
    assert result.exit_code == 0
    assert "key valid" in result.stdout


def test_providers_remove():
    runner.invoke(
        app,
        ["providers", "add", "groq", "--api-key", "gsk_k1234567890", "--storage", "1"],
    )
    result = runner.invoke(app, ["providers", "remove", "groq", "--yes"])
    assert result.exit_code == 0
    listed = runner.invoke(app, ["providers", "list"])
    assert "No providers configured" in listed.stdout


def test_providers_export_requires_redacted_flag():
    assert runner.invoke(app, ["providers", "export"]).exit_code == 1


def test_providers_export_redacted_has_no_keys():
    key = "sk-ant-topsecret12345678901234"
    runner.invoke(
        app, ["providers", "add", "anthropic", "--api-key", key, "--storage", "1"]
    )
    result = runner.invoke(app, ["providers", "export", "--redacted"])
    assert result.exit_code == 0
    assert key not in result.stdout
    assert "anthropic" in result.stdout


# ── policies / route ────────────────────────────────────────────────────


def test_policies_validate_ok_without_file():
    result = runner.invoke(app, ["policies", "validate"])
    assert result.exit_code == 0


def test_policies_validate_bad_file(ollabridge_home):
    (ollabridge_home / "policies.yaml").write_text("policies: [", encoding="utf-8")
    result = runner.invoke(app, ["policies", "validate"])
    assert result.exit_code == 1


def test_policies_list_shows_builtins():
    result = runner.invoke(app, ["policies", "list"])
    assert "local-private" in result.stdout or "local-priv" in result.stdout


def test_route_explain_json_offline(monkeypatch):
    from ollabridge.policies import RouteContext

    monkeypatch.setattr(
        "ollabridge.policies.engine.gather_route_context",
        lambda: RouteContext(local_models=["llama3.1:8b"], local_device_name="Test PC"),
    )
    result = runner.invoke(app, ["route", "explain", "local-private", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["selected_backend"] == "local_device"
    assert payload["prompt_logging"] is False


def test_policies_explain_unknown_alias():
    result = runner.invoke(app, ["policies", "explain", "no-such-alias"])
    assert result.exit_code == 1


# ── traces ──────────────────────────────────────────────────────────────


def test_traces_list_empty():
    result = runner.invoke(app, ["traces", "list"])
    assert result.exit_code == 0
    assert "No traces recorded" in result.stdout


def test_traces_show_and_list():
    from ollabridge.tracing import TraceRecord, get_trace_store

    rec = TraceRecord(requested_model="coding", resolved_model="qwen2.5", latency_ms=5)
    get_trace_store().record(rec)
    listed = runner.invoke(app, ["traces", "list"])
    assert "qwen2.5" in listed.stdout
    shown = runner.invoke(app, ["traces", "show", rec.request_id])
    assert shown.exit_code == 0
    assert rec.request_id in shown.stdout


def test_traces_show_missing():
    result = runner.invoke(app, ["traces", "show", "req_nonexistent"])
    assert result.exit_code == 1


# ── login / logout ──────────────────────────────────────────────────────


def test_logout_when_not_paired():
    result = runner.invoke(app, ["logout", "--yes"])
    assert "Not paired" in result.stdout


def test_login_flow_with_mocked_cloud(monkeypatch):
    from ollabridge.cloud import api_client as ac

    class FakeClient:
        def __init__(self, cloud_url, timeout=30.0):
            self.cloud_url = cloud_url

        def device_start(self):
            return ac.DeviceStart(
                user_code="ABCD-1234",
                device_code="devcode",
                verification_url="https://cloud.example/link",
                expires_in=600,
            )

        def device_poll(self, device_code):
            return ac.DevicePoll(
                status="approved",
                approved=ac.DevicePollApproved(
                    device_id="dev_test1", device_token="dvt_token1234567890"
                ),
            )

        def close(self):
            pass

    monkeypatch.setattr("ollabridge.cli.cloud_login.CloudApiClient", FakeClient)

    result = runner.invoke(app, ["login", "--cloud", "https://cloud.example"])
    assert result.exit_code == 0, result.stdout
    assert "ABCD-1234" in result.stdout
    assert "Device paired" in result.stdout
    assert "dvt_token1234567890" not in result.stdout  # token never printed
    # Login enabled metadata sync, sensitive flags stayed off.
    from ollabridge.cloud.sync_config import load_sync_config

    cfg = load_sync_config()
    assert cfg.enabled is True
    assert cfg.prompt_logging is False
    assert cfg.provider_secrets_cloud_vault is False
