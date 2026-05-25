"""Hugging Face Inference Providers catalog (gateway-native).

Discovers the top inference-capable Hugging Face models, scores them, and
persists a snapshot YAML so the ``huggingface-free`` provider can serve
many ``model:provider`` pairs without exploding the provider list.

The module is deliberately self-contained so OllaBridge keeps working
without OllaBridge Cloud:

    HuggingFaceCatalogClient → Hub API ( /api/models )
    normalize()              → (model, hf_provider) rows
    score_rows()             → ranked list
    CatalogSnapshot          → YAML on disk
    CatalogSyncService       → orchestrates fetch → rank → persist → alias rewrite

When OllaBridge Cloud is reachable the same module can layer the cloud's
curated catalog on top — see ``cloud_sync.py``.
"""

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFInferenceModelRow,
    HFTask,
    ScoringProfile,
    SyncResult,
)

__all__ = [
    "HFInferenceModelRow",
    "HFTask",
    "ScoringProfile",
    "SyncResult",
]
