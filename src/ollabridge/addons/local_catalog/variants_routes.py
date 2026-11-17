"""``/local/variants``: copies of installed models with their own context window.

* ``GET    /local/variants``         every installed model: built from, context, last load result
* ``POST   /local/variants``         make a copy (``source``, ``context``, optional ``name``)
* ``POST   /local/variants/test``    load a model once and record whether it fits here
* ``DELETE /local/variants/{name}``  remove a copy (never an original)

Backend for the "Build a model" wizard. See ``variants.py`` for the rules.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ollabridge.addons.local_catalog import variants
from ollabridge.core.security import require_api_key

router = APIRouter(prefix="/local/variants", tags=["local-variants"])


class CreateRequest(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    context: int = Field(ge=variants.MIN_CONTEXT, le=1_048_576)
    # Left out: the name is made from the source and the size, e.g. ``clef-flash-6k``.
    name: Optional[str] = Field(default=None, max_length=120)


class TestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _refuse(exc: variants.VariantError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


@router.get("", dependencies=[Depends(require_api_key)])
async def list_variants():
    try:
        models = await variants.list_models()
    except variants.VariantError as exc:
        raise _refuse(exc) from None
    return {"models": models, "presets": list(variants.CONTEXT_PRESETS)}


@router.post("", dependencies=[Depends(require_api_key)])
async def create_variant(body: CreateRequest):
    try:
        return await variants.create(body.source, body.context, body.name)
    except variants.VariantError as exc:
        raise _refuse(exc) from None


@router.post("/test", dependencies=[Depends(require_api_key)])
async def test_variant(body: TestRequest):
    try:
        return await variants.load_test(body.name)
    except variants.VariantError as exc:
        raise _refuse(exc) from None


@router.delete("/{name:path}", dependencies=[Depends(require_api_key)])
async def remove_variant(name: str):
    try:
        await variants.remove(name)
    except variants.VariantError as exc:
        raise _refuse(exc) from None
    return {"ok": True, "name": name}
