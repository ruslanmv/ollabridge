"""BYOK provider metadata: catalog, storage modes, and ``providers.yaml``.

Secure BYOK routing across your authorized devices and workspaces:

* ``providers.yaml`` stores **metadata only** — provider name, kind, storage
  mode, base URL, rotation timestamps. It never contains an API key.
* The key itself lives in the encrypted :class:`SecretStore`
  (``~/.ollabridge/secrets.enc``) or, when the user explicitly opts in and
  the paired cloud supports it, in the cloud encrypted vault.

Storage modes:

* ``local_only``               — safest; key never leaves this device.
* ``cloud_encrypted_vault``    — usable from the user's paired devices
  (requires cloud login + ``provider_secrets_cloud_vault: true`` in sync.yaml).
* ``organization_vault``       — usable by the team according to org policy
  (enterprise; requires an org-enabled cloud).

Until the paired cloud exposes a vault API, modes 2 and 3 keep the secret
local and record the *intent* — nothing is uploaded silently.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from ollabridge.core import paths

StorageMode = Literal["local_only", "cloud_encrypted_vault", "organization_vault"]

STORAGE_MODES: tuple[StorageMode, ...] = (
    "local_only",
    "cloud_encrypted_vault",
    "organization_vault",
)


class ProviderSpec(BaseModel):
    """Static catalog entry for a supported provider."""

    name: str
    label: str
    env_var: str
    key_prefix: str = ""  # informational; used for sanity warnings only
    base_url: str = ""
    models_path: str = "/models"  # OpenAI-style listing for health checks
    openai_compatible: bool = True
    notes: str = ""
    # Extra provider-specific config fields the UI should prompt for, beyond
    # the generic api_key/base_url (e.g. watsonx needs a project_id). Each
    # entry is (field_name, label, required).
    extra_fields: list[tuple[str, str, bool]] = []


PROVIDER_CATALOG: dict[str, ProviderSpec] = {
    spec.name: spec
    for spec in [
        ProviderSpec(
            name="openai",
            label="OpenAI",
            env_var="OPENAI_API_KEY",
            key_prefix="sk-",
            base_url="https://api.openai.com/v1",
        ),
        ProviderSpec(
            name="anthropic",
            label="Anthropic",
            env_var="ANTHROPIC_API_KEY",
            key_prefix="sk-ant-",
            base_url="https://api.anthropic.com/v1",
            openai_compatible=False,
            models_path="/models",
        ),
        ProviderSpec(
            name="gemini",
            label="Google Gemini",
            env_var="GEMINI_API_KEY",
            key_prefix="AIza",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            notes="OpenAI-compatible endpoint",
        ),
        ProviderSpec(
            name="azure-openai",
            label="Azure OpenAI",
            env_var="AZURE_OPENAI_API_KEY",
            base_url="",
            notes="base_url required: https://<resource>.openai.azure.com",
        ),
        ProviderSpec(
            name="bedrock",
            label="AWS Bedrock",
            env_var="AWS_BEARER_TOKEN_BEDROCK",
            base_url="",
            openai_compatible=False,
            notes="region-specific endpoint; IAM credentials also supported via AWS env",
        ),
        ProviderSpec(
            name="watsonx",
            label="IBM watsonx.ai",
            env_var="WATSONX_API_KEY",
            base_url="https://us-south.ml.cloud.ibm.com",
            openai_compatible=False,
            models_path="/ml/v1/foundation_model_specs?version=2024-09-16",
            notes="IBM watsonx.ai foundation models. Requires a project_id (or "
            "space_id) and a region base URL.",
            extra_fields=[
                ("project_id", "Project ID (or Space ID)", True),
                ("region", "Region (e.g. us-south, eu-de)", False),
            ],
        ),
        ProviderSpec(
            name="groq",
            label="Groq",
            env_var="GROQ_API_KEY",
            key_prefix="gsk_",
            base_url="https://api.groq.com/openai/v1",
        ),
        ProviderSpec(
            name="openrouter",
            label="OpenRouter",
            env_var="OPENROUTER_API_KEY",
            key_prefix="sk-or-",
            base_url="https://openrouter.ai/api/v1",
        ),
        ProviderSpec(
            name="huggingface",
            label="Hugging Face",
            env_var="HUGGINGFACE_API_KEY",
            key_prefix="hf_",
            base_url="https://router.huggingface.co/v1",
        ),
        ProviderSpec(
            name="deepseek",
            label="DeepSeek",
            env_var="DEEPSEEK_API_KEY",
            key_prefix="sk-",
            base_url="https://api.deepseek.com/v1",
        ),
        ProviderSpec(
            name="mistral",
            label="Mistral",
            env_var="MISTRAL_API_KEY",
            base_url="https://api.mistral.ai/v1",
        ),
        ProviderSpec(
            name="together",
            label="Together AI",
            env_var="TOGETHER_API_KEY",
            base_url="https://api.together.xyz/v1",
        ),
        ProviderSpec(
            name="fireworks",
            label="Fireworks AI",
            env_var="FIREWORKS_API_KEY",
            base_url="https://api.fireworks.ai/inference/v1",
        ),
        ProviderSpec(
            name="custom",
            label="Generic OpenAI-compatible",
            env_var="CUSTOM_LLM_API_KEY",
            base_url="",
            notes="set base_url to any OpenAI-compatible endpoint",
        ),
    ]
}


SharingMode = Literal["private", "account", "workspace", "organization"]


class ProviderRecord(BaseModel):
    """One configured source in ``providers.yaml`` (metadata, never secrets).

    Safe-by-default policy (see docs/UX_EXTERNAL_SOURCES.md): a new source is
    local-only, private to this computer, and excluded from automatic routing
    until the user explicitly opts in.
    """

    name: str
    kind: str = ""  # catalog name; equals `name` unless a custom instance
    display_name: str = ""  # user-facing label, e.g. "Personal OpenAI"
    storage_mode: StorageMode = "local_only"
    base_url: str = ""
    default_model: str = ""  # used when the request doesn't pin a model
    enabled: bool = True
    allow_routing: bool = False  # may the routing engine pick this source?
    sharing: SharingMode = "private"
    created_at: Optional[str] = None
    rotated_at: Optional[str] = None
    last_test_ok: Optional[bool] = None
    last_test_at: Optional[str] = None
    vault_synced: bool = False  # true only after an explicit, successful vault push


class ProvidersFile(BaseModel):
    providers: list[ProviderRecord] = Field(default_factory=list)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_providers(path: Path | None = None) -> list[ProviderRecord]:
    p = path or paths.providers_file()
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict):
        return []
    return ProvidersFile.model_validate(raw).providers


def save_providers(records: list[ProviderRecord], path: Path | None = None) -> Path:
    p = path or paths.providers_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# OllaBridge provider metadata. SECRETS ARE NEVER STORED IN THIS FILE.\n"
        "# Keys live in ~/.ollabridge/secrets.enc (encrypted when OLLA_SECRET is set).\n"
    )
    payload = ProvidersFile(providers=records).model_dump()
    p.write_text(header + yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    paths.tighten_permissions(p)
    return p


def get_record(
    name: str, records: list[ProviderRecord] | None = None
) -> ProviderRecord | None:
    for r in records if records is not None else load_providers():
        if r.name == name:
            return r
    return None


def upsert_record(record: ProviderRecord, path: Path | None = None) -> None:
    records = load_providers(path)
    records = [r for r in records if r.name != record.name]
    if record.created_at is None:
        record.created_at = _now()
    records.append(record)
    records.sort(key=lambda r: r.name)
    save_providers(records, path)


def remove_record(name: str, path: Path | None = None) -> bool:
    records = load_providers(path)
    kept = [r for r in records if r.name != name]
    if len(kept) == len(records):
        return False
    save_providers(kept, path)
    return True


def secret_key_for(name: str) -> str:
    """SecretStore key for a provider's API key."""
    return name


def env_key_for(name: str) -> str | None:
    spec = PROVIDER_CATALOG.get(name)
    if spec and os.environ.get(spec.env_var, "").strip():
        return os.environ[spec.env_var].strip()
    return None


def configured_provider_names(secret_store=None) -> set[str]:
    """Providers that have a usable credential (secret store or env var)."""
    configured: set[str] = set()
    store = secret_store
    if store is None:
        try:
            from ollabridge.addons.providers.secret_store import SecretStore

            store = SecretStore()
        except Exception:
            store = None
    if store is not None:
        for rec in load_providers():
            if store.has(secret_key_for(rec.name)):
                configured.add(rec.name)
        # Legacy direct keys (e.g. "huggingface" stored by the HF connect flow)
        for key in getattr(store, "list_keys", lambda: [])():
            if key in PROVIDER_CATALOG:
                configured.add(key)
    for name, spec in PROVIDER_CATALOG.items():
        if os.environ.get(spec.env_var, "").strip():
            configured.add(name)
    return configured
