"""Hugging Face Hub catalog client (gateway).

Queries the public Hub API for models that expose at least one inference
provider mapping. The response includes the ``inferenceProviderMapping``
array we enumerate into ``model:provider`` pairs.

API reference (stable, public)::

    GET https://huggingface.co/api/models
        ?inference_provider=all
        &pipeline_tag=text-generation
        &sort=trendingScore
        &direction=-1
        &limit=<n>
        &expand[]=inferenceProviderMapping

Authorization is optional but recommended — without an HF token, calls
share the anonymous rate limit. The same client implementation is used
by ``ollabridge-cloud`` so behaviour stays consistent between local and
cloud-side syncs.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


DEFAULT_API_BASE = "https://huggingface.co"

# Pipelines that map to chat-style completions.
CHAT_PIPELINES = (
    "text-generation",
    "conversational",
    "image-text-to-text",  # VLMs
)

# Pipelines for media generation. Snapshot-only by default — the gateway
# routes these through dedicated /v1/images and /v1/videos endpoints.
IMAGE_PIPELINES = ("text-to-image",)
VIDEO_PIPELINES = ("text-to-video",)


class HuggingFaceCatalogClient:
    """Async wrapper around ``GET https://huggingface.co/api/models``."""

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        token: Optional[str] = None,
        timeout: float = 30.0,
        user_agent: str = "ollabridge/hf-catalog (+https://github.com/ruslanmv/ollabridge)",
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.user_agent = user_agent

    async def fetch_inference_models(
        self,
        limit: int = 100,
        pipelines: tuple[str, ...] = CHAT_PIPELINES,
        sort: str = "trendingScore",
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` unique Hub entries that have at least one
        live inference provider mapping. Deduplicates by ``modelId`` across
        pipelines (some chat models appear under multiple tags)."""
        seen: dict[str, dict[str, Any]] = {}

        async with self._http() as client:
            for pipeline in pipelines:
                per_pipeline = max(limit, 100)
                rows = await self._fetch_pipeline(client, pipeline, per_pipeline, sort)
                for row in rows:
                    model_id = row.get("id") or row.get("modelId")
                    if not model_id or model_id in seen:
                        continue
                    if not row.get("inferenceProviderMapping"):
                        continue
                    seen[model_id] = row
                    if len(seen) >= limit:
                        break
                if len(seen) >= limit:
                    break

        result = list(seen.values())[:limit]
        logger.info("HF catalog: fetched %d inference-capable models", len(result))
        return result

    async def probe_chat(
        self,
        router_model_id: str,
        api_key: Optional[str] = None,
        router_base: str = "https://router.huggingface.co",
    ) -> tuple[bool, Optional[str], Optional[float]]:
        """Tiny round-trip probe used by per-model health checks.

        Returns ``(ok, error, latency_ms)``."""
        url = f"{router_base.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json", "User-Agent": self.user_agent}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": router_model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.post(url, json=payload)
            latency_ms = (time.monotonic() - started) * 1000.0
        except httpx.HTTPError as exc:
            return False, exc.__class__.__name__, None

        if resp.status_code >= 400:
            return False, f"http_{resp.status_code}", latency_ms
        return True, None, latency_ms

    # ── Internals ───────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.AsyncClient(
            base_url=self.api_base,
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
        )

    async def _fetch_pipeline(
        self,
        client: httpx.AsyncClient,
        pipeline: str,
        limit: int,
        sort: str,
    ) -> list[dict[str, Any]]:
        # ``expand[]=inferenceProviderMapping`` is required — without it
        # the Hub omits the mapping array and the client returns nothing.
        params: list[tuple[str, str]] = [
            ("inference_provider", "all"),
            ("pipeline_tag", pipeline),
            ("sort", sort),
            ("direction", "-1"),
            ("limit", str(limit)),
            ("expand[]", "inferenceProviderMapping"),
            ("full", "true"),
            ("config", "true"),
        ]
        try:
            resp = await client.get("/api/models", params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "HF catalog: /api/models returned %s for pipeline=%s: %s",
                exc.response.status_code, pipeline, exc.response.text[:200],
            )
            return []
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("HF catalog: transport error for pipeline=%s: %s", pipeline, exc)
            return []

        try:
            data = resp.json()
        except ValueError:
            logger.warning("HF catalog: non-JSON response for pipeline=%s", pipeline)
            return []

        if not isinstance(data, list):
            logger.warning(
                "HF catalog: expected list, got %s for pipeline=%s",
                type(data).__name__, pipeline,
            )
            return []
        return data
