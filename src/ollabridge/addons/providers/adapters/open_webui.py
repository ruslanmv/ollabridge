"""
Generic Open WebUI-compatible provider adapter.

Open WebUI (and compatible servers) expose an OpenAI-style surface under an
``/api`` prefix — models at ``/api/v1/models`` and chat at
``/api/v1/chat/completions`` — which the stock ``OpenAICompatibleAdapter``
(hard-coded to ``{base}/v1/...``) only reaches if the operator happens to set
``base_url`` to ``<host>/api``. This adapter is prefix-aware and additive: it
negotiates the preferred OpenAI-compat path, falls back to the legacy
non-``/v1`` path on a 404, namespaces upstream model ids so they cannot collide
with local Ollama or other providers, strips that namespace before calling
upstream, preserves the full OpenAI response object (tool calls, usage,
finish_reason), and redacts credentials from every error.

It carries no vendor name or hard-coded host: point it at any Open WebUI-style
server via ``base_url`` (the server's ``/api`` root).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ollabridge.addons.providers.adapters.oauth import OAuthClientCredentials
from ollabridge.addons.providers.base import BaseProviderAdapter
from ollabridge.addons.providers.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderTimeout,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

# OpenAI-compatible request fields we forward upstream. Unknown fields are
# dropped by default so a client cannot smuggle arbitrary parameters through.
_ALLOWED_FIELDS = frozenset({
    "temperature", "top_p", "max_tokens", "max_completion_tokens", "stop",
    "seed", "response_format", "tools", "tool_choice", "parallel_tool_calls",
    "stream", "stream_options", "user", "frequency_penalty", "presence_penalty",
})

# Map upstream ``info.meta.capabilities`` keys → our normalized flags. Only
# DECLARED capabilities are honored — never inferred from a model name.
_CAP_KEYS = {
    "vision": "vision",
    "image_generation": "image_generation",
    "tools": "tools",
    "function_calling": "tools",
    "structured_output": "structured_output",
    "structured_outputs": "structured_output",
}


class OpenWebUIAdapter(BaseProviderAdapter):
    """Adapter for any Open WebUI-compatible server."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        *,
        models_path: str = "/v1/models",
        chat_path: str = "/v1/chat/completions",
        fallback_models_path: str | None = "/models",
        fallback_chat_path: str | None = "/chat/completions",
        model_prefix: str = "openwebui",
        auth_header: str = "authorization",
        fail_closed: bool = True,
        # --- optional non-interactive auth strategies -------------------------
        # "api_key" (default): the stored secret is a long-lived API key.
        # "bearer": the stored secret is a static, externally-minted access
        #   token/JWT (its lifecycle is managed outside OllaBridge).
        # "oauth2_client_credentials": mint a short-lived token machine-to-machine
        #   from the IdP token endpoint (the stored secret is the client_secret).
        auth_strategy: str = "api_key",
        token_url: str | None = None,
        client_id: str | None = None,
        oauth_scope: str | None = None,
        oauth_audience: str | None = None,
        oauth_transport: Any = None,
    ) -> None:
        super().__init__(base_url=base_url, api_key=api_key, timeout=timeout)
        self.models_path = models_path
        self.chat_path = chat_path
        self.fallback_models_path = fallback_models_path
        self.fallback_chat_path = fallback_chat_path
        self.model_prefix = (model_prefix or "openwebui").strip("/")
        self.auth_header = (auth_header or "authorization").lower()
        self.fail_closed = fail_closed
        self.auth_strategy = (auth_strategy or "api_key").lower()
        # Remember which endpoint variant actually answered, so we negotiate once.
        self._models_endpoint: str | None = None
        self._chat_endpoint: str | None = None
        self._oauth = None
        if self.auth_strategy == "oauth2_client_credentials":
            if not (token_url and client_id and api_key):
                raise ValueError(
                    "oauth2_client_credentials requires token_url, client_id, and a "
                    "client secret (stored as the provider key)"
                )
            self._oauth = OAuthClientCredentials(
                token_url=token_url, client_id=client_id, client_secret=api_key,
                scope=oauth_scope, audience=oauth_audience, transport=oauth_transport,
            )

    # -- helpers --------------------------------------------------------------

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        """Non-auth headers only. Auth is added asynchronously via _auth_header
        because the OAuth strategy may need to mint/refresh a token."""
        headers: dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _auth_header(self) -> dict[str, str]:
        if self.auth_strategy == "oauth2_client_credentials" and self._oauth is not None:
            token = await self._oauth.get()
            return {"Authorization": f"Bearer {token}"}
        if not self.api_key:
            return {}
        # api_key / bearer: a static secret. x-api-key transport applies only to
        # the api_key strategy (a bearer token is always sent as Bearer).
        if self.auth_strategy == "api_key" and self.auth_header == "x-api-key":
            return {"x-api-key": self.api_key}
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _headers_with_auth(self, *, json_body: bool = False) -> dict[str, str]:
        headers = self._headers(json_body=json_body)
        headers.update(await self._auth_header())
        return headers

    def _on_auth_failure(self) -> None:
        # An OAuth token can be revoked/rotated server-side; drop the cache so the
        # next attempt re-mints rather than replaying a dead token.
        if self._oauth is not None:
            self._oauth.invalidate()

    def _namespace(self, upstream_id: str) -> str:
        return f"{self.model_prefix}/{upstream_id}"

    def _to_upstream_model(self, model: str) -> str:
        """Strip the local namespace before calling upstream. Accepts a bare id
        too, so a client that already passes the upstream id still works."""
        return model.removeprefix(f"{self.model_prefix}/")

    def _redact(self, text: str) -> str:
        out = text or ""
        if self.api_key:
            out = out.replace(self.api_key, "***")
        return out

    def _map_status(self, status: int, body: str) -> ProviderError:
        detail = self._redact(body)[:200]
        if status in (401, 403):
            return ProviderAuthError(f"authentication failed (HTTP {status})")
        if status in (402, 429):
            return ProviderQuotaExceeded(f"quota or rate limit (HTTP {status})")
        if status in (400, 404, 422):
            return ProviderBadRequest(f"bad request (HTTP {status}): {detail}")
        if status in (500, 502, 503, 504):
            err = ProviderUnavailable(f"upstream error (HTTP {status})")
            err.upstream_status = status
            return err
        return ProviderBadRequest(f"unexpected status HTTP {status}: {detail}")

    # -- model discovery ------------------------------------------------------

    async def list_models(self) -> list[dict]:
        """Discover the models the API-key owner can access, namespaced locally.

        Tries the preferred OpenAI-compat path, then the legacy path on a 404.
        Unknown capabilities stay ``null`` — never inferred from a model name."""
        paths = [p for p in (self.models_path, self.fallback_models_path) if p]
        last_exc: Exception | None = None
        headers = await self._headers_with_auth()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for path in paths:
                    url = f"{self.base_url}{path}"
                    try:
                        resp = await client.get(url, headers=headers)
                    except (httpx.ConnectError, httpx.ReadError) as exc:
                        last_exc = exc
                        continue
                    if resp.status_code == 404 and path != paths[-1]:
                        continue  # negotiate: try the legacy path
                    if resp.status_code in (401, 403):
                        # A real auth failure must NOT surface stale models.
                        self._on_auth_failure()
                        raise self._map_status(resp.status_code, resp.text)
                    if resp.status_code != 200:
                        raise self._map_status(resp.status_code, resp.text)
                    self._models_endpoint = path
                    return self._normalize_models(resp.json())
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"timeout listing models: {self._redact(str(exc))}") from exc
        if last_exc is not None:
            raise ProviderUnavailable(self._redact(str(last_exc))) from last_exc
        return []

    def _normalize_models(self, payload: Any) -> list[dict]:
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        out: list[dict] = []
        seen: set[str] = set()
        for m in data or []:
            if not isinstance(m, dict):
                continue
            upstream_id = m.get("id")
            if not upstream_id or upstream_id in seen:
                continue  # dedupe upstream ids before namespacing
            seen.add(upstream_id)
            out.append(self._normalize_one(upstream_id, m))
        return out

    def _normalize_one(self, upstream_id: str, m: dict) -> dict:
        info = m.get("info") if isinstance(m.get("info"), dict) else {}
        meta = info.get("meta") if isinstance(info.get("meta"), dict) else {}
        capabilities = self._capabilities(m, meta)
        category = self._classify(m, capabilities)
        return {
            "id": self._namespace(upstream_id),
            "object": "model",
            "owned_by": self.model_prefix,
            "name": m.get("name") or upstream_id,
            "upstream_model_id": upstream_id,
            # Original owner is kept for provenance; the public owned_by is the
            # local namespace so callers group by provider.
            "upstream_owned_by": m.get("owned_by"),
            # Open WebUI catalog metadata, preserved for local filtering. These
            # are the exact signals the "Local/External" and tag filters use.
            "connection_type": m.get("connection_type"),
            "tags": self._normalize_tags(m.get("tags")),
            "description": meta.get("description"),
            "hidden": bool(meta.get("hidden")) if meta.get("hidden") is not None else None,
            "preset": bool(m.get("preset")) if m.get("preset") is not None else False,
            "pipe": m.get("pipe"),
            "action_count": len(m.get("actions") or []),
            "filter_count": len(m.get("filters") or []),
            "status": "available",
            "stale": False,
            "capabilities": capabilities,
            # Coarse persona-safety class so a picker never auto-selects a
            # non-chat pipe. Unknowns stay honest rather than being guessed.
            "category": category,
            "persona_compatible": capabilities.get("chat") is True,
        }

    @staticmethod
    def _normalize_tags(tags: Any) -> list[dict]:
        """Open WebUI returns tags as ``[{"name": ...}]``; some servers send bare
        strings. Normalize to a list of ``{"name": str}`` either way."""
        out: list[dict] = []
        for t in tags or []:
            if isinstance(t, dict) and t.get("name"):
                out.append({"name": str(t["name"])})
            elif isinstance(t, str) and t:
                out.append({"name": t})
        return out

    def _capabilities(self, m: dict, meta: dict) -> dict:
        caps: dict[str, Any] = {
            "chat": None, "tools": None, "vision": None,
            "image_generation": None, "structured_output": None,
        }
        declared = meta.get("capabilities") if isinstance(meta.get("capabilities"), dict) else {}
        for src, dst in _CAP_KEYS.items():
            if src in declared and declared[src] is not None:
                caps[dst] = bool(declared[src])
        # A plain model entry (no pipe, not a preset) is a chat LLM; a pipe or
        # preset is a workflow/tool and is NOT auto-offered as a chat model.
        is_workflow = bool(m.get("pipe")) or bool(m.get("preset"))
        if not is_workflow and caps["image_generation"] is not True:
            caps["chat"] = True
        return caps

    @staticmethod
    def _classify(m: dict, caps: dict) -> str:
        """Coarse category: chat | tools | vision | image_generation |
        preset_or_workflow | unknown."""
        if bool(m.get("pipe")) or bool(m.get("preset")):
            return "preset_or_workflow"
        if caps.get("image_generation") is True:
            return "image_generation"
        if caps.get("vision") is True:
            return "vision"
        if caps.get("tools") is True:
            return "tools"
        if caps.get("chat") is True:
            return "chat"
        return "unknown"

    @staticmethod
    def filter_models(
        models: list[dict],
        *,
        connection_type: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        persona_compatible: bool | None = None,
    ) -> list[dict]:
        """Reproduce the Open WebUI-style views (All / Local / External / by-tag)
        plus persona-safety categories over an already-normalized list. Pure and
        side-effect free, so the dashboard, the gateway, and a persona picker all
        filter the same catalog identically."""
        out = models
        if connection_type is not None:
            out = [m for m in out if m.get("connection_type") == connection_type]
        if tag is not None:
            out = [m for m in out if any(t.get("name") == tag for t in (m.get("tags") or []))]
        if category is not None:
            out = [m for m in out if m.get("category") == category]
        if persona_compatible is not None:
            out = [m for m in out if bool(m.get("persona_compatible")) == persona_compatible]
        return out

    # -- chat -----------------------------------------------------------------

    def _payload(self, upstream_model: str, messages: list[dict], kwargs: dict) -> dict:
        payload: dict[str, Any] = {"model": upstream_model, "messages": messages}
        for key in _ALLOWED_FIELDS:
            if kwargs.get(key) is not None:
                payload[key] = kwargs[key]
        payload.setdefault("stream", False)
        return payload

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        upstream_model = self._to_upstream_model(model)
        payload = self._payload(upstream_model, messages, kwargs)
        payload["stream"] = False  # this method is non-streaming; stream via stream_chat
        paths = [p for p in (self.chat_path, self.fallback_chat_path) if p]
        headers = await self._headers_with_auth(json_body=True)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for path in paths:
                    url = f"{self.base_url}{path}"
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code == 404 and path != paths[-1]:
                        continue
                    if resp.status_code in (401, 403):
                        self._on_auth_failure()
                        raise self._map_status(resp.status_code, resp.text)
                    if resp.status_code != 200:
                        raise self._map_status(resp.status_code, resp.text)
                    self._chat_endpoint = path
                    data = resp.json()
                    # Preserve the full OpenAI response; only re-label the public
                    # model so the caller sees the namespaced id it asked for.
                    if isinstance(data, dict):
                        data["model"] = model
                    return data
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"chat timeout: {self._redact(str(exc))}") from exc
        except (httpx.ConnectError, httpx.ReadError) as exc:
            raise ProviderUnavailable(self._redact(str(exc))) from exc
        # No path returned 200 (all 404) — fail closed rather than reroute.
        raise ProviderBadRequest("no compatible chat endpoint (404 on all known paths)")

    async def health_check(self) -> bool:
        try:
            models = await self.list_models()
            return isinstance(models, list)
        except Exception:  # noqa: BLE001 - health is best-effort
            return False
