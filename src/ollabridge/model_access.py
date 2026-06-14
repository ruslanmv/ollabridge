"""Per-model access control — the layer that separates a configured *source*
from *where each of its models is visible*.

The product previously conflated four independent ideas into one "source
mode". They are now distinct (see docs/UX_SOURCES_MODEL.md):

* **Source**       — where a model comes from (Ollama, watsonx, OpenAI, …);
                     managed in ``providers.yaml`` / the Sources API.
* **Key storage**  — where the credential lives (local vs cloud vault);
                     the ``storage_mode`` field on a source.
* **Access**       — *this module*: per (source, model) visibility flags
                     (this PC / LAN / cloud / per-app) and a routing opt-in.
* **Routing**      — whether the router may auto-select a model
                     (``allow_routing`` here + the policy engine).

Access records live in ``~/.ollabridge/model_access.yaml`` (metadata only —
never a secret). Safe defaults: a model is visible to **this PC only**;
LAN, cloud, app access, and routing are all **off** until the user opts in.

LAN and workspace visibility are accepted and persisted but not yet
*enforced* by a serving path — they are forward-looking flags. Cloud
visibility and per-app allow-lists are honoured by ``cloud_manifest()``,
which is what gets published to OllaBridge Cloud.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ollabridge.core import paths


def _access_file() -> Path:
    return paths.data_dir() / "model_access.yaml"


def _key(source_id: str, model_id: str) -> str:
    return f"{source_id}\t{model_id}"


class ModelAccess(BaseModel):
    """Where one model (from one source) is visible, and whether it routes."""

    source_id: str
    model_id: str
    enabled: bool = True
    visible_local: bool = True  # available to the local OpenAI API
    visible_lan: bool = False  # forward-looking (not yet enforced)
    visible_cloud: bool = False  # published to the OllaBridge Cloud relay
    allowed_apps: list[str] = Field(default_factory=list)  # paired-app ids
    allowed_workspace: bool = False  # forward-looking (enterprise)
    allow_routing: bool = False  # router may auto-select this model

    @property
    def access_key(self) -> str:
        return _key(self.source_id, self.model_id)


class AccessFile(BaseModel):
    access: list[ModelAccess] = Field(default_factory=list)


def load_all(path: Path | None = None) -> dict[str, ModelAccess]:
    """All stored access records, keyed by ``source\\tmodel``."""
    p = path or _access_file()
    if not p.exists():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    records = AccessFile.model_validate(raw).access
    return {r.access_key: r for r in records}


def get(source_id: str, model_id: str, path: Path | None = None) -> ModelAccess:
    """Access for one model — safe defaults (local-only) when unset."""
    records = load_all(path)
    existing = records.get(_key(source_id, model_id))
    if existing is not None:
        return existing
    return ModelAccess(source_id=source_id, model_id=model_id)


def _save(records: dict[str, ModelAccess], path: Path | None = None) -> Path:
    p = path or _access_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records.values(), key=lambda r: (r.source_id, r.model_id))
    payload = AccessFile(access=ordered).model_dump()
    header = (
        "# OllaBridge per-model access (metadata only — never secrets).\n"
        "# Safe defaults: visible to this PC only; LAN/cloud/app/routing off.\n"
        "# See docs/UX_SOURCES_MODEL.md.\n"
    )
    p.write_text(header + yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    paths.tighten_permissions(p)
    return p


def set_access(
    source_id: str,
    model_id: str,
    *,
    enabled: bool | None = None,
    visible_local: bool | None = None,
    visible_lan: bool | None = None,
    visible_cloud: bool | None = None,
    allowed_apps: list[str] | None = None,
    allowed_workspace: bool | None = None,
    allow_routing: bool | None = None,
    path: Path | None = None,
) -> ModelAccess:
    """Update access flags for one model; unspecified flags are unchanged."""
    records = load_all(path)
    rec = records.get(_key(source_id, model_id)) or ModelAccess(
        source_id=source_id, model_id=model_id
    )
    if enabled is not None:
        rec.enabled = enabled
    if visible_local is not None:
        rec.visible_local = visible_local
    if visible_lan is not None:
        rec.visible_lan = visible_lan
    if visible_cloud is not None:
        rec.visible_cloud = visible_cloud
    if allowed_apps is not None:
        rec.allowed_apps = sorted(set(allowed_apps))
    if allowed_workspace is not None:
        rec.allowed_workspace = allowed_workspace
    if allow_routing is not None:
        rec.allow_routing = allow_routing
    records[rec.access_key] = rec
    _save(records, path)
    return rec


def remove_source(source_id: str, path: Path | None = None) -> int:
    """Drop all access records for a source (called when a source is removed)."""
    records = load_all(path)
    kept = {k: v for k, v in records.items() if v.source_id != source_id}
    removed = len(records) - len(kept)
    if removed:
        _save(kept, path)
    return removed


def cloud_manifest(
    models: list[tuple[str, str, str]], path: Path | None = None
) -> list[dict]:
    """Filtered manifest to publish to OllaBridge Cloud.

    *models* is a list of ``(source_id, source_label, model_id)``. Only models
    flagged ``visible_cloud`` are included; per-app allow-lists travel with
    each entry so the cloud can scope a model to specific paired apps.
    """
    records = load_all(path)
    out: list[dict] = []
    for source_id, source_label, model_id in models:
        rec = records.get(_key(source_id, model_id))
        if rec is None or not (rec.enabled and rec.visible_cloud):
            continue
        out.append(
            {
                "model_id": model_id,
                "source_id": source_id,
                "source_label": source_label,
                "allowed_apps": rec.allowed_apps,
                "allow_routing": rec.allow_routing,
                "requires_device_online": True,  # relay path: this device serves it
            }
        )
    return out
