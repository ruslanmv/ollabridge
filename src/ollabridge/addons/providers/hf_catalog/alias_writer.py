"""Auto-rewrite the managed ``hf:*`` / ``ollabridge:*`` alias block in
``model_aliases.yaml`` from the latest catalog snapshot.

Design principles (from the architecture decision):

- **Aliases describe intent, not model names.** ``ollabridge:fast`` always
  points at the fastest live HF route on disk; ``ollabridge:reasoning``
  always points at the best reasoning model.
- **Capability buckets are derived, not hardcoded.** New tasks
  (``video-generation``, future ``audio-generation``) flow through the
  same machinery just by adding the bucket definition below.
- **Operator overrides are preserved.** Manual aliases live above the
  ``# --- BEGIN AUTOMANAGED ---`` sentinel and are never touched.

The writer is idempotent: writing the same snapshot twice yields
byte-identical YAML, so a no-op sync produces no spurious diffs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import yaml

from ollabridge.addons.providers.hf_catalog.schemas import (
    HFTask,
    SnapshotEntry,
)

logger = logging.getLogger(__name__)


_BEGIN_MARK = "# --- BEGIN AUTOMANAGED hf_catalog ---"
_END_MARK = "# --- END AUTOMANAGED hf_catalog ---"
_PROVIDER_ID = "huggingface-free"


@dataclass(frozen=True)
class _Bucket:
    """Definition of a capability bucket → alias name."""

    alias: str
    predicate: Callable[[SnapshotEntry], bool]
    top_n: int = 3
    description: str = ""

    def pick(self, entries: list[SnapshotEntry]) -> list[SnapshotEntry]:
        eligible = [e for e in entries if self.predicate(e)]
        # Already ranked by snapshot.filter()/score order; dedupe by model_id.
        seen: set[str] = set()
        out: list[SnapshotEntry] = []
        for e in eligible:
            if e.model_id in seen:
                continue
            seen.add(e.model_id)
            out.append(e)
            if len(out) >= self.top_n:
                break
        return out


# Capability buckets — order matters only for human readability of the YAML.
# Adding a new alias is a one-line change here: no router code, no UI,
# no client SDK change.
_BUCKETS: tuple[_Bucket, ...] = (
    # ── ollabridge:* — primary, intent-based ────────────────
    _Bucket(
        alias="ollabridge:fast",
        predicate=lambda e: e.task in (HFTask.CHAT_COMPLETION, HFTask.VLM)
            and (e.latency_s is None or e.latency_s < 1.5),
        top_n=3,
        description="Lowest-latency live chat route",
    ),
    _Bucket(
        alias="ollabridge:reasoning",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION
            and any(t in {"reasoning", "thinking", "math"} for t in e.labels),
        top_n=3,
        description="Best reasoning / thinking model",
    ),
    _Bucket(
        alias="ollabridge:vision",
        predicate=lambda e: e.task == HFTask.VLM,
        top_n=3,
        description="Best image-understanding model",
    ),
    _Bucket(
        alias="ollabridge:tools",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION and e.supports_tools,
        top_n=3,
        description="Best tool-calling model",
    ),
    _Bucket(
        alias="ollabridge:json",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION
            and e.supports_structured_output,
        top_n=3,
        description="Best structured-output (JSON / response_format) model",
    ),
    _Bucket(
        alias="ollabridge:image",
        predicate=lambda e: e.task == HFTask.IMAGE,
        top_n=3,
        description="Best image-generation model",
    ),
    _Bucket(
        alias="ollabridge:video",
        predicate=lambda e: e.task == HFTask.VIDEO,
        top_n=3,
        description="Best video-generation model",
    ),
    # ── hf:* — convenience secondaries that still always work ─
    _Bucket(
        alias="hf:best",
        predicate=lambda e: e.task in (HFTask.CHAT_COMPLETION, HFTask.VLM),
        top_n=5,
        description="Top-scoring chat/VLM route overall",
    ),
    _Bucket(
        alias="hf:auto",
        predicate=lambda e: e.task in (HFTask.CHAT_COMPLETION, HFTask.VLM),
        top_n=5,
        description="Same as hf:best — synonym for OpenAI SDK ergonomics",
    ),
    _Bucket(
        alias="hf:fast",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION
            and (e.latency_s is None or e.latency_s < 1.5),
        top_n=3,
        description="Lowest-latency HF route",
    ),
    _Bucket(
        alias="hf:cheap",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION
            and e.cost_marker in ("free", "cheap"),
        top_n=3,
        description="Cheapest HF route under monthly credits",
    ),
    _Bucket(
        alias="hf:tools",
        predicate=lambda e: e.task == HFTask.CHAT_COMPLETION and e.supports_tools,
        top_n=3,
        description="HF tool-calling route",
    ),
    _Bucket(
        alias="hf:vision",
        predicate=lambda e: e.task == HFTask.VLM,
        top_n=3,
        description="HF vision-language route",
    ),
    _Bucket(
        alias="hf:image",
        predicate=lambda e: e.task == HFTask.IMAGE,
        top_n=3,
        description="HF image-generation route",
    ),
    _Bucket(
        alias="hf:video",
        predicate=lambda e: e.task == HFTask.VIDEO,
        top_n=3,
        description="HF video-generation route",
    ),
    # ── hf:deepseek — kept as a label-pattern bucket, not hardcoded model id ─
    _Bucket(
        alias="hf:deepseek",
        predicate=lambda e: "deepseek" in e.model_id.lower(),
        top_n=3,
        description="Best DeepSeek-family route on HF",
    ),
)


def build_managed_aliases(entries: list[SnapshotEntry]) -> dict[str, list[dict]]:
    """Apply each bucket's predicate to the snapshot and return a mapping
    of ``alias → [{provider, model}, ...]``. Aliases with no matching rows
    are dropped so the YAML never carries empty arrays."""
    out: dict[str, list[dict]] = {}
    # Entries already ordered by rank/score in caller; defensive resort:
    ranked = sorted(entries, key=lambda e: (e.rank or 1e9, -e.score))
    for bucket in _BUCKETS:
        picks = bucket.pick(ranked)
        if not picks:
            continue
        out[bucket.alias] = [
            {"provider": _PROVIDER_ID, "model": e.router_model_id}
            for e in picks
        ]
    return out


def _format_block(managed: dict[str, list[dict]]) -> str:
    """Render the managed alias block as YAML lines suitable for splicing."""
    if not managed:
        return ""
    lines: list[str] = []
    bucket_descriptions = {b.alias: b.description for b in _BUCKETS}
    for alias, candidates in managed.items():
        desc = bucket_descriptions.get(alias, "")
        if desc:
            lines.append(f"  # {desc}")
        lines.append(f"  {alias}:")
        for c in candidates:
            lines.append(f"    - provider: {c['provider']}")
            lines.append(f"      model: {c['model']}")
        lines.append("")  # blank line between aliases for readability
    return "\n".join(lines).rstrip() + "\n"


def write_managed_aliases(
    path: Path,
    managed: dict[str, list[dict]],
) -> int:
    """Splice the managed alias block between ``# --- BEGIN AUTOMANAGED ---``
    and ``# --- END AUTOMANAGED ---`` sentinels in ``model_aliases.yaml``.

    Inserts the sentinels at the end of the file the first time it runs.
    Returns the number of aliases written.

    Validates that the resulting YAML still parses before replacing the
    file on disk — a corrupt write would silently break routing.
    """
    if not path.exists():
        logger.warning("Aliases file %s does not exist; skipping alias write", path)
        return 0

    original = path.read_text(encoding="utf-8")
    body = _format_block(managed)

    if _BEGIN_MARK in original and _END_MARK in original:
        before, _, rest = original.partition(_BEGIN_MARK)
        _, _, after = rest.partition(_END_MARK)
        new_text = (
            before.rstrip()
            + "\n\n"
            + _BEGIN_MARK
            + "\n"
            + body
            + _END_MARK
            + "\n"
            + after.lstrip("\n")
        )
    else:
        new_text = (
            original.rstrip()
            + "\n\n"
            + _BEGIN_MARK
            + "\n"
            + body
            + _END_MARK
            + "\n"
        )

    # Parse-check before writing — never poison the alias file.
    try:
        yaml.safe_load(new_text)
    except yaml.YAMLError as exc:
        logger.error("Refusing to write aliases — generated YAML is invalid: %s", exc)
        return 0

    path.write_text(new_text, encoding="utf-8")
    logger.info("Wrote %d managed aliases to %s", len(managed), path)
    return len(managed)


def aliases_supported() -> Iterable[str]:
    """Return the list of alias names this module manages."""
    return (b.alias for b in _BUCKETS)
