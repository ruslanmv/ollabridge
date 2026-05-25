"""OpenAI-compatible media generation endpoints.

``POST /v1/images/generations`` and ``POST /v1/videos/generations`` route
through the Hugging Face Inference Providers via :class:`HFMediaService`.

Model resolution:
  - ``hf:image`` / ``hf:video`` / ``ollabridge:image`` / ``ollabridge:video``
    aliases resolve through the standard :class:`ProviderRouter`.
  - A bare ``model_id:provider`` is passed directly through.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ollabridge.addons.providers.errors import ProviderError, ProviderQuotaExceeded
from ollabridge.addons.providers.media import HFMediaService
from ollabridge.core.security import require_api_key

logger = logging.getLogger("ollabridge.media_routes")


router = APIRouter(prefix="/v1", tags=["media"])


# ── Request bodies ─────────────────────────────────────────


class ImageGenerationRequest(BaseModel):
    model: str = Field(default="ollabridge:image", description="Alias or HF router model id")
    prompt: str = Field(..., min_length=1, max_length=4000)
    n: int = Field(default=1, ge=1, le=4)
    size: str = Field(default="1024x1024")
    response_format: str = Field(default="b64_json", pattern="^(b64_json|url)$")
    user: Optional[str] = None
    free_credit_only: bool = Field(default=True)


class VideoGenerationRequest(BaseModel):
    model: str = Field(default="ollabridge:video", description="Alias or HF router model id")
    prompt: str = Field(..., min_length=1, max_length=4000)
    num_frames: int = Field(default=32, ge=8, le=128)
    free_credit_only: bool = Field(default=True)


# ── Helpers ────────────────────────────────────────────────


def _resolve_model(request: Request, model_or_alias: str) -> tuple[str, dict[str, Any]]:
    """Run the alias resolver and return ``(concrete_router_id, route_info)``.

    Falls back to passing the value through unchanged so power users can
    target a specific ``model_id:provider`` directly.
    """
    prouter = getattr(request.app.state, "provider_router", None)
    if prouter is None:
        return model_or_alias, {"route": "passthrough", "reason": "no router"}

    candidates = prouter.resolve(model_or_alias)
    if not candidates:
        return model_or_alias, {"route": "passthrough", "reason": "no alias match"}

    chosen = candidates[0]
    return chosen.model, {
        "route": "alias",
        "provider_id": chosen.provider_id,
        "model": chosen.model,
        "score": chosen.score,
    }


def _hf_credentials(request: Request) -> tuple[Optional[str], Optional[str]]:
    """Pull the HF token + bill_to from the secret store, with env fallback."""
    import os

    store = getattr(request.app.state, "secret_store", None)
    token = None
    bill_to = None
    if store is not None:
        token = store.get("huggingface")
        bill_to = store.get("huggingface_bill_to")
    if not token:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    return token, bill_to


# ── Endpoints ──────────────────────────────────────────────


@router.post("/images/generations", dependencies=[Depends(require_api_key)])
async def create_image(
    request: Request,
    body: ImageGenerationRequest = Body(...),
) -> dict[str, Any]:
    """OpenAI-compatible image generation."""
    token, bill_to = _hf_credentials(request)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Hugging Face token not configured. Connect via /admin/providers/huggingface/connect or set HF_TOKEN.",
        )

    concrete_model, route_info = _resolve_model(request, body.model)
    logger.info("Image generation: %s → %s (%s)", body.model, concrete_model, route_info)

    service = HFMediaService(api_key=token, bill_to=bill_to)
    started = time.monotonic()
    try:
        result = await service.generate_image(
            model=concrete_model,
            prompt=body.prompt,
            n=body.n,
            size=body.size,
            response_format=body.response_format,
            extra={"user": body.user} if body.user else None,
        )
    except ProviderQuotaExceeded as exc:
        # Surface free-credit hard-stop as a clean 402 to the client.
        raise HTTPException(status_code=402, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"upstream: {exc}")

    latency_ms = (time.monotonic() - started) * 1000.0
    # Standard OpenAI response shape + a small ollabridge namespace for
    # the route the gateway actually chose.
    result.setdefault("created", int(time.time()))
    result["_ollabridge"] = {
        "route": route_info,
        "latency_ms": round(latency_ms, 1),
        "alias_requested": body.model,
    }
    return result


@router.post("/videos/generations", dependencies=[Depends(require_api_key)])
async def create_video(
    request: Request,
    body: VideoGenerationRequest = Body(...),
) -> dict[str, Any]:
    """Video generation (long-running, synchronous response of base64 bytes)."""
    token, bill_to = _hf_credentials(request)
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Hugging Face token not configured. Connect via /admin/providers/huggingface/connect or set HF_TOKEN.",
        )

    concrete_model, route_info = _resolve_model(request, body.model)
    logger.info("Video generation: %s → %s (%s)", body.model, concrete_model, route_info)

    service = HFMediaService(api_key=token, bill_to=bill_to)
    started = time.monotonic()
    try:
        result = await service.generate_video(
            model=concrete_model,
            prompt=body.prompt,
            num_frames=body.num_frames,
        )
    except ProviderQuotaExceeded as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"upstream: {exc}")

    latency_ms = (time.monotonic() - started) * 1000.0
    result.setdefault("created", int(time.time()))
    result["_ollabridge"] = {
        "route": route_info,
        "latency_ms": round(latency_ms, 1),
        "alias_requested": body.model,
    }
    return result
