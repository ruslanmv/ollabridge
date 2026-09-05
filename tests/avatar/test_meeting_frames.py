"""Meeting frames across the bridge (HomePilot batch MS8, wave W2).

HomePilot's MeetingSense records a meeting over the avatar session it already has, rather than
over a socket a hosted page cannot open. That only works if this proxy is what its own
docstring says it is: **a pipe, not a participant**. It reads one frame — the ``hello``, because
that is where the token is — and everything after that is HomePilot's business and the
client's.

So the assertions here are deliberately about *bytes*, not about parsed objects. A proxy that
round-tripped every frame through ``json.loads``/``json.dumps`` would pass a
compare-the-dictionaries test while quietly reordering keys, dropping whitespace and — the one
that would actually bite — re-encoding a base64 audio payload it had no business touching. The
frames below are formatted oddly on purpose: spaces after colons, keys out of order, a
trailing space. If any of that changes in transit, this is not a pipe.

Nothing in ollabridge knows what a meeting is, and after this file it still will not. That is
the point being defended.
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
from ollabridge.node.avatar_link import AvatarLink

#: Deliberately ugly: spaces after colons, keys not alphabetical, a trailing space. A proxy
#: that parses and re-serialises cannot reproduce this, and that is exactly what we want to
#: detect — because the same re-serialisation would rewrite the base64 audio below.
UGLY_START = '{"type": "meeting_start", "v": 1, "conversation_id": "conv-1", "audio": {"channels": 2} } '

#: A real WAV header in base64. If the proxy ever decodes and re-encodes a frame, padding and
#: line breaks are where it shows, and an audio chunk is where it hurts.
WAV_B64 = "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
#: The trailing space and the gap before the brace matter: without them this string happens to
#: be exactly what `json.dumps` produces by default, so a re-serialising relay would reproduce
#: it byte for byte and the test would pass while the guarantee was gone. That is precisely
#: what happened on the first run of this file.
UGLY_AUDIO = (
    '{"type": "meeting_audio", "v": 1, "format": "wav", "data_b64": "%s", "t0": 0, "t1": 1400 } ' % WAV_B64
)

#: Server → client, the one outbound type. Its payload is a MeetingSense frame the bridge has
#: no opinion about whatsoever.
UGLY_MEETING = (
    '{"type": "meeting", "v": 1, "meeting": {"type": "segment", "seq": 1, "t0": 1000, '
    '"text": "the launch moves to October", "speaker": "them"} } '
)


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
    """A HomePilot that records the raw text it receives and sends back raw text on demand.

    Records strings rather than objects, because the claim under test is about the bytes. A
    double that parsed what it received would destroy the evidence before the test could look
    at it.
    """
    seen: dict[str, Any] = {"raw": []}
    app = FastAPI()

    @app.websocket("/avatar/session")
    async def session(ws: WebSocket) -> None:
        await ws.accept()
        seen["hello"] = json.loads(await ws.receive_text())
        await ws.send_text(json.dumps({"v": 1, "type": "ping"}))
        try:
            while True:
                raw = await ws.receive_text()
                seen["raw"].append(raw)
                # Answer a meeting frame with the outbound one, so the downward direction is
                # exercised with a payload the bridge must not touch either.
                if '"meeting_start"' in raw:
                    await ws.send_text(UGLY_MEETING)
        except WebSocketDisconnect:
            return

    return app, seen


@pytest.fixture()
def wired(monkeypatch):
    hp_app, seen = homepilot_double()
    with Server(hp_app) as hp:
        monkeypatch.setattr(
            av, "homepilot_target", lambda: (f"ws://127.0.0.1:{hp.port}/avatar/session", "hp-secret-key")
        )
        app = FastAPI()
        app.include_router(av.router)
        with Server(app) as bridge:
            yield bridge, seen


async def _open(bridge, monkeypatch):
    monkeypatch.setattr(av, "authorize", lambda token, ws: True)
    ws = await websockets.connect(f"ws://127.0.0.1:{bridge.port}/v1/avatar/session")
    await ws.send(json.dumps({"v": 1, "type": "hello", "auth": "t"}))
    assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "ping"
    return ws


# ── the proxy is a pipe ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_a_meeting_frame_arrives_byte_for_byte(wired, monkeypatch):
    # Not "the dictionaries match": a proxy that parsed and re-serialised would pass that and
    # still have rewritten the frame. Byte-identity is the property MeetingSense is relying on.
    bridge, seen = wired
    ws = await _open(bridge, monkeypatch)
    try:
        await ws.send(UGLY_START)
        for _ in range(50):
            if seen["raw"]:
                break
            await asyncio.sleep(0.02)
    finally:
        await ws.close()
    assert seen["raw"][0] == UGLY_START


@pytest.mark.anyio
async def test_an_audio_payload_is_never_re_encoded(wired, monkeypatch):
    # The one that would actually bite: base64 has several valid spellings, and a proxy that
    # round-trips a chunk through json could hand HomePilot audio that decodes differently.
    bridge, seen = wired
    ws = await _open(bridge, monkeypatch)
    try:
        await ws.send(UGLY_AUDIO)
        for _ in range(50):
            if seen["raw"]:
                break
            await asyncio.sleep(0.02)
    finally:
        await ws.close()
    assert seen["raw"][0] == UGLY_AUDIO
    assert WAV_B64 in seen["raw"][0]


@pytest.mark.anyio
async def test_the_server_frame_comes_back_byte_for_byte(wired, monkeypatch):
    bridge, _ = wired
    ws = await _open(bridge, monkeypatch)
    try:
        await ws.send(UGLY_START)
        received = await asyncio.wait_for(ws.recv(), 5)
    finally:
        await ws.close()
    assert received == UGLY_MEETING


@pytest.mark.anyio
async def test_a_whole_meeting_crosses_in_order(wired, monkeypatch):
    # Ordering is part of the contract: audio chunks carry overlap, and a transcript assembled
    # out of order would duplicate the words the overlap exists to reconcile.
    bridge, seen = wired
    ws = await _open(bridge, monkeypatch)
    frames = [UGLY_START, UGLY_AUDIO, '{"type":"meeting_audio","v":1,"format":"wav","data_b64":"%s","t0":1800}' % WAV_B64, '{"type":"meeting_stop","v":1}']
    try:
        for frame in frames:
            await ws.send(frame)
        for _ in range(100):
            if len(seen["raw"]) >= len(frames):
                break
            await asyncio.sleep(0.02)
    finally:
        await ws.close()
    assert seen["raw"] == frames


@pytest.mark.anyio
async def test_the_bridge_still_swaps_only_the_hello(wired, monkeypatch):
    # The credential swap is the one edit this proxy makes, and adding meeting frames must not
    # have given it a second opinion.
    bridge, seen = wired
    ws = await _open(bridge, monkeypatch)
    try:
        await ws.send(UGLY_START)
        for _ in range(50):
            if seen["raw"]:
                break
            await asyncio.sleep(0.02)
    finally:
        await ws.close()
    assert seen["hello"]["auth"] == "hp-secret-key"
    assert seen["raw"][0] == UGLY_START


def test_the_bridge_holds_no_opinion_about_meetings():
    """No meeting vocabulary anywhere in the proxy — asserted, not assumed.

    The moment this module learns what a `meeting_audio` is, there are two implementations of
    one protocol and they begin to drift. HomePilot's MS7 explicitly declined to flatten the
    frame family for the same reason.
    """
    source = Path(av.__file__).read_text(encoding="utf-8")
    for word in ("meeting_start", "meeting_audio", "meeting_stop", "transcript", "data_b64"):
        assert word not in source, f"the proxy has learned about {word}"


def test_health_promises_meetings_survive_the_trip():
    # `/health`'s feature list is a promise the client reads before offering the control. The
    # bridge can make this one honestly: it relays them because it relays everything.
    assert "meetings" in av.AVATAR_FEATURES
    block = av.health_block()
    assert block is None or "meetings" in block["features"]


# ── the cloud path: the same frames over sig/ev ─────────────────────────────


class FakeHomePilot:
    """The node's upstream socket, as a queue."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        item = await self.inbox.get()
        if item is None:
            raise ConnectionError("closed")
        return item

    async def close(self) -> None:
        self.closed = True


async def _collect(sink: list, frame: dict) -> None:
    sink.append(frame)


async def _ready(pilot: FakeHomePilot):
    return pilot


@pytest.mark.anyio
async def test_a_meeting_frame_crosses_the_relay_unchanged():
    # Cloud: HomePilot is on the operator's machine and the bridge process cannot reach it, so
    # the frames ride the existing sig/ev relay. Same claim as the direct path — the payload is
    # opaque and arrives as it left.
    pilot = FakeHomePilot()
    sent: list[dict] = []
    link = AvatarLink(
        homepilot_base="http://x", send=lambda frame: _collect(sent, frame), connect=lambda url: _ready(pilot)
    )
    await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {"auth": "hp"}}})

    # The payload is the raw frame string, exactly as `_relayed_session` sends it — and that
    # is *why* the byte guarantee survives the cloud path: a dict payload would be
    # re-serialised on the way out, a string is forwarded as it stands.
    await link.handle({"type": "sig", "stream": "s1", "op": "avatar_send", "payload": UGLY_AUDIO})
    await asyncio.sleep(0.05)

    assert UGLY_AUDIO in pilot.sent


@pytest.mark.anyio
async def test_a_meeting_answer_comes_back_on_the_stream_that_asked():
    # Stream id intact: two browsers on one node each have a meeting, and an event delivered to
    # the wrong stream would put one person's transcript on another person's screen.
    pilot = FakeHomePilot()
    sent: list[dict] = []
    link = AvatarLink(
        homepilot_base="http://x", send=lambda frame: _collect(sent, frame), connect=lambda url: _ready(pilot)
    )
    await link.handle({"type": "sig", "stream": "s7", "op": "avatar_open", "payload": {"hello": {}}})

    await pilot.inbox.put(UGLY_MEETING)
    await asyncio.sleep(0.05)

    assert {"type": "ev", "stream": "s7", "payload": UGLY_MEETING} in sent


@pytest.mark.anyio
async def test_the_relay_carries_the_payload_as_text_not_as_an_object():
    # If the relay ever parsed the payload it would have to re-serialise it, and the byte
    # guarantee the direct path makes would quietly stop holding on the cloud path only —
    # which is the harder of the two to notice.
    pilot = FakeHomePilot()
    sent: list[dict] = []
    link = AvatarLink(
        homepilot_base="http://x", send=lambda frame: _collect(sent, frame), connect=lambda url: _ready(pilot)
    )
    await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {}}})
    await pilot.inbox.put(UGLY_MEETING)
    await asyncio.sleep(0.05)

    event = next(f for f in sent if f.get("type") == "ev")
    assert isinstance(event["payload"], str)
    assert event["payload"] == UGLY_MEETING
