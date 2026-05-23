"""
Local model fleet — discovery, scoring, and admin for an OllaBridge node's
local runtime (Ollama today; llama.cpp / vLLM later).

This addon is the local counterpart to the cloud's ``huggingface_catalog``
module: same data model, same lifecycle (discover → score → top-N
auto-enable → manual override), but the discovery source is the local
runtime's ``/api/tags`` rather than a remote Hub.

The persisted state lives under ``~/.ollabridge/local_models.yaml`` so it
survives restarts and can be inspected/edited by hand. Concurrency is
controlled by a single asyncio lock per node.
"""

from ollabridge.addons.local_catalog.schemas import (
    LocalCatalogStats,
    LocalModel,
    LocalModelRow,
    LocalScoringProfile,
    LocalSetupStatus,
    LocalSyncResult,
    ModelCapabilities,
)

__all__ = [
    "LocalCatalogStats",
    "LocalModel",
    "LocalModelRow",
    "LocalScoringProfile",
    "LocalSetupStatus",
    "LocalSyncResult",
    "ModelCapabilities",
]
