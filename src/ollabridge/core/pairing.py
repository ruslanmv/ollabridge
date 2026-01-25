from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ollabridge.core.settings import settings


def _now() -> float:
    return time.time()


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class PairInfo:
    code: str
    expires_at: float
    local_only: bool

    @property
    def expires_in(self) -> int:
        return max(0, int(self.expires_at - _now()))


class PairingManager:
    """MatrixLLM-style pairing for client applications.

    - A short code is shown in the server console (or via GET /pair/info).
    - Client exchanges the code for a long-lived bearer token via POST /pair.
    - Token hashes are persisted on disk and validated for subsequent requests.

    Notes:
    - Pair codes are held in-memory only. Restarting the gateway resets the code.
    - Tokens persist across restarts (stored as hashes).
    """

    def __init__(self, tokens_file: Path | None = None):
        self._tokens_file = tokens_file or settings.PAIRING_TOKENS_FILE
        self._pair_code: str | None = None
        self._pair_expires_at: float = 0.0

    # ----------------------------
    # Pair code lifecycle
    # ----------------------------
    def reset_pair_code(self) -> PairInfo:
        code = f"{secrets.randbelow(1_000):03d}-{secrets.randbelow(1_000):03d}"
        expires_at = _now() + int(settings.PAIRING_CODE_TTL_SECONDS)
        self._pair_code = code
        self._pair_expires_at = expires_at
        return PairInfo(code=code, expires_at=expires_at, local_only=bool(settings.PAIRING_LOCAL_ONLY))

    def get_pair_info(self) -> PairInfo | None:
        if not self._pair_code:
            return None
        if _now() >= self._pair_expires_at:
            return None
        return PairInfo(code=self._pair_code, expires_at=self._pair_expires_at, local_only=bool(settings.PAIRING_LOCAL_ONLY))

    def validate_pair_code(self, code: str) -> bool:
        info = self.get_pair_info()
        if not info:
            return False
        return code.strip() == info.code

    # ----------------------------
    # Token store
    # ----------------------------
    def _load_tokens(self) -> dict[str, Any]:
        p = self._tokens_file
        try:
            if not p.exists():
                return {"tokens": {}}
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt file should not crash the server; start fresh.
            return {"tokens": {}}

    def _save_tokens(self, data: dict[str, Any]) -> None:
        p = self._tokens_file
        _ensure_parent(p)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
        try:
            # best effort (unix only)
            p.chmod(0o600)
        except Exception:
            pass

    def mint_token(self, client_name: str | None = None) -> str:
        token = f"mtx_{secrets.token_urlsafe(24)}"
        h = _sha256_hex(token)

        blob = self._load_tokens()
        blob.setdefault("tokens", {})
        blob["tokens"][h] = {
            "client_name": (client_name or "").strip() or None,
            "created_at": int(_now()),
            "revoked": False,
        }
        self._save_tokens(blob)
        return token

    def revoke_token(self, token: str) -> bool:
        h = _sha256_hex(token)
        blob = self._load_tokens()
        tok = (blob.get("tokens") or {}).get(h)
        if not tok:
            return False
        tok["revoked"] = True
        tok["revoked_at"] = int(_now())
        self._save_tokens(blob)
        return True

    def token_valid(self, token: str) -> bool:
        if not token:
            return False
        h = _sha256_hex(token)
        blob = self._load_tokens()
        tok = (blob.get("tokens") or {}).get(h)
        if not tok:
            return False
        if tok.get("revoked"):
            return False
        return True


_pairing_singleton: PairingManager | None = None


def pairing() -> PairingManager:
    global _pairing_singleton
    if _pairing_singleton is None:
        _pairing_singleton = PairingManager()
    return _pairing_singleton
