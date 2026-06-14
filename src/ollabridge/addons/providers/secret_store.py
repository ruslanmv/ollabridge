"""Encrypted-at-rest token store for provider credentials.

Uses Fernet (AES-128-CBC + HMAC-SHA256, the cryptography library's
authenticated symmetric primitive). The key is derived deterministically
from the gateway's ``OLLA_SECRET`` env var via HKDF-SHA256, so:

- The same secret on a different machine reads the same store (handy
  for backup / migration).
- Rotating ``OLLA_SECRET`` invalidates the store and the user has to
  re-enter their tokens (defensive against accidental key drift).

Storage layout (``~/.ollabridge/secrets.enc``)::

    {
      "version": 1,
      "tokens": {
        "huggingface": "<fernet-ciphertext>",
        "huggingface_bill_to": "<fernet-ciphertext>",
        ...
      }
    }

If the ``cryptography`` package is not installed we fall back to a
plaintext file with mode ``0o600`` and a loud warning — better than
silently breaking the rest of the app in dev environments.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


DEFAULT_STORE_PATH = Path("~/.ollabridge/secrets.enc").expanduser()
_VERSION = 1


def _default_store_path() -> Path:
    """Default store location, honoring the OLLABRIDGE_HOME override."""
    home = os.environ.get("OLLABRIDGE_HOME", "").strip()
    if home:
        return Path(home).expanduser() / "secrets.enc"
    return DEFAULT_STORE_PATH


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret using HKDF."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    salt = b"ollabridge.providers.secret_store.v1"
    info = b"fernet"
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info)
    raw = hkdf.derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


class SecretStore:
    """Encrypted key-value store for provider credentials.

    Public API is deliberately tiny — get, set, delete, list_keys. Adding
    a new provider's credential is a single ``store.set("groq", "...")``
    call; no schema changes needed.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        secret: str | None = None,
    ) -> None:
        self.path = Path(path).expanduser() if path else _default_store_path()
        self._secret = secret if secret is not None else os.environ.get("OLLA_SECRET", "")
        self._fernet = self._init_fernet()
        self._data: dict[str, str] = {}
        self._load()

    # ── Backend init ───────────────────────────────────────

    def _init_fernet(self):
        if not self._secret:
            logger.warning(
                "SecretStore: OLLA_SECRET is not set — tokens will be stored "
                "in plaintext with file mode 0o600. Set OLLA_SECRET in production."
            )
            return None
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning(
                "SecretStore: 'cryptography' is not installed — falling back to "
                "plaintext storage. Run: pip install cryptography"
            )
            return None
        return Fernet(_derive_fernet_key(self._secret))

    # ── Storage I/O ────────────────────────────────────────

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("SecretStore: %s unreadable: %s", self.path, exc)
            self._data = {}
            return

        if raw.get("version") != _VERSION:
            logger.warning(
                "SecretStore: unsupported version %s in %s — starting empty",
                raw.get("version"), self.path,
            )
            self._data = {}
            return

        tokens = raw.get("tokens", {})
        if not self._fernet:
            self._data = dict(tokens)
            return

        decrypted: dict[str, str] = {}
        for key, ciphertext in tokens.items():
            try:
                decrypted[key] = self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
            except Exception:
                logger.warning(
                    "SecretStore: could not decrypt %s — wrong OLLA_SECRET? "
                    "Dropping the entry.",
                    key,
                )
        self._data = decrypted

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._fernet:
            tokens = {
                k: self._fernet.encrypt(v.encode("utf-8")).decode("utf-8")
                for k, v in self._data.items()
            }
        else:
            tokens = dict(self._data)
        payload = {"version": _VERSION, "tokens": tokens}
        # Write atomically and lock down permissions.
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        os.replace(tmp_path, self.path)

    # ── Public API ─────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> bool:
        if key not in self._data:
            return False
        del self._data[key]
        self._save()
        return True

    def list_keys(self) -> list[str]:
        return sorted(self._data.keys())

    def has(self, key: str) -> bool:
        return key in self._data

    @property
    def is_encrypted(self) -> bool:
        return self._fernet is not None
