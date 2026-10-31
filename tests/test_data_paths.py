"""Every data file follows the gateway's data directory.

``OLLABRIDGE_HOME`` (else the ``DATA_DIR`` setting) is documented to relocate
all state. The local model catalog, its managed aliases, the Hugging Face
snapshot and the secret store's fallback built ``~/.ollabridge/...`` from the
home directory themselves, and the stores built on ``settings.DATA_DIR``
(runtime settings, consumer nodes, the request database, pairing tokens,
sessions) ignored ``OLLABRIDGE_HOME`` entirely. A test or demo run could only
keep away from real data by changing ``HOME``, which is how a cleanup once
deleted a real home directory. These tests pin every store to the one data
directory and keep new modules from reintroducing the pattern.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService
from ollabridge.addons.providers.hf_catalog.snapshot import CatalogSnapshot
from ollabridge.addons.providers.secret_store import SecretStore
from ollabridge.core.settings import Settings, settings

SRC = Path(__file__).resolve().parents[1] / "src" / "ollabridge"


def _default_paths() -> dict[str, Path]:
    repo = LocalCatalogRepository()
    return {
        "local_models.yaml": repo.path,
        "local_aliases.yaml": LocalCatalogSyncService(repository=repo).alias_path,
        "hf_catalog.yaml": CatalogSnapshot().path,
        "secrets.enc": SecretStore(secret="test-only-secret").path,
    }


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    for var in ("OLLABRIDGE_HOME", "OBRIDGE_LOCAL_CATALOG_PATH", "OBRIDGE_LOCAL_ALIAS_PATH"):
        monkeypatch.delenv(var, raising=False)


def test_ollabridge_home_relocates_every_default_path(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path))
    assert _default_paths() == {name: tmp_path / name for name in _default_paths()}


def test_without_ollabridge_home_paths_follow_the_data_dir_setting(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "DATA_DIR", data)
    assert _default_paths() == {name: data / name for name in _default_paths()}


def test_paths_are_resolved_when_objects_are_created_not_at_import(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path / "first"))
    first = _default_paths()
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path / "second"))
    second = _default_paths()
    assert all(path.parent == tmp_path / "first" for path in first.values())
    assert all(path.parent == tmp_path / "second" for path in second.values())


def test_dedicated_catalog_overrides_still_win(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OBRIDGE_LOCAL_CATALOG_PATH", str(tmp_path / "cat.yaml"))
    monkeypatch.setenv("OBRIDGE_LOCAL_ALIAS_PATH", str(tmp_path / "aliases.yaml"))
    paths = _default_paths()
    assert paths["local_models.yaml"] == tmp_path / "cat.yaml"
    assert paths["local_aliases.yaml"] == tmp_path / "aliases.yaml"
    assert paths["hf_catalog.yaml"] == tmp_path / "home" / "hf_catalog.yaml"


@pytest.mark.parametrize(
    ("home", "data_dir", "expected"),
    [
        ("{tmp}/home", None, "{tmp}/home"),
        (None, "{tmp}/data", "{tmp}/data"),
        ("{tmp}/home", "{tmp}/data", "{tmp}/home"),  # OLLABRIDGE_HOME wins, as in paths.data_dir()
        ("   ", "{tmp}/data", "{tmp}/data"),  # empty counts as unset
    ],
)
def test_data_dir_setting_honours_ollabridge_home(tmp_path, monkeypatch, home, data_dir, expected):
    monkeypatch.delenv("DATA_DIR", raising=False)
    if home is not None:
        monkeypatch.setenv("OLLABRIDGE_HOME", home.format(tmp=tmp_path))
    if data_dir is not None:
        monkeypatch.setenv("DATA_DIR", data_dir.format(tmp=tmp_path))
    assert Settings(_env_file=None).DATA_DIR == Path(expected.format(tmp=tmp_path))


def test_data_dir_setting_expands_a_tilde(monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_HOME", "~/ollabridge-test-home")
    assert Settings(_env_file=None).DATA_DIR == Path("~/ollabridge-test-home").expanduser()


_REPORT_LOCATIONS = """
import json
from ollabridge.core import consumer_registry, paths, runtime_settings
from ollabridge.core.pairing import PairingManager
from ollabridge.core.session_bridge import SessionBridge
from ollabridge.core.settings import settings
from ollabridge.cloud import device_config
from ollabridge.db import database
from ollabridge.addons.local_catalog.repository import LocalCatalogRepository
from ollabridge.addons.local_catalog.sync_service import LocalCatalogSyncService
from ollabridge.addons.providers.hf_catalog.snapshot import CatalogSnapshot
from ollabridge.addons.providers.secret_store import SecretStore

repo = LocalCatalogRepository()
print(json.dumps({
    "settings.DATA_DIR": str(settings.DATA_DIR / "x"),
    "runtime_settings.json": str(runtime_settings._STORE_FILE),
    "consumer_nodes.json": str(consumer_registry._STORE_FILE),
    "ollabridge.sqlite": database.db_url().removeprefix("sqlite:///"),
    "pair_tokens.json": str(PairingManager()._tokens_file),
    "sessions.json": str(SessionBridge()._store_file),
    "cloud_device.json (default)": str(device_config.DEFAULT_CLOUD_DEVICE_PATH),
    "traces.db": str(paths.traces_db_file()),
    "sync.yaml": str(paths.sync_file()),
    "local_models.yaml": str(repo.path),
    "local_aliases.yaml": str(LocalCatalogSyncService(repository=repo).alias_path),
    "hf_catalog.yaml": str(CatalogSnapshot().path),
    "secrets.enc": str(SecretStore(secret="test-only-secret").path),
}))
"""


def test_one_variable_relocates_every_store(tmp_path):
    """A fresh process with only OLLABRIDGE_HOME set keeps every file under it.

    Runs in a subprocess because several stores resolve their location once,
    when the settings singleton is imported.
    """
    home = tmp_path / "obhome"
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("DATA_DIR", "DATABASE_URL", "OBRIDGE_LOCAL_CATALOG_PATH", "OBRIDGE_LOCAL_ALIAS_PATH")
    }
    env["OLLABRIDGE_HOME"] = str(home)
    out = subprocess.run(
        [sys.executable, "-c", _REPORT_LOCATIONS],
        cwd=tmp_path,  # no ./.env from the repository
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout
    locations = json.loads(out.strip().splitlines()[-1])
    outside = {name: p for name, p in locations.items() if Path(p).parent != home}
    assert outside == {}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, owners) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def test_no_module_builds_a_data_path_from_the_home_directory():
    """Only settings.py (the DATA_DIR default) and paths.py may name the home directory."""
    allowed = {SRC / "core" / "settings.py", SRC / "core" / "paths.py"}
    offenders: list[str] = []
    for file in sorted(SRC.rglob("*.py")):
        if file in allowed:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            where = f"{file.relative_to(SRC).as_posix()}:{getattr(node, 'lineno', '?')}"
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "home"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "Path"
            ):
                offenders.append(f"{where} Path.home()")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("~/.ollabridge")
                and id(node) not in docstrings
            ):
                offenders.append(f"{where} {node.value!r}")
    assert offenders == [], "Use ollabridge.core.paths.data_dir() instead:\n" + "\n".join(offenders)
