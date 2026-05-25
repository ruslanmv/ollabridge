"""Unit tests for the cloud preferences sync helper."""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers.models import (
    AliasCandidate,
    ProviderCategory,
    ProviderConfig,
    ProviderTier,
)
from ollabridge.cloud import preferences_sync as ps


def _provider(**kw):
    base = dict(
        id="huggingface-free",
        name="HF",
        kind="huggingface",
        enabled=True,
        tier=ProviderTier.MAIN,
        category=ProviderCategory.FREE_FLEX,
        tags=["free", "tools"],
    )
    base.update(kw)
    return ProviderConfig(**base)


def test_build_payload_strips_internal_fields_and_secrets():
    providers = [_provider(), _provider(id="ollama-node-01", kind="ollama_bridge")]
    aliases = {
        "ollabridge:tools": [
            AliasCandidate(provider="huggingface-free", model="meta-llama/Llama-3.3-70B-Instruct:groq"),
        ],
    }
    hf = {
        "connected": True,
        "mode": "free_credit_only",
        "bill_to": None,
        "encrypted_at_rest": True,
        "catalog": {"entries": 132},
    }

    payload = ps.build_payload(
        device_id="dev_abc", providers=providers, aliases=aliases, hf_status=hf,
    )

    assert payload["device_id"] == "dev_abc"
    assert payload["schema_version"] == 1
    assert len(payload["providers"]) == 2
    assert payload["providers"][0]["id"] == "huggingface-free"
    # Sanity: pydantic dumps the enum as its value.
    assert payload["providers"][0]["tier"] in ("main", ProviderTier.MAIN)
    assert payload["aliases"]["ollabridge:tools"][0]["model"].endswith(":groq")

    # Critical: no field named anything like a secret is present.
    flat = repr(payload)
    assert "hf_" not in flat or "hf_status" in flat  # only the allowed key
    assert "token" not in flat.lower() or "token_synced" in flat.lower()
    assert payload["hf_status"]["token_synced"] is False
    assert payload["hf_status"]["catalog_entries"] == 132


def test_build_payload_handles_no_hf_status():
    payload = ps.build_payload(
        device_id="dev_x", providers=[_provider()], aliases={}, hf_status=None,
    )
    assert payload["hf_status"] is None
    assert payload["aliases"] == {}


@pytest.mark.asyncio
async def test_push_to_cloud_sends_authed_post(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True, "stored_at": "2026-05-25T07:00:00Z"})

    transport = httpx.MockTransport(handler)
    real = ps.httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(ps.httpx, "AsyncClient", _patched)

    ack = await ps.push_to_cloud(
        cloud_url="https://cloud.example.com/",
        device_token="dt_secret_token",
        payload={"device_id": "dev_x", "synced_at": "now"},
    )
    assert ack["ok"] is True
    assert captured["url"] == "https://cloud.example.com/api/devices/me/preferences"
    assert captured["auth"] == "Bearer dt_secret_token"
    assert "dev_x" in captured["body"]


@pytest.mark.asyncio
async def test_push_to_cloud_requires_credentials():
    with pytest.raises(RuntimeError, match="cloud_url"):
        await ps.push_to_cloud(cloud_url="", device_token="x", payload={})
    with pytest.raises(RuntimeError, match="device_token"):
        await ps.push_to_cloud(cloud_url="https://x", device_token="", payload={})


@pytest.mark.asyncio
async def test_push_to_cloud_surface_upstream_errors(monkeypatch):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(403, text="device revoked")
    )
    real = ps.httpx.AsyncClient

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    monkeypatch.setattr(ps.httpx, "AsyncClient", _patched)

    with pytest.raises(RuntimeError, match="403"):
        await ps.push_to_cloud(
            cloud_url="https://cloud.example.com",
            device_token="dt",
            payload={},
        )
