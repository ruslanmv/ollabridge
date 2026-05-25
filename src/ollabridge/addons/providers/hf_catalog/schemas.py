"""Pydantic schemas for the Hugging Face inference-model catalog (gateway).

A trimmed-down sibling of ``ollabridge_cloud.addons.providers.huggingface_catalog.schemas``
— the gateway snapshots to YAML and never to a database, so we don't need
the full admin-state machinery the cloud carries.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HFTask(str, Enum):
    """Subset of HF pipeline tags we route on."""

    CHAT_COMPLETION = "chat-completion"
    TEXT_GENERATION = "text-generation"
    VLM = "vlm"
    EMBEDDING = "embedding"
    IMAGE = "image-generation"
    VIDEO = "video-generation"
    OTHER = "other"


class ScoringProfile(str, Enum):
    """Pluggable scoring strategy."""

    DEFAULT = "default"
    FREE_LAB = "free_lab"


class HFInferenceModelRow(BaseModel):
    """One normalized ``(model, hf_provider)`` row from the Hub API."""

    model_id: str
    hf_provider: str
    router_model_id: str
    task: HFTask = HFTask.CHAT_COMPLETION
    input_price_per_1m: Optional[float] = None
    output_price_per_1m: Optional[float] = None
    context_window: Optional[int] = None
    latency_s: Optional[float] = None
    throughput_tps: Optional[float] = None
    supports_tools: bool = False
    supports_structured_output: bool = False
    trending_score: Optional[float] = None
    likes: Optional[int] = None
    downloads: Optional[int] = None
    labels: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)

    @field_validator("router_model_id")
    @classmethod
    def _validate_router_id(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("router_model_id must include ':<hf_provider>' suffix")
        return v


class SnapshotEntry(BaseModel):
    """A persisted catalog entry. Mirrors the row plus rank/score from the
    last sync. Edited entries with ``manually_added=True`` are kept across
    syncs."""

    router_model_id: str
    model_id: str
    hf_provider: str
    task: HFTask = HFTask.CHAT_COMPLETION
    rank: int = 0
    score: float = 0.0
    input_price_per_1m: Optional[float] = None
    output_price_per_1m: Optional[float] = None
    context_window: Optional[int] = None
    latency_s: Optional[float] = None
    throughput_tps: Optional[float] = None
    supports_tools: bool = False
    supports_structured_output: bool = False
    trending_score: Optional[float] = None
    labels: list[str] = Field(default_factory=list)
    manually_added: bool = False
    last_seen_at: Optional[dt.datetime] = None
    missing_sync_count: int = 0

    @property
    def cost_marker(self) -> str:
        in_p = self.input_price_per_1m
        out_p = self.output_price_per_1m
        if in_p is None and out_p is None:
            return "unknown"
        if (in_p or 0.0) == 0.0 and (out_p or 0.0) == 0.0:
            return "free"
        if max(in_p or 0.0, out_p or 0.0) < 1.0:
            return "cheap"
        return "paid"


class SyncResult(BaseModel):
    """Outcome of one catalog sync."""

    started_at: dt.datetime
    finished_at: dt.datetime
    fetched: int = 0
    upserted: int = 0
    marked_stale: int = 0
    aliases_written: int = 0
    profile: ScoringProfile = ScoringProfile.FREE_LAB
    error: Optional[str] = None

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def ok(self) -> bool:
        return self.error is None
