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
