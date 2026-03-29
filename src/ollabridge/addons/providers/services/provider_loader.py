"""
Provider catalog loader.

Reads YAML seed files and returns typed structures.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ollabridge.addons.providers.models import AliasCandidate, ProviderConfig

logger = logging.getLogger(__name__)

# Default catalog directory (relative to this file)
_CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog"


def load_provider_seed(path: str | Path | None = None) -> list[ProviderConfig]:
    """
    Load provider definitions from providers.seed.yaml.

    Returns a list of ProviderConfig objects.
    """
    if path is None:
        path = _CATALOG_DIR / "providers.seed.yaml"
    path = Path(path)

    if not path.exists():
        logger.warning("Provider seed file not found: %s", path)
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    providers: list[ProviderConfig] = []
    for raw in data.get("providers", []):
        try:
            providers.append(ProviderConfig(**raw))
        except Exception as exc:
            logger.warning("Skipping invalid provider entry %s: %s", raw.get("id", "?"), exc)

    logger.info("Loaded %d providers from %s", len(providers), path)
    return providers


def load_aliases(path: str | Path | None = None) -> dict[str, list[AliasCandidate]]:
    """
    Load model alias mappings from model_aliases.yaml.

    Returns {alias_name: [AliasCandidate, ...]}.
    """
    if path is None:
        path = _CATALOG_DIR / "model_aliases.yaml"
    path = Path(path)

    if not path.exists():
        logger.warning("Alias file not found: %s", path)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    aliases: dict[str, list[AliasCandidate]] = {}
    for alias_name, candidates in data.get("aliases", {}).items():
        alias_list: list[AliasCandidate] = []
        for c in candidates:
            try:
                alias_list.append(AliasCandidate(**c))
            except Exception as exc:
                logger.warning("Skipping invalid alias candidate in '%s': %s", alias_name, exc)
        if alias_list:
            aliases[alias_name] = alias_list

    logger.info("Loaded %d aliases from %s", len(aliases), path)
    return aliases


def append_provider_to_seed(provider: dict, path: str | Path | None = None) -> None:
    """
    Append a single provider entry to providers.seed.yaml.

    This is additive only — existing entries are never modified or removed.
    """
    if path is None:
        path = _CATALOG_DIR / "providers.seed.yaml"
    path = Path(path)

    if not path.exists():
        data: dict = {"providers": []}
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"providers": []}

    providers_list = data.get("providers", [])

    # Guard: don't duplicate an existing id
    existing_ids = {p.get("id") for p in providers_list}
    if provider.get("id") in existing_ids:
        raise ValueError(f"Provider '{provider['id']}' already exists in seed file")

    providers_list.append(provider)
    data["providers"] = providers_list

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    logger.info("Appended provider '%s' to %s", provider.get("id"), path)


def toggle_provider_in_seed(provider_id: str, enabled: bool, path: str | Path | None = None) -> bool:
    """
    Toggle the enabled flag of a provider in providers.seed.yaml.

    Returns True if the provider was found and toggled.
    """
    if path is None:
        path = _CATALOG_DIR / "providers.seed.yaml"
    path = Path(path)

    if not path.exists():
        return False

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    found = False
    for entry in data.get("providers", []):
        if entry.get("id") == provider_id:
            entry["enabled"] = enabled
            found = True
            break

    if found:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info("Toggled provider '%s' enabled=%s in %s", provider_id, enabled, path)

    return found


def append_alias_to_seed(alias_name: str, candidates: list[dict], path: str | Path | None = None) -> None:
    """
    Append or update a model alias in model_aliases.yaml.

    If the alias already exists, the new candidates are appended to it.
    """
    if path is None:
        path = _CATALOG_DIR / "model_aliases.yaml"
    path = Path(path)

    if not path.exists():
        data: dict = {"aliases": {}}
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"aliases": {}}

    aliases = data.get("aliases", {})
    if alias_name in aliases:
        # Append new candidates to existing alias
        existing = aliases[alias_name]
        existing_keys = {(c.get("provider"), c.get("model")) for c in existing}
        for c in candidates:
            if (c.get("provider"), c.get("model")) not in existing_keys:
                existing.append(c)
    else:
        aliases[alias_name] = candidates

    data["aliases"] = aliases

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    logger.info("Updated alias '%s' in %s", alias_name, path)


def load_test_matrix(path: str | Path | None = None) -> list[dict]:
    """
    Load the test matrix from test-matrix.yaml.

    Returns a list of test scenario dicts.
    """
    if path is None:
        path = _CATALOG_DIR / "test-matrix.yaml"
    path = Path(path)

    if not path.exists():
        logger.warning("Test matrix file not found: %s", path)
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tests = data.get("tests", [])
    logger.info("Loaded %d test scenarios from %s", len(tests), path)
    return tests
