"""
``/local/library/*``: find a model that is not installed yet.

- ``GET /local/library/search``            search the Ollama library or Hugging Face
- ``GET /local/library/tags``              the builds of one model, with sizes
- ``GET /local/library/recommendations``   models that fit this PC (opt-in)
- ``PUT /local/library/recommendations``   turn that on or off

Downloading is not here: the UI starts it with ``POST /local/models/pull``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ollabridge.addons.local_catalog import fit
from ollabridge.addons.local_catalog.library import (
    HuggingFaceLibrary,
    OllamaLibrary,
    valid_hf_repo,
    valid_name,
    valid_tag,
)
from ollabridge.core.security import require_api_key

logger = logging.getLogger("ollabridge.local_catalog")

router = APIRouter(prefix="/local/library", tags=["local-library"])

_ollama = OllamaLibrary()
_huggingface = HuggingFaceLibrary()

Source = Literal["ollama", "huggingface"]
_SOURCE_SITE = {"ollama": "ollama.com", "huggingface": "huggingface.co"}


class RecommendationsToggle(BaseModel):
    enabled: bool


@router.get("/search", dependencies=[Depends(require_api_key)])
async def search_library(q: str = Query(default="", max_length=80), source: Source = "ollama"):
    try:
        results = await (_huggingface if source == "huggingface" else _ollama).search(q)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"{_SOURCE_SITE[source]} could not be reached ({type(exc).__name__}).")
    return {"query": q.strip(), "source": source, "results": results}


@router.get("/tags", dependencies=[Depends(require_api_key)])
async def library_tags(
    name: str = Query(..., max_length=160),
    source: Source = "ollama",
    tags: Optional[str] = Query(default=None, max_length=400, description="Ollama only, comma separated; default: latest"),
):
    """The builds a model can be downloaded as: the pull reference and size of each."""
    if source == "huggingface":
        if not valid_hf_repo(name):
            raise HTTPException(422, "Not a Hugging Face repository id.")
        try:
            return {"name": name, "source": source, "tags": await _huggingface.quantizations(name)}
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"huggingface.co could not be reached ({type(exc).__name__}).")
    if not valid_name(name):
        raise HTTPException(422, "Not a library model name.")
    wanted = [t.strip() for t in (tags or "latest").split(",") if t.strip()]
    if not wanted or not all(valid_tag(t) for t in wanted):
        raise HTTPException(422, "Not a valid tag list.")
    return {"name": name, "source": source, "tags": await _ollama.tag_sizes(name, wanted)}


@router.get("/recommendations", dependencies=[Depends(require_api_key)])
async def recommendations(refresh: bool = False, limit: int = Query(default=12, ge=1, le=50)):
    """Off: ``{"enabled": false}`` and nothing else happens: no hardware
    probe, no download."""
    if not fit.is_enabled():
        return {"enabled": False}
    hardware = await asyncio.to_thread(fit.detect_hardware)
    try:
        registry, source = await fit.load_registry(refresh=refresh)
    except RuntimeError as exc:
        return {"enabled": True, "hardware": hardware, "models": [], "error": str(exc)}
    return {
        "enabled": True,
        "hardware": hardware,
        "models": fit.recommend(registry, hardware, limit=limit),
        "assumptions": {"quantization": fit.QUANT, "context": fit.CONTEXT},
        "registry": {"generated_at": registry.get("generated_at"), "source": source},
    }


@router.put("/recommendations", dependencies=[Depends(require_api_key)])
async def set_recommendations(body: RecommendationsToggle):
    return {"enabled": fit.set_enabled(body.enabled)}
