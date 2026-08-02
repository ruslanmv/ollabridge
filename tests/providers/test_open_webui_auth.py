"""Optional, non-interactive auth strategies for the Open WebUI adapter.

Covers the two backend-appropriate strategies beyond a plain API key: a static
externally-minted bearer token, and OAuth2 client-credentials (mint + cache +
auto-refresh a short-lived token). The interactive authorization-code browser
flow is intentionally NOT supported by a headless adapter.
"""

from __future__ import annotations

import httpx
import pytest

from ollabridge.addons.providers.adapters import oauth as oauth_mod
from ollabridge.addons.providers.adapters import open_webui as ow_mod
from ollabridge.addons.providers.adapters.open_webui import OpenWebUIAdapter
from ollabridge.addons.providers.errors import ProviderAuthError

BASE = "https://host.example/api"


@pytest.fixture
def patch_resource(monkeypatch):
    """Patch the adapter's httpx.AsyncClient (the resource-server calls)."""
    real = ow_mod.httpx.AsyncClient

    def _apply(handler):
        transport = httpx.MockTransport(handler)

        def _patched(*a, **kw):
            # Only inject the resource transport when the caller didn't pass one,
            # so an explicitly-injected OAuth token transport is preserved
            # (both modules share the httpx module object).
            kw.setdefault("transport", transport)
            return real(*a, **kw)

        monkeypatch.setattr(ow_mod.httpx, "AsyncClient", _patched)

    return _apply


@pytest.mark.asyncio
async def test_bearer_strategy_sends_static_token(patch_resource):
    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("Authorization")
        seen["xapi"] = req.headers.get("x-api-key")
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    patch_resource(handler)
    # Even with auth_header="x-api-key", a bearer token is sent as Bearer.
    adapter = OpenWebUIAdapter(base_url=BASE, api_key="idp-jwt-xyz",
                               auth_strategy="bearer", auth_header="x-api-key")
    models = await adapter.list_models()
    assert models[0]["id"] == "openwebui/m"
    assert seen["auth"] == "Bearer idp-jwt-xyz" and seen["xapi"] is None


@pytest.mark.asyncio
async def test_oauth2_client_credentials_mints_caches_and_sends_bearer(patch_resource):
    token_calls = {"n": 0}

    def idp_handler(req):
        token_calls["n"] += 1
        form = dict(p.split("=", 1) for p in req.content.decode().split("&") if "=" in p)
        assert form["grant_type"] == "client_credentials"
        assert form["client_id"] == "cid" and form["client_secret"] == "csecret"
        return httpx.Response(200, json={"access_token": "at-123", "expires_in": 3600})

    seen = {}

    def resource_handler(req):
        seen["auth"] = req.headers.get("Authorization")
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    patch_resource(resource_handler)
    adapter = OpenWebUIAdapter(
        base_url=BASE, api_key="csecret", auth_strategy="oauth2_client_credentials",
        token_url="https://idp.example/oauth2/v1/token", client_id="cid", oauth_scope="openid",
        oauth_transport=httpx.MockTransport(idp_handler),
    )
    await adapter.list_models()
    await adapter.list_models()  # second call reuses the cached token
    assert seen["auth"] == "Bearer at-123"
    assert token_calls["n"] == 1  # minted once, then cached


@pytest.mark.asyncio
async def test_oauth2_rejected_credentials_raise_auth_error(patch_resource):
    def idp_handler(req):
        return httpx.Response(401, json={"error": "invalid_client"})

    patch_resource(lambda req: httpx.Response(200, json={"data": []}))
    adapter = OpenWebUIAdapter(
        base_url=BASE, api_key="bad", auth_strategy="oauth2_client_credentials",
        token_url="https://idp.example/token", client_id="cid",
        oauth_transport=httpx.MockTransport(idp_handler),
    )
    with pytest.raises(ProviderAuthError):
        await adapter.list_models()


@pytest.mark.asyncio
async def test_oauth_token_refetched_after_resource_401(patch_resource):
    token_calls = {"n": 0}

    def idp_handler(req):
        token_calls["n"] += 1
        return httpx.Response(200, json={"access_token": f"at-{token_calls['n']}", "expires_in": 3600})

    def resource_handler(req):
        return httpx.Response(401, text="expired")

    patch_resource(resource_handler)
    adapter = OpenWebUIAdapter(
        base_url=BASE, api_key="csecret", auth_strategy="oauth2_client_credentials",
        token_url="https://idp.example/token", client_id="cid",
        oauth_transport=httpx.MockTransport(idp_handler),
    )
    with pytest.raises(ProviderAuthError):
        await adapter.list_models()
    # The resource 401 invalidated the cache, so the next attempt re-mints.
    with pytest.raises(ProviderAuthError):
        await adapter.list_models()
    assert token_calls["n"] == 2


def test_oauth_strategy_requires_config():
    with pytest.raises(ValueError):
        OpenWebUIAdapter(base_url=BASE, api_key="secret",
                         auth_strategy="oauth2_client_credentials")  # missing token_url/client_id


@pytest.mark.asyncio
async def test_oauth_token_response_redacts_secret():
    mgr = oauth_mod.OAuthClientCredentials(
        token_url="https://idp.example/token", client_id="cid", client_secret="csecret",
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="boom csecret leak")),
    )
    with pytest.raises(Exception) as ei:
        await mgr.get()
    # Client secret never appears in the raised error.
    assert "csecret" not in str(ei.value)
