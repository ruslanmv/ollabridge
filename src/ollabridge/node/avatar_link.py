"""Avatar sessions over the relay link — the node half.

The bridge's ``/v1/avatar/session`` proxy connects a browser to a HomePilot. When HomePilot
sits on the operator's own machine and the bridge is OllaBridge Cloud, the cloud cannot reach
it: that is the whole reason the relay link exists. This module is what runs on the machine
that *can*.

**Why this needed a new frame and not another ``req``.** Inference over the relay is
request/response — the cloud asks, the node answers, and nothing is ever said unprompted. An
avatar session is not shaped like that. HomePilot starts turns of its own: curiosity, a
greeting, a reaction to something on screen. A node with something to say has nowhere to put it
in a protocol where every frame answers a question the cloud asked. So the hub gained a mirror
pair — ``sig`` down, ``ev`` up — and this module is the only thing that speaks them.

Everything here is per-stream. One node may be carrying several browser sessions at once, and
they must not see each other's frames; ``stream`` is what keeps them apart, end to end.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

#: HomePilot's own route (its spec v1.1 §6.9), same constant the cloud proxy uses.
HOMEPILOT_SESSION_PATH = "/avatar/session"

#: Ops this module answers. Named on the wire so an older node meeting a newer cloud refuses
#: by name rather than silently doing nothing.
OPS = ("avatar_open", "avatar_send", "avatar_close")


def to_ws_url(base: str) -> str:
    """``http(s)://host`` → ``ws(s)://host/avatar/session``."""
    url = (base or "").strip().rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    return url + HOMEPILOT_SESSION_PATH


class AvatarLink:
    """The node's open HomePilot sessions, one per browser stream.

    :param homepilot_base: where HomePilot is, from this machine's point of view
    :param send: sends one frame up the relay link; the caller owns the socket
    :param connect: opens a websocket, injected so tests need no HomePilot
    """

    def __init__(
        self,
        *,
        homepilot_base: str,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        connect: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.homepilot_base = homepilot_base
        self._send = send
        self._connect = connect
        self._sockets: dict[str, Any] = {}
        self._readers: dict[str, asyncio.Task] = {}

    def handles(self, frame: dict[str, Any]) -> bool:
        """Whether this frame is ours. The agent's inference path is untouched."""
        return frame.get("type") == "sig" and frame.get("op") in OPS

    async def handle(self, frame: dict[str, Any]) -> None:
        stream = str(frame.get("stream") or "")
        if not stream:
            return
        op = frame.get("op")
        payload = frame.get("payload") or {}
        if op == "avatar_open":
            await self._open(stream, payload)
        elif op == "avatar_send":
            await self._forward(stream, payload)
        elif op == "avatar_close":
            await self.close(stream)

    async def _open(self, stream: str, payload: dict[str, Any]) -> None:
        if stream in self._sockets:
            return  # already open; a duplicate open is not an error, it is a retry
        try:
            socket = await self._dial(to_ws_url(self.homepilot_base))
        except Exception as exc:  # noqa: BLE001 — every failure is the same to the browser
            logger.info("[avatar-link] HomePilot connect failed: %s", exc)
            await self._emit(stream, {"v": 1, "type": "error", "code": "homepilot_unreachable",
                                      "msg": "HomePilot did not accept the session"})
            await self._emit(stream, None)
            return
        self._sockets[stream] = socket
        # The hello the cloud already authorised and rewrote. This node does not re-decide
        # who may connect: that judgement was made once, at the bridge, with the bridge's
        # credentials. Making it twice would mean two answers to one question.
        hello = payload.get("hello")
        if hello is not None:
            await socket.send(json.dumps(hello, separators=(",", ":")))
        self._readers[stream] = asyncio.create_task(self._pump(stream, socket))

    async def _dial(self, url: str):
        if self._connect is not None:
            return await self._connect(url)
        from ollabridge.core.websocket_client import websocket_connect

        return await websocket_connect(url, max_size=None).__aenter__()

    async def _forward(self, stream: str, payload: dict[str, Any]) -> None:
        socket = self._sockets.get(stream)
        if socket is None:
            return  # the session is gone; a frame for it is not an error worth raising
        with contextlib.suppress(Exception):
            await socket.send(payload if isinstance(payload, str) else json.dumps(payload))

    async def _pump(self, stream: str, socket) -> None:
        """HomePilot → the relay, as `ev` frames, until the socket ends."""
        try:
            while True:
                message = await socket.recv()
                await self._emit(stream, message)
        except Exception:  # noqa: BLE001 — a closed socket is the normal end of this loop
            pass
        finally:
            # `None` is end-of-stream: the browser must learn the far end went away, or it
            # sits on a socket that will never speak again.
            with contextlib.suppress(Exception):
                await self._emit(stream, None)

    async def _emit(self, stream: str, payload: Any) -> None:
        await self._send({"type": "ev", "stream": stream, "payload": payload})

    async def close(self, stream: str) -> None:
        """End one session. Idempotent — both ends may notice at once."""
        task = self._readers.pop(stream, None)
        if task is not None:
            task.cancel()
        socket = self._sockets.pop(stream, None)
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()

    async def aclose(self) -> None:
        """End every session, for when the relay link itself goes down."""
        for stream in list(self._sockets):
            await self.close(stream)
