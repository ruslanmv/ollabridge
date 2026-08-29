"""
IBM watsonx.ai adapter.

watsonx.ai is not OpenAI-compatible in two ways that matter here.

**Authentication is two-step.** The IBM Cloud API key is not a bearer
token: it is exchanged at ``https://iam.cloud.ibm.com/identity/token`` for
a short-lived IAM access token, which is what every request carries. The
token is cached on the adapter and refreshed shortly before it expires.

**The model catalog is per account.** Which foundation models exist depends
on the region, the plan and what the account has been granted, so there is
no fixed list to hard-code — ``list_models`` asks
``/ml/v1/foundation_model_specs`` and filters to the models that support
the chat API. That is the same call the ``ibm-watsonx-ai`` SDK's
``get_model_specs(filters="function_text_chat")`` makes, done over REST so
the SDK is not a dependency.

Chat additionally requires a **project id** (or a deployment **space id**);
the source's saved config supplies it, falling back to
``WATSONX_PROJECT_ID`` / ``WATSONX_SPACE_ID``.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import quote, unquote

import httpx

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

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
IAM_GRANT_TYPE = "urn:ibm:params:oauth:grant-type:apikey"

#: watsonx pins its REST contract to a date. One constant so the chat call
#: and the catalog listing can never drift onto different API versions.
WATSONX_API_VERSION = "2024-10-10"

#: Catalog filter selecting the models that support the chat API. Documented
#: syntax is a comma-separated list where ``function_*`` selects by supported
#: function; only chat models can serve ``/ml/v1/text/chat``.
CHAT_MODELS_FILTER = "function_text_chat"

DEFAULT_MAX_TOKENS = 4096

#: Refresh the cached IAM token when fewer than this many seconds remain.
_TOKEN_REFRESH_MARGIN_S = 120.0

#: watsonx paginates its catalog. A generous page size keeps discovery to a
#: single round-trip in practice, and the cap stops a pathological ``next``
#: chain from looping forever.
_PAGE_LIMIT = 200
_MAX_PAGES = 10


class WatsonxAdapter(BaseProviderAdapter):
    """Adapter for the IBM watsonx.ai text chat API."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        project_id: str | None = None,
        space_id: str | None = None,
    ):
        super().__init__(base_url, api_key, timeout)
        self.project_id = (project_id or "").strip() or None
        self.space_id = (space_id or "").strip() or None
        self._iam_token: str | None = None
        self._iam_expires_at: float = 0.0

    # ── Target resolution (project / space) ─────────────────────────

    def _scope(self) -> tuple[str, str] | None:
        """The ``(field, value)`` scoping a request, or None when unset.

        A configured project id wins over a space id; each falls back to its
        environment variable, so an exported value keeps working for a source
        that has never had one saved.
        """
        project_id = self.project_id or os.environ.get("WATSONX_PROJECT_ID", "").strip()
        if project_id:
            return "project_id", project_id
        space_id = self.space_id or os.environ.get("WATSONX_SPACE_ID", "").strip()
        if space_id:
            return "space_id", space_id
        return None

    @property
    def is_configured(self) -> bool:
        """True when this adapter has both a key and a project/space id."""
        return bool(self.has_credential and self._scope())

    # ── URLs ────────────────────────────────────────────────────────

    def _chat_url(self) -> str:
        return f"{self.base_url}/ml/v1/text/chat?version={WATSONX_API_VERSION}"

    def _models_url(self, *, start: str | None = None) -> str:
        url = (
            f"{self.base_url}/ml/v1/foundation_model_specs"
            f"?version={WATSONX_API_VERSION}"
            f"&filters={CHAT_MODELS_FILTER}&limit={_PAGE_LIMIT}"
        )
        return f"{url}&start={quote(start, safe='')}" if start else url

    @staticmethod
    def _bearer_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Errors ──────────────────────────────────────────────────────

    def _redact(self, text: str) -> str:
        out = text
        for secret in (self.api_key, self._iam_token):
            if secret:
                out = out.replace(str(secret), "(redacted)")
        return out

    def _map_status(self, status: int, body: str) -> ProviderError:
        detail = self._redact((body or "")[:300])
        if status in (401, 403):
            exc: ProviderError = ProviderAuthError(f"HTTP {status}: {detail}")
        elif status in (402, 429):
            exc = ProviderQuotaExceeded(f"HTTP {status}: {detail}")
        elif 400 <= status < 500:
            exc = ProviderBadRequest(f"HTTP {status}: {detail}")
        else:
            exc = ProviderUnavailable(f"HTTP {status}: {detail}")
        exc.upstream_status = status
        return exc

    # ── IAM token handling ──────────────────────────────────────────

    async def _get_iam_token(self) -> str:
        """A valid IAM access token, refreshed when near expiry."""
        now = time.time()
        if self._iam_token and (self._iam_expires_at - now) > _TOKEN_REFRESH_MARGIN_S:
            return self._iam_token

        if not self.api_key:
            raise ProviderAuthError(
                "watsonx: no IBM Cloud API key configured "
                "(set WATSONX_API_KEY or save one for this source)"
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    IAM_TOKEN_URL,
                    data={"grant_type": IAM_GRANT_TYPE, "apikey": self.api_key},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self._redact(f"IAM timeout: {exc}")) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                self._redact(f"IAM {type(exc).__name__}: {exc}")
            ) from exc
        if resp.status_code != 200:
            # A rejected API key is an auth failure however IAM words it.
            raise self._map_status(
                401 if resp.status_code == 400 else resp.status_code, resp.text
            )

        data = resp.json()
        self._iam_token = data["access_token"]
        self._iam_expires_at = time.time() + float(data.get("expires_in", 3600))
        return self._iam_token

    async def _get_json(self, url: str) -> dict:
        token = await self._get_iam_token()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=self._bearer_headers(token))
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self._redact(f"timeout: {exc}")) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc
        if resp.status_code != 200:
            raise self._map_status(resp.status_code, resp.text)
        return resp.json()

    # ── Response normalization ──────────────────────────────────────

    @staticmethod
    def _normalize_response(data: dict, model: str) -> dict:
        """Normalize a watsonx chat response to the OpenAI dict shape."""
        norm_choices: list[dict] = []
        for i, choice in enumerate(data.get("choices") or []):
            message = choice.get("message") or {}
            norm_choices.append(
                {
                    "index": choice.get("index", i),
                    "message": {
                        "role": message.get("role", "assistant"),
                        "content": message.get("content", "") or "",
                    },
                    "finish_reason": choice.get("finish_reason") or "stop",
                }
            )
        if not norm_choices:
            norm_choices = [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }
            ]

        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        return {
            "id": data.get("id") or "chatcmpl-watsonx",
            "object": "chat.completion",
            "created": int(data.get("created") or time.time()),
            "model": data.get("model_id") or model,
            "choices": norm_choices,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": int(
                    usage.get("total_tokens", prompt_tokens + completion_tokens) or 0
                ),
            },
        }

    # ── API surface ─────────────────────────────────────────────────

    async def chat(self, model: str, messages: list[dict], **kwargs: Any) -> dict:
        scope = self._scope()
        if scope is None:
            raise ProviderBadRequest(
                "watsonx: no project id configured — set it on the source "
                "(Sources → IBM watsonx.ai → Project ID) or export "
                "WATSONX_PROJECT_ID"
            )
        scope_field, scope_value = scope
        token = await self._get_iam_token()

        max_tokens = kwargs.get("max_tokens")
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            max_tokens = DEFAULT_MAX_TOKENS

        payload: dict[str, Any] = {
            "model_id": model,
            scope_field: scope_value,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self._chat_url(),
                    json=payload,
                    headers=self._bearer_headers(token),
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self._redact(f"timeout: {exc}")) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                self._redact(f"{type(exc).__name__}: {exc}")
            ) from exc
        if resp.status_code != 200:
            raise self._map_status(resp.status_code, resp.text)
        return self._normalize_response(resp.json(), model)

    async def health_check(self) -> bool:
        try:
            await self._get_json(self._models_url())
            return True
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        """The chat models this account can use, newest page order preserved.

        Raises a :class:`ProviderError` so a caller can tell "your key was
        rejected" apart from "this account has no chat models" — an empty
        list is a real answer, not an error swallowed on the way out.
        """
        out: list[dict] = []
        seen: set[str] = set()
        start: str | None = None
        for _ in range(_MAX_PAGES):
            page = await self._get_json(self._models_url(start=start))
            resources = page.get("resources") or []
            for spec in resources:
                if not isinstance(spec, dict):
                    continue
                model_id = str(spec.get("model_id") or "").strip()
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                out.append(self._normalize_spec(model_id, spec))
            start = _next_page_start(page)
            if not start or not resources:
                break
        return out

    @staticmethod
    def _normalize_spec(model_id: str, spec: dict) -> dict:
        """One ``foundation_model_specs`` entry in the shape callers expect.

        The extra fields watsonx gives us — a human label, the provider, the
        lifecycle — are kept rather than flattened away: the lifecycle is
        what lets a deprecated model be passed over when picking a default.
        """
        limits = (
            spec.get("model_limits")
            if isinstance(spec.get("model_limits"), dict)
            else {}
        )
        return {
            "id": model_id,
            "object": "model",
            "name": str(spec.get("label") or model_id),
            "owned_by": str(spec.get("provider") or "IBM watsonx.ai"),
            "description": spec.get("short_description"),
            "context_window": limits.get("max_sequence_length"),
            "lifecycle": _lifecycle_states(spec),
            "deprecated": _is_deprecated(spec),
        }


def _next_page_start(page: dict) -> str | None:
    """The cursor for the next catalog page, or None on the last one.

    Returned decoded, because ``_models_url`` percent-encodes it — a cursor
    lifted straight out of an ``href`` query string is already encoded and
    would otherwise be encoded twice, and watsonx would reject it.
    """
    nxt = page.get("next")
    if not isinstance(nxt, dict):
        return None
    start = nxt.get("start")
    if start:
        return str(start)
    # Some deployments return only an href; pull the cursor out of its query.
    href = str(nxt.get("href") or "")
    if "start=" in href:
        return unquote(href.split("start=", 1)[1].split("&", 1)[0]) or None
    return None


def _lifecycle_states(spec: dict) -> list[str]:
    """The lifecycle ids watsonx reports for a model, lowercased.

    The field is a list of ``{"id": "available"|"deprecated"|"withdrawn", …}``
    entries. Read defensively — a model with no lifecycle block is treated as
    saying nothing rather than as deprecated.
    """
    out: list[str] = []
    for entry in spec.get("lifecycle") or []:
        if isinstance(entry, dict) and entry.get("id"):
            out.append(str(entry["id"]).lower())
        elif isinstance(entry, str):
            out.append(entry.lower())
    return out


def _is_deprecated(spec: dict) -> bool:
    """Is this model on its way out? Never auto-select one as a default."""
    return any(
        state in ("deprecated", "withdrawn", "constricted")
        for state in _lifecycle_states(spec)
    )
