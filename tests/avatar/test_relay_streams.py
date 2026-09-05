"""The `ev`/`sig` frames — what lets HomePilot speak first through the Cloud.

Inference over the relay is request/response: the Cloud asks, the node answers, and nothing is
ever said unprompted. An avatar session is not shaped like that. HomePilot starts turns of its
own — curiosity, a greeting, a reaction to the screen — and a node with something to say had
nowhere to put it in a protocol where every frame answers a question the Cloud asked.

So the hub gained a mirror pair, and this file is about the three properties that make it safe
rather than merely working:

  * an event reaches **one** stream, the one that owns it;
  * a node cannot push into a stream it does not own;
  * when a node vanishes, every session on it is woken rather than left waiting.

The third is the one that is invisible until it happens to somebody.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.api.relay import RelayHub
from ollabridge.node.avatar_link import AvatarLink, to_ws_url


class FakeRegistry:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, node_id: str) -> None:
        self.removed.append(node_id)


class FakeWs:
    """Records the frames the hub sent to a node."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


async def hub_with_node(node_id: str = "node-a") -> tuple[RelayHub, FakeWs]:
    hub = RelayHub(FakeRegistry())
    ws = FakeWs()
    await hub.attach(node_id, ws)
    return hub, ws


# ── fan-out ──────────────────────────────────────────────────────────────────


class TestFanOut:
    @pytest.mark.anyio
    async def test_an_event_reaches_the_stream_that_owns_it(self):
        hub, _ = await hub_with_node()
        stream, inbox = await hub.open_stream("node-a")

        await hub.handle_frame("node-a", {"type": "ev", "stream": stream, "payload": '{"type":"intent"}'})

        assert inbox.get_nowait() == '{"type":"intent"}'

    @pytest.mark.anyio
    async def test_and_reaches_no_other_stream_on_the_same_node(self):
        # One node may carry several browser sessions. Delivering to all of them would put
        # one person's conversation in front of another.
        hub, _ = await hub_with_node()
        mine, my_inbox = await hub.open_stream("node-a")
        _, their_inbox = await hub.open_stream("node-a")

        await hub.handle_frame("node-a", {"type": "ev", "stream": mine, "payload": "for-me"})

        assert my_inbox.get_nowait() == "for-me"
        assert their_inbox.empty()

    @pytest.mark.anyio
    async def test_a_node_cannot_push_into_a_stream_it_does_not_own(self):
        hub, _ = await hub_with_node("node-a")
        await hub.attach("node-b", FakeWs())
        stream, inbox = await hub.open_stream("node-a")

        await hub.handle_frame("node-b", {"type": "ev", "stream": stream, "payload": "injected"})

        assert inbox.empty()

    @pytest.mark.anyio
    async def test_an_event_for_an_unknown_stream_is_dropped_quietly(self):
        hub, _ = await hub_with_node()
        await hub.handle_frame("node-a", {"type": "ev", "stream": "gone", "payload": "x"})

    @pytest.mark.anyio
    async def test_a_closed_stream_stops_receiving(self):
        hub, _ = await hub_with_node()
        stream, inbox = await hub.open_stream("node-a")
        await hub.close_stream(stream)

        await hub.handle_frame("node-a", {"type": "ev", "stream": stream, "payload": "late"})

        assert inbox.empty()

    @pytest.mark.anyio
    async def test_closing_twice_is_not_an_error(self):
        # Both ends may notice the end of a session at the same moment.
        hub, _ = await hub_with_node()
        stream, _ = await hub.open_stream("node-a")
        await hub.close_stream(stream)
        await hub.close_stream(stream)


# ── the request/response path is untouched ───────────────────────────────────


class TestFramesStaySeparate:
    @pytest.mark.anyio
    async def test_a_res_still_resolves_its_request(self):
        hub, ws = await hub_with_node()
        task = asyncio.create_task(hub.request("node-a", "models", {}, timeout_s=2))
        await asyncio.sleep(0)
        req_id = ws.sent[0]["id"]

        await hub.handle_frame("node-a", {"type": "res", "id": req_id, "ok": True, "data": {}})

        assert (await task)["ok"] is True

    @pytest.mark.anyio
    async def test_an_ev_carrying_a_pending_id_still_does_not_resolve_it(self):
        # The adversarial shape, not the accidental one. A test that sends an `ev` with a
        # fresh stream id proves nothing: the ids could never have collided, so it passes
        # whatever the dispatch does. The frame that matters is one that names a real pending
        # request — a node echoing an id, by bug or by design. If that resolved the future,
        # one unrelated intent from HomePilot would return as somebody's chat completion.
        hub, ws = await hub_with_node()
        task = asyncio.create_task(hub.request("node-a", "models", {}, timeout_s=0.3))
        await asyncio.sleep(0)
        req_id = ws.sent[0]["id"]
        stream, _ = await hub.open_stream("node-a")

        await hub.handle_frame("node-a", {"type": "ev", "id": req_id, "stream": stream, "payload": "noise"})

        assert req_id in hub._pending, "the request was resolved by an event"
        with pytest.raises(asyncio.TimeoutError):
            await task

    @pytest.mark.anyio
    async def test_a_sig_allocates_no_future_to_answer(self):
        # A `req` with its response ignored would leak a future per frame, and a session sends
        # thousands. `sig` is the reason there is a second frame type rather than a convention.
        hub, ws = await hub_with_node()
        stream, _ = await hub.open_stream("node-a")

        await hub.signal("node-a", stream, "avatar_send", {"type": "ctx"})

        assert hub._pending == {}
        assert ws.sent[-1] == {"type": "sig", "stream": stream, "op": "avatar_send", "payload": {"type": "ctx"}}

    @pytest.mark.anyio
    async def test_signalling_a_vanished_node_raises_rather_than_silently_dropping(self):
        hub, _ = await hub_with_node()
        stream, _ = await hub.open_stream("node-a")
        await hub.detach("node-a")

        with pytest.raises(RuntimeError):
            await hub.signal("node-a", stream, "avatar_send", {})


# ── the case nobody sees until it happens ────────────────────────────────────


class TestNodeDisappears:
    @pytest.mark.anyio
    async def test_every_stream_on_a_detached_node_is_woken(self):
        # Without this a browser sits on a socket whose far end is gone, showing a connected
        # avatar that will never move again, until its own timeout — minutes later.
        hub, _ = await hub_with_node()
        _, first = await hub.open_stream("node-a")
        _, second = await hub.open_stream("node-a")

        await hub.detach("node-a")

        assert await asyncio.wait_for(first.get(), 1) is None
        assert await asyncio.wait_for(second.get(), 1) is None

    @pytest.mark.anyio
    async def test_streams_on_other_nodes_are_untouched(self):
        hub, _ = await hub_with_node("node-a")
        await hub.attach("node-b", FakeWs())
        _, survivor = await hub.open_stream("node-b")

        await hub.detach("node-a")

        assert survivor.empty()

    @pytest.mark.anyio
    async def test_a_slow_reader_gets_the_newest_frames_not_the_oldest(self):
        # A backgrounded tab stops reading. The queue is bounded so it cannot grow without
        # limit, and when it overflows a live conversation should stay current rather than
        # replay a backlog nobody wants.
        hub, _ = await hub_with_node()
        stream, inbox = await hub.open_stream("node-a", maxsize=2)

        for n in range(4):
            await hub.handle_frame("node-a", {"type": "ev", "stream": stream, "payload": f"m{n}"})

        drained = [inbox.get_nowait() for _ in range(inbox.qsize())]
        assert drained == ["m2", "m3"]


# ── the node half ────────────────────────────────────────────────────────────


class FakeHomePilot:
    """A HomePilot socket the node can talk to, with no HomePilot."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        message = await self.inbox.get()
        if message is None:
            raise ConnectionError("closed")
        return message

    async def close(self) -> None:
        self.closed = True


class TestNodeLink:
    def test_the_url_follows_the_scheme_it_was_given(self):
        assert to_ws_url("http://localhost:8000") == "ws://localhost:8000/avatar/session"
        assert to_ws_url("https://pilot.example/") == "wss://pilot.example/avatar/session"
        assert to_ws_url("pilot.lan:8000") == "ws://pilot.lan:8000/avatar/session"

    def test_it_claims_only_its_own_frames(self):
        link = AvatarLink(homepilot_base="http://x", send=None)
        assert link.handles({"type": "sig", "op": "avatar_open"}) is True
        assert link.handles({"type": "req", "op": "chat"}) is False
        assert link.handles({"type": "sig", "op": "something_else"}) is False

    @pytest.mark.anyio
    async def test_open_forwards_the_hello_the_cloud_already_authorised(self):
        # The node does not re-decide who may connect. That judgement was made once, at the
        # bridge, with the bridge's credentials; making it twice would mean two answers.
        pilot = FakeHomePilot()
        sent: list[dict] = []
        link = AvatarLink(
            homepilot_base="http://x",
            send=lambda frame: _collect(sent, frame),
            connect=lambda url: _ready(pilot),
        )

        await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {"auth": "hp"}}})

        assert json.loads(pilot.sent[0]) == {"auth": "hp"}

    @pytest.mark.anyio
    async def test_homepilot_frames_come_back_as_events_on_the_right_stream(self):
        pilot = FakeHomePilot()
        sent: list[dict] = []
        link = AvatarLink(
            homepilot_base="http://x",
            send=lambda frame: _collect(sent, frame),
            connect=lambda url: _ready(pilot),
        )
        await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {}}})

        await pilot.inbox.put('{"type":"intent"}')
        await asyncio.sleep(0.05)

        assert {"type": "ev", "stream": "s1", "payload": '{"type":"intent"}'} in sent

    @pytest.mark.anyio
    async def test_a_closed_homepilot_ends_the_stream_rather_than_going_quiet(self):
        pilot = FakeHomePilot()
        sent: list[dict] = []
        link = AvatarLink(
            homepilot_base="http://x",
            send=lambda frame: _collect(sent, frame),
            connect=lambda url: _ready(pilot),
        )
        await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {}}})

        await pilot.inbox.put(None)
        await asyncio.sleep(0.05)

        assert sent[-1] == {"type": "ev", "stream": "s1", "payload": None}

    @pytest.mark.anyio
    async def test_an_unreachable_homepilot_is_reported_then_ended(self):
        sent: list[dict] = []

        async def refuse(url):
            raise ConnectionError("refused")

        link = AvatarLink(homepilot_base="http://x", send=lambda frame: _collect(sent, frame), connect=refuse)
        await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {}}})

        assert sent[0]["payload"]["code"] == "homepilot_unreachable"
        assert sent[1]["payload"] is None

    @pytest.mark.anyio
    async def test_frames_for_a_session_that_is_gone_are_dropped_not_raised(self):
        link = AvatarLink(homepilot_base="http://x", send=None)
        await link.handle({"type": "sig", "stream": "unknown", "op": "avatar_send", "payload": "{}"})

    @pytest.mark.anyio
    async def test_close_ends_the_socket_and_is_idempotent(self):
        pilot = FakeHomePilot()
        link = AvatarLink(
            homepilot_base="http://x", send=lambda frame: _collect([], frame), connect=lambda url: _ready(pilot)
        )
        await link.handle({"type": "sig", "stream": "s1", "op": "avatar_open", "payload": {"hello": {}}})
        await link.close("s1")
        await link.close("s1")
        assert pilot.closed is True


async def _collect(sink: list, frame: dict) -> None:
    sink.append(frame)


async def _ready(value):
    return value


@pytest.fixture
def anyio_backend():
    return "asyncio"
