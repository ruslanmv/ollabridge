"""Avatar session proxy — the bridge between a browser and a HomePilot behind it.

Two properties carry this module, and both are about what happens when something is missing.

**Absence means no.** `/health` must omit the `avatar` block whenever the relay would not
actually work — not merely when HomePilot is switched off. The avatar client treats an absent
block as "this bridge cannot relay", falls back to the chat path (which already carries
directives) and says so plainly. A block advertised by a bridge that then refuses the socket
turns a graceful degrade into a broken feature.

**The browser never holds HomePilot's key.** It presents OllaBridge's own credential; this
proxy validates that and swaps in HomePilot's before forwarding the hello. The swap is the
reason the feature exists, so it is asserted directly rather than inferred from a round trip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.api import avatar_session as av


class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class FakeWebSocket:
    """Enough of a Starlette WebSocket for `authorize` to make its decision."""

    def __init__(self, host: str = "10.0.0.9") -> None:
        self.client = FakeClient(host)


@pytest.fixture()
def settings_store(monkeypatch):
    """A runtime-settings store the tests own, so no test reads the developer's real config.

    Patches ``get_all`` on the real module rather than swapping the module in ``sys.modules``.
    The swap looks equivalent and is not: ``homepilot_target`` does
    ``from ollabridge.core import runtime_settings``, and once anything has imported that
    submodule once, the name resolves to an **attribute of the package object**, never
    consulting ``sys.modules`` again. So the fake applied when this file ran alone and was
    silently ignored the moment any earlier test had imported the real one — six tests that
    passed in isolation and failed in the suite, which is the worst way for a fixture to be
    wrong.
    """
    from ollabridge.core import runtime_settings as rts

    store: dict[str, Any] = {}
    monkeypatch.setattr(rts, "get_all", lambda: dict(store))
    return store


# ── where HomePilot is, and whether there is one ────────────────────────────


class TestTarget:
    def test_no_homepilot_is_none(self, settings_store):
        settings_store.update({"homepilot_enabled": False, "homepilot_base_url": "http://localhost:8000"})
        assert av.homepilot_target() is None

    def test_enabled_without_a_url_is_also_none(self, settings_store, monkeypatch):
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": ""})
        monkeypatch.setattr("ollabridge.core.settings.settings.HOMEPILOT_BASE_URL", "", raising=False)
        assert av.homepilot_target() is None

    def test_http_becomes_ws_and_the_path_is_appended(self, settings_store):
        settings_store.update(
            {
                "homepilot_enabled": True,
                "homepilot_base_url": "http://localhost:8000",
                "homepilot_api_key": "hp-key",
            }
        )
        assert av.homepilot_target() == ("ws://localhost:8000/avatar/session", "hp-key")

    def test_https_becomes_wss(self, settings_store):
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "https://pilot.example/"})
        url, _ = av.homepilot_target()
        assert url == "wss://pilot.example/avatar/session"

    def test_a_bare_host_is_assumed_plain(self, settings_store):
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "pilot.lan:8000"})
        url, _ = av.homepilot_target()
        assert url == "ws://pilot.lan:8000/avatar/session"

    def test_no_key_configured_is_an_empty_key_not_a_failure(self, settings_store, monkeypatch):
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "http://localhost:8000"})
        monkeypatch.setattr("ollabridge.core.settings.settings.HOMEPILOT_API_KEY", "", raising=False)
        _, key = av.homepilot_target()
        assert key == ""


# ── the advert, and the older bridges that must not make one ────────────────


class TestHealthBlock:
    def test_advertised_when_the_relay_would_work(self, settings_store, monkeypatch):
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "http://localhost:8000"})
        monkeypatch.setattr(av, "websockets_available", lambda: True)
        assert av.health_block() == {"session": "/v1/avatar/session", "features": av.AVATAR_FEATURES}

    def test_absent_when_homepilot_is_off(self, settings_store, monkeypatch):
        settings_store.update({"homepilot_enabled": False})
        monkeypatch.setattr(av, "websockets_available", lambda: True)
        assert av.health_block() is None

    def test_absent_when_the_client_library_is_missing(self, settings_store, monkeypatch):
        # The case that would turn a graceful degrade into a broken feature: HomePilot is
        # configured, so the naive advert says yes, and every socket then fails at connect.
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "http://localhost:8000"})
        monkeypatch.setattr(av, "websockets_available", lambda: False)
        assert av.health_block() is None

    def test_the_features_list_is_a_copy(self, settings_store, monkeypatch):
        # A caller mutating the response must not edit what the next caller is told.
        settings_store.update({"homepilot_enabled": True, "homepilot_base_url": "http://x"})
        monkeypatch.setattr(av, "websockets_available", lambda: True)
        av.health_block()["features"].append("nonsense")
        assert "nonsense" not in av.AVATAR_FEATURES


# ── the browser's credential, judged by OllaBridge's own rules ──────────────


class TestAuthorize:
    @pytest.fixture(autouse=True)
    def _keys(self, monkeypatch):
        monkeypatch.setattr("ollabridge.core.security._keys", lambda: {"sk-static"})
        monkeypatch.setattr("ollabridge.core.security._pairing_manager", None, raising=False)

    def _mode(self, monkeypatch, mode: str):
        monkeypatch.setattr("ollabridge.core.security._effective_auth_mode", lambda: mode)

    def test_required_mode_accepts_a_static_key(self, monkeypatch):
        self._mode(monkeypatch, "required")
        assert av.authorize("sk-static", FakeWebSocket()) is True

    def test_required_mode_rejects_anything_else(self, monkeypatch):
        self._mode(monkeypatch, "required")
        assert av.authorize("nope", FakeWebSocket()) is False
        assert av.authorize("", FakeWebSocket()) is False

    def test_required_mode_does_not_trust_loopback(self, monkeypatch):
        # `local-trust` is a mode the operator chooses. `required` meaning "unless you are on
        # the same box" would make the choice meaningless.
        self._mode(monkeypatch, "required")
        assert av.authorize("", FakeWebSocket("127.0.0.1")) is False

    def test_local_trust_accepts_loopback_with_no_token(self, monkeypatch):
        self._mode(monkeypatch, "local-trust")
        assert av.authorize("", FakeWebSocket("127.0.0.1")) is True

    def test_local_trust_still_wants_a_key_from_elsewhere(self, monkeypatch):
        self._mode(monkeypatch, "local-trust")
        assert av.authorize("", FakeWebSocket("10.0.0.9")) is False
        assert av.authorize("sk-static", FakeWebSocket("10.0.0.9")) is True

    def test_pairing_mode_accepts_a_paired_token(self, monkeypatch):
        self._mode(monkeypatch, "pairing")

        class Mgr:
            @staticmethod
            def validate_token(token: str) -> bool:
                return token == "paired-abc"

        monkeypatch.setattr("ollabridge.core.security._pairing_manager", Mgr, raising=False)
        assert av.authorize("paired-abc", FakeWebSocket()) is True
        assert av.authorize("paired-xyz", FakeWebSocket()) is False

    def test_pairing_mode_still_accepts_the_admin_key(self, monkeypatch):
        self._mode(monkeypatch, "pairing")
        assert av.authorize("sk-static", FakeWebSocket()) is True


# ── the swap, which is the whole reason this proxy exists ───────────────────


class TestCredentialSwap:
    def test_the_operators_key_is_what_travels(self):
        assert av.upstream_token("hp-secret") == "hp-secret"

    @pytest.mark.parametrize("configured", ["", "   ", None])
    def test_an_unconfigured_key_still_sends_something(self, configured):
        # HomePilot's default verifier is a presence check — `bool(token)`. Forwarding an
        # empty string would be refused, which is exactly how the browser's direct path
        # failed before this proxy existed; returning "" here reproduces it one layer down.
        assert av.upstream_token(configured) == av.DEFAULT_UPSTREAM_TOKEN
        assert av.DEFAULT_UPSTREAM_TOKEN

    def test_errors_use_homepilots_own_envelope(self):
        # So the client needs no special case for ours.
        body = json.loads(av._error("unauthorized", "pairing rejected"))
        assert body == {"v": 1, "type": "error", "code": "unauthorized", "msg": "pairing rejected"}


# ── it is a pipe, not a participant ─────────────────────────────────────────


class TestPipe:
    @pytest.mark.anyio
    async def test_frames_pass_through_untouched_until_the_source_stops(self):
        frames = ['{"type":"ctx"}', '{"type":"user_event"}', None]
        sent: list[str] = []

        async def read():
            return frames.pop(0)

        async def write(message):
            sent.append(message)

        await av._pump(read, write)
        assert sent == ['{"type":"ctx"}', '{"type":"user_event"}']

    def test_the_module_names_no_message_type_of_its_own(self):
        # Every type except `hello` is HomePilot's business and the client's. An opinion here
        # would mean two implementations of one protocol, drifting.
        from pathlib import Path

        source = Path(av.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for kind in ("ctx", "user_event", "vision_ask", "chat_meta", "streak", "adult_verify"):
            assert f'"{kind}"' not in code, f"the proxy should not know about {kind}"


@pytest.fixture
def anyio_backend():
    return "asyncio"
