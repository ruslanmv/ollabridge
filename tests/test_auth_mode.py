"""Unit tests for runtime-switchable authentication mode.

Verifies the additive, non-destructive behaviour:

* the three canonical modes (required / local-trust / pairing) enforce exactly
  what they did before, now sourced from the runtime store;
* switching the mode via the store takes effect on the very next request (no
  restart), because ``require_api_key`` reads it live;
* the always-on API-key baseline keeps working in every mode;
* unknown/garbage stored values fail safe to ``required``.

No network, no running server — ``require_api_key`` is called directly with a
lightweight fake Request.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.core import runtime_settings as rts  # noqa: E402
from ollabridge.core import security  # noqa: E402

VALID_KEY = "dev-key-change-me"  # settings.API_KEYS default


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, host: str | None) -> None:
        self.client = _FakeClient(host) if host is not None else None


@pytest.fixture(autouse=True)
def _isolate_store(tmp_path, monkeypatch):
    """Point the runtime store at a temp file and reset caches/pairing between
    tests so each starts from a clean, env-default state."""
    monkeypatch.setattr(rts, "_STORE_FILE", tmp_path / "runtime_settings.json")
    monkeypatch.setattr(rts, "_cache", None)
    security.set_pairing_manager(None)
    yield
    monkeypatch.setattr(rts, "_cache", None)


def _call(request, key=None):
    return security.require_api_key(request, x_api_key=key, authorization=None)


def _loopback():
    return _FakeRequest("127.0.0.1")


def _remote():
    return _FakeRequest("203.0.113.9")


# ── required (default) ───────────────────────────────────────────────────────

def test_required_accepts_valid_key():
    rts.set_auth_mode("required")
    assert _call(_remote(), VALID_KEY) == VALID_KEY


def test_required_rejects_missing_or_bad_key():
    rts.set_auth_mode("required")
    for req in (_loopback(), _remote()):
        with pytest.raises(HTTPException) as ei:
            _call(req, None)
        assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        _call(_remote(), "wrong")


def test_required_does_not_trust_loopback():
    # Non-destructive: `required` must NOT bypass auth for loopback.
    rts.set_auth_mode("required")
    with pytest.raises(HTTPException):
        _call(_loopback(), None)


# ── local-trust ──────────────────────────────────────────────────────────────

def test_local_trust_bypasses_loopback():
    rts.set_auth_mode("local-trust")
    assert _call(_loopback(), None) == "__local_trust__"


def test_local_trust_requires_key_for_remote():
    rts.set_auth_mode("local-trust")
    with pytest.raises(HTTPException):
        _call(_remote(), None)
    assert _call(_remote(), VALID_KEY) == VALID_KEY


# ── pairing ──────────────────────────────────────────────────────────────────

def test_pairing_accepts_static_key_and_loopback():
    rts.set_auth_mode("pairing")
    assert _call(_remote(), VALID_KEY) == VALID_KEY
    assert _call(_loopback(), None) == "__local_trust__"


def test_pairing_accepts_paired_token():
    rts.set_auth_mode("pairing")

    class _Mgr:
        def validate_token(self, tok):
            return tok == "mtx_paired"

    security.set_pairing_manager(_Mgr())
    assert _call(_remote(), "mtx_paired") == "mtx_paired"
    with pytest.raises(HTTPException):
        _call(_remote(), "mtx_wrong")


# ── live switching + fail-safe ───────────────────────────────────────────────

def test_switching_mode_takes_effect_immediately():
    # A keyless loopback request is rejected under required...
    rts.set_auth_mode("required")
    with pytest.raises(HTTPException):
        _call(_loopback(), None)
    # ...and accepted the moment we flip to local-trust — no restart, no
    # re-import; require_api_key reads the store per call.
    rts.set_auth_mode("local-trust")
    assert _call(_loopback(), None) == "__local_trust__"


def test_no_override_honors_live_settings(monkeypatch):
    # Regression: the launcher sets the live settings.AUTH_MODE at runtime. With
    # no UI override saved, that must be the effective mode — previously a store
    # default froze it to "required" and 401'd the loopback UI.
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "local-trust", raising=False)
    assert rts.effective_auth_mode() == "local-trust"
    # A keyless loopback request (the bundled UI) is therefore trusted.
    assert _call(_loopback(), None) == "__local_trust__"


def test_unrelated_settings_save_does_not_touch_auth_mode(monkeypatch):
    # Saving other runtime settings must never persist/shadow auth mode.
    from ollabridge.core.settings import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "local-trust", raising=False)
    rts.update({"default_model": "llama3"})
    assert rts.effective_auth_mode() == "local-trust"


def test_unknown_mode_fails_safe_to_required():
    rts.update({rts._AUTH_OVERRIDE_KEY: "garbage"})
    assert rts.effective_auth_mode() == "required"
    with pytest.raises(HTTPException):
        _call(_loopback(), None)
    assert _call(_remote(), VALID_KEY) == VALID_KEY
