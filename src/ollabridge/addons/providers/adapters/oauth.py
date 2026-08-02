"""Non-interactive OAuth2 helper for provider adapters (generic).

A headless gateway must never drive an interactive, browser-based
authorization-code login (the "Sign in / Continue with <IdP>" flow) — that is a
human, in a browser, and its product is a *session*. The only OAuth2 grant
appropriate for a backend service is **client_credentials**: a service-account
token minted machine-to-machine from the IdP's token endpoint, with no user and
no redirect. This helper implements exactly that, generically — it works with
any OIDC/OAuth2 IdP (there is no vendor name here).

The access token is cached in memory with an expiry skew and refreshed
automatically; the client secret and the token are never logged. The httpx
transport is injectable so the flow is unit-testable without a live IdP.
"""

from __future__ import annotations

import time

import httpx

from ollabridge.addons.providers.errors import ProviderAuthError, ProviderUnavailable

# Refresh a little before the real expiry so an in-flight request never races a
# just-expired token.
_EXPIRY_SKEW_SECONDS = 60


class OAuthClientCredentials:
    """Fetches and caches an OAuth2 client-credentials access token."""

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str | None = None,
        audience: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.audience = audience
        self._transport = transport
        self._timeout = timeout
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _redact(self, text: str) -> str:
        out = text or ""
        for secret in (self.client_secret, self._token):
            if secret:
                out = out.replace(secret, "***")
        return out

    def invalidate(self) -> None:
        """Drop the cached token so the next call re-mints one (used after a
        401 from the resource server)."""
        self._token = None
        self._expires_at = 0.0

    async def get(self) -> str:
        now = time.time()
        if self._token and now < self._expires_at:
            return self._token
        return await self._fetch()

    async def _fetch(self) -> str:
        form = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            form["scope"] = self.scope
        if self.audience:
            form["audience"] = self.audience
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(
                    self.token_url,
                    data=form,
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"oauth token timeout: {self._redact(str(exc))}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"oauth token transport error: {self._redact(str(exc))}") from exc

        if resp.status_code in (400, 401, 403):
            # Bad/again client credentials → an auth error, not a retryable one.
            raise ProviderAuthError(f"oauth client-credentials rejected (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ProviderUnavailable(f"oauth token endpoint HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderUnavailable("oauth token response was not JSON") from exc

        token = data.get("access_token")
        if not token:
            raise ProviderAuthError("oauth token response had no access_token")
        expires_in = data.get("expires_in")
        ttl = int(expires_in) if isinstance(expires_in, (int, float, str)) and str(expires_in).isdigit() else 3600
        self._token = token
        self._expires_at = time.time() + max(0, ttl - _EXPIRY_SKEW_SECONDS)
        return token
