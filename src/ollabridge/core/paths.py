"""Canonical locations of OllaBridge configuration and state files.

Everything lives under ``~/.ollabridge`` (override with ``OLLABRIDGE_HOME``):

    config.yaml        — reserved for future general config
    sync.yaml          — cloud sync consent/configuration (metadata-only defaults)
    policies.yaml      — routing policies (aliases, allow/deny, cost ceilings)
    providers.yaml     — provider metadata (NEVER secrets; see secrets.enc)
    secrets.enc        — provider credentials (Fernet-encrypted when OLLA_SECRET set)
    cloud_device.json  — cloud pairing credentials (0o600)
    traces.db          — request traces (metadata only, no prompt content)
    audit.log          — local audit trail
    ollabridge.sqlite  — request log database
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def data_dir() -> Path:
    """Resolve the OllaBridge home directory (created on demand).

    Precedence: ``OLLABRIDGE_HOME`` env var → ``Settings.DATA_DIR``
    (itself overridable via the ``DATA_DIR`` env var) → ``~/.ollabridge``.
    """
    raw = os.environ.get("OLLABRIDGE_HOME", "").strip()
    if raw:
        base = Path(raw).expanduser()
    else:
        try:
            from ollabridge.core.settings import settings

            base = Path(settings.DATA_DIR).expanduser()
        except Exception:
            base = Path.home() / ".ollabridge"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return data_dir() / "config.yaml"


def sync_file() -> Path:
    return data_dir() / "sync.yaml"


def policies_file() -> Path:
    return data_dir() / "policies.yaml"


def providers_file() -> Path:
    return data_dir() / "providers.yaml"


def cloud_device_file() -> Path:
    return data_dir() / "cloud_device.json"


def traces_db_file() -> Path:
    return data_dir() / "traces.db"


def audit_log_file() -> Path:
    return data_dir() / "audit.log"


def tighten_permissions(path: Path) -> bool:
    """Best-effort chmod 0o600. Returns True when permissions are now strict."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return True
    except OSError:
        return False


def permissions_ok(path: Path) -> bool:
    """True when *path* is not readable by group/other (POSIX only)."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    if os.name != "posix":
        return True  # Windows ACLs are out of scope for this check
    return not (mode & (stat.S_IRWXG | stat.S_IRWXO))
