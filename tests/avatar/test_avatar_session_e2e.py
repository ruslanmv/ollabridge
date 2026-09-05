"""The proxy over a real socket, against a stand-in HomePilot.

The unit suite next door asserts the pieces. This one runs the whole path — browser opens a
socket to OllaBridge, OllaBridge opens one to HomePilot, frames cross both ways — because the
claim that matters ("the browser's token never reaches HomePilot") is about what arrives
somewhere else, and only a round trip can show that.

The stand-in HomePilot is deliberately dumb: it records the hello it was given and echoes
everything after it. A smarter fake would start being a second implementation of the protocol,
which is the thing the proxy is written not to be.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any, Self

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

pytest.importorskip("websockets")
pytest.importorskip("uvicorn")

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from ollabridge.api import avatar_session as av


class Server:
    """A uvicorn app on an ephemeral port, up for the life of a `with` block."""

    def __init__(self, app: FastAPI) -> None:
        self._config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                break
            import time

            time.sleep(0.05)
        assert self._server.started, "server did not start"
        return self

    @property
    def port(self) -> int:
        return self._server.servers[0].sockets[0].getsockname()[1]

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)


def homepilot_double() -> tuple[FastAPI, dict[str, Any]]:
    """A HomePilot that records its hello and echoes the rest."""
    seen: dict[str, Any] = {}
    app = FastAPI()

    @app.websocket("/avatar/session")
    async def session(ws: WebSocket) -> None:
        await ws.accept()
        seen["hello"] = json.loads(await ws.receive_text())
        # HomePilot's own presence check: an empty token is refused.
        if not seen["hello"].get("auth"):
            await ws.send_text(json.dumps({"v": 1, "type": "error", "code": "unauthorized"}))
            await ws.close()
            return
        await ws.send_text(json.dumps({"v": 1, "type": "ping"}))
        try:
            while True:
                await ws.send_text(await ws.receive_text())
        except WebSocketDisconnect:
            return

    return app, seen


def bridge_app() -> FastAPI:
    app = FastAPI()
    app.include_router(av.router)
    return app


@pytest.fixture()
def wired(monkeypatch):
    """A HomePilot double and a bridge pointed at it, in local-trust mode."""
    hp_app, seen = homepilot_double()
    with Server(hp_app) as hp:
        monkeypatch.setattr(
            av, "homepilot_target", lambda: (f"ws://127.0.0.1:{hp.port}/avatar/session", "hp-secret-key")
        )
        with Server(bridge_app()) as bridge:
            yield bridge, seen


@pytest.mark.anyio
async def test_the_browsers_token_is_replaced_before_it_leaves(wired, monkeypatch):
    bridge, seen = wired
    monkeypatch.setattr(av, "authorize", lambda token, ws: token == "browser-pair-token")

    async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
        await ws.send(json.dumps({"v": 1, "type": "hello", "client": "3dac", "auth": "browser-pair-token"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "ping"

    # The whole point of the proxy, observed where it matters: at HomePilot.
    assert seen["hello"]["auth"] == "hp-secret-key"
    assert seen["hello"]["client"] == "3dac", "the rest of the hello is the client's to say"


@pytest.mark.anyio
async def test_frames_cross_in_both_directions(wired, monkeypatch):
    bridge, _ = wired
    monkeypatch.setattr(av, "authorize", lambda token, ws: True)

    async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
        await ws.send(json.dumps({"v": 1, "type": "hello", "auth": "t"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "ping"
        await ws.send(json.dumps({"v": 1, "type": "ctx", "mode": "companion"}))
        echoed = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert echoed == {"v": 1, "type": "ctx", "mode": "companion"}


@pytest.mark.anyio
async def test_a_rejected_credential_never_opens_an_upstream_socket(wired, monkeypatch):
    bridge, seen = wired
    monkeypatch.setattr(av, "authorize", lambda token, ws: False)

    async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
        await ws.send(json.dumps({"v": 1, "type": "hello", "auth": "wrong"}))
        body = json.loads(await asyncio.wait_for(ws.recv(), 5))

    assert body["code"] == "unauthorized"
    assert "hello" not in seen, "HomePilot was contacted despite the browser being refused"


@pytest.mark.anyio
async def test_a_first_frame_that_is_not_hello_is_refused(wired, monkeypatch):
    bridge, seen = wired
    monkeypatch.setattr(av, "authorize", lambda token, ws: True)

    async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
        await ws.send(json.dumps({"v": 1, "type": "ctx"}))
        body = json.loads(await asyncio.wait_for(ws.recv(), 5))

    assert body["code"] == "unauthenticated"
    assert "hello" not in seen


@pytest.mark.anyio
async def test_no_homepilot_is_a_named_refusal_not_a_dropped_socket(monkeypatch):
    monkeypatch.setattr(av, "homepilot_target", lambda: None)
    with Server(bridge_app()) as bridge:
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
            body = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert body["code"] == "homepilot_unavailable"


@pytest.mark.anyio
async def test_an_unreachable_homepilot_says_so_rather_than_hanging(monkeypatch):
    # Port 1 is reserved and refuses immediately — a connect failure, not a timeout.
    monkeypatch.setattr(av, "homepilot_target", lambda: ("ws://127.0.0.1:1/avatar/session", "k"))
    monkeypatch.setattr(av, "authorize", lambda token, ws: True)
    with Server(bridge_app()) as bridge:
        async with websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session") as ws:
            await ws.send(json.dumps({"v": 1, "type": "hello", "auth": "t"}))
            body = json.loads(await asyncio.wait_for(ws.recv(), 10))
    assert body["code"] == "homepilot_unreachable"


@pytest.fixture
def anyio_backend():
    return "asyncio"
