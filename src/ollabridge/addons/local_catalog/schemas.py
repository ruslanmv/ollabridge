"""
Pydantic schemas for the local model fleet.

Mirrors the cloud-side ``HFProviderModel`` shape so cloud Admin can ingest
the heartbeat payload directly into its unified ``provider_models`` table
without translation.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ───────────────────────────────────────────────────


class LocalSetupStatus(str, Enum):
    """Lifecycle state of a local catalog row."""

    AUTO = "auto"               # discovered but not probed yet
    VERIFIED = "verified"        # last probe succeeded
    BROKEN = "broken"            # last probe failed
    NOT_INSTALLED = "not_installed"   # referenced but not pulled
    PULLING = "pulling"          # download in progress
    DISABLED = "disabled"        # admin disabled
    REMOVED = "removed"          # ``ollama rm`` happened externally


class LocalScoringProfile(str, Enum):
    DEFAULT = "default"
    PRIVACY = "privacy"          # prefers small offline-capable models


class LocalRuntime(str, Enum):
    OLLAMA = "ollama"
    LLAMACPP = "llamacpp"
    VLLM = "vllm"
    OPENAI_COMPATIBLE = "openai_compatible"
    UNKNOWN = "unknown"


# ── Capability bag ──────────────────────────────────────────


class ModelCapabilities(BaseModel):
    """Inferred from model family + runtime ``/api/show`` output."""

    supports_chat: bool = True
    supports_embeddings: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_streaming: bool = True

    def count(self) -> int:
        return sum([
            self.supports_chat, self.supports_embeddings, self.supports_tools,
            self.supports_vision, self.supports_structured_output, self.supports_streaming,
        ])


# ── Transient discovery row ─────────────────────────────────


class LocalModelRow(BaseModel):
    """One normalized row produced by the parser from a runtime listing."""

    node_id: str
    runtime: LocalRuntime = LocalRuntime.OLLAMA
    external_model_id: str               # raw tag, e.g. ``qwen2.5:14b``
    router_model_id: str                 # ``<node_id>:<external_model_id>``
    display_name: Optional[str] = None
    family: Optional[str] = None         # llama, qwen, gemma, mistral, deepseek
    parameter_size: Optional[str] = None # 1b, 7b, 14b, 70b
    parameter_count: Optional[int] = None  # parsed numeric form (in millions)
    quantization: Optional[str] = None   # q4_K_M, fp16, ...
    context_window: Optional[int] = None
    disk_size_bytes: Optional[int] = None
    modified_at: Optional[dt.datetime] = None
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    raw: dict = Field(default_factory=dict)


# ── Persisted entity ────────────────────────────────────────


class LocalModel(BaseModel):
    """Persisted row in ``local_models.yaml``."""

    # Identity
    node_id: str
    runtime: LocalRuntime = LocalRuntime.OLLAMA
    external_model_id: str
    router_model_id: str

    # Classification
    display_name: Optional[str] = None
    family: Optional[str] = None
    parameter_size: Optional[str] = None
    parameter_count: Optional[int] = None
    quantization: Optional[str] = None
    context_window: Optional[int] = None
    disk_size_bytes: Optional[int] = None

    # Capabilities
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)

    # Scoring output
    rank: int = 0
    score: float = 0.0
    is_top_recommended: bool = False

    # Admin state
    enabled: bool = False
    pinned: bool = False                 # admin pin (always promoted)
    manually_added: bool = False
    setup_status: LocalSetupStatus = LocalSetupStatus.AUTO

    # Observability
    modified_at: Optional[dt.datetime] = None
    last_seen_at: Optional[dt.datetime] = None
    last_checked_at: Optional[dt.datetime] = None
    last_error: Optional[str] = None
    latency_observed_ms: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    missing_sync_count: int = 0
    consecutive_check_failures: int = 0

    raw_metadata: dict = Field(default_factory=dict)

    @property
    def size_marker(self) -> str:
        """Coarse bucket used by filters."""
        if not self.parameter_count:
            return "unknown"
        p = self.parameter_count
        if p < 3_000:
            return "tiny"      # <3B
        if p < 10_000:
            return "small"     # 3B–10B
        if p < 30_000:
            return "medium"    # 10B–30B
        if p < 80_000:
            return "large"     # 30B–80B
        return "huge"          # 80B+

    @property
    def is_chat_capable(self) -> bool:
        return bool(self.capabilities and self.capabilities.supports_chat)


# ── Sync result ─────────────────────────────────────────────


class LocalSyncResult(BaseModel):
    """Outcome of one node sync."""

    node_id: str
    started_at: dt.datetime
    finished_at: dt.datetime
    fetched: int = 0
    upserted: int = 0
    promoted_to_top: int = 0
    demoted_from_top: int = 0
    marked_removed: int = 0
    aliases_written: int = 0
    error: Optional[str] = None

    @property
    def duration_s(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def ok(self) -> bool:
        return self.error is None


# ── Stats ───────────────────────────────────────────────────


class LocalCatalogStats(BaseModel):
    """Aggregate stats per node (or globally when ``node_id=None``)."""

    node_id: Optional[str] = None
    total: int = 0
    enabled: int = 0
    top_recommended: int = 0
    pinned: int = 0
    manual: int = 0
    verified: int = 0
    broken: int = 0
    removed: int = 0
    last_sync_at: Optional[dt.datetime] = None
    last_sync_ok: Optional[bool] = None
    total_disk_bytes: int = 0


# ── Pull-job tracking ───────────────────────────────────────


class PullProgress(BaseModel):
    """In-memory progress for an ongoing ``ollama pull``."""

    node_id: str
    external_model_id: str
    status: str = "queued"   # queued | running | completed | error
    total_bytes: int = 0
    completed_bytes: int = 0
    last_update: dt.datetime = Field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )
    error: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round(100.0 * self.completed_bytes / self.total_bytes, 1)
