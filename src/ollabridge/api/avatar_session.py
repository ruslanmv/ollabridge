"""Avatar session proxy — one socket from the browser to a HomePilot behind the bridge.

Additive module. Nothing existing changes; this adds ``ws /v1/avatar/session``.

**Why the bridge and not a direct socket.** The 3D avatar used to reach HomePilot by having
the user type a ``wss://`` address into its settings. That address only works where the
*browser* can open it, which is one machine and nowhere else: an HTTPS page cannot open
``ws://localhost:8000`` — mixed content — and a hosted page's "localhost" is the server it was
served from, not the user's PC. Meanwhile the user has already linked OllaBridge to get
models, and OllaBridge is running next to HomePilot. So the socket goes here.

**Credential injection is the point, not a detail.** The browser presents *OllaBridge's* own
credential — the pairing token or API key it already holds. This proxy validates that, then
replaces it with HomePilot's key before forwarding. HomePilot's key never reaches the browser,
and the browser never needed a second field to put one in. That second field is also why the
direct path did not work as shipped: the client had nowhere to store a HomePilot token, sent
an empty string, and HomePilot's verifier is a presence check.

**What this module is not.** It is not a protocol participant. It reads exactly one frame —
the ``hello``, because that is where the token is — rewrites one field of it, and pumps
everything after that verbatim in both directions. Every message type, every version bump and
every future field is HomePilot's business and the client's; adding an opinion here would mean
two implementations of one protocol, drifting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["avatar"])

#: The path HomePilot mounts its channel on (its spec v1.1 §6.9). Not configurable here: it is
#: HomePilot's route, and a knob for it would be a knob nobody can set correctly.
HOMEPILOT_SESSION_PATH = "/avatar/session"

#: What ``/health`` advertises. The client treats an absent block as "cannot relay", so this
#: list is a promise: a name here means the frames for it survive the round trip.
AVATAR_FEATURES = ["directives", "curiosity", "vision", "panels", "meetings"]

#: Sent upstream when the operator configured no HomePilot key. HomePilot's default verifier is
#: a presence check, so *something* non-empty has to travel or the handshake is refused. Named
#: rather than blank so it is identifiable in a HomePilot log.
DEFAULT_UPSTREAM_TOKEN = "ollabridge"

#: Long enough for a slow phone to send its hello, short enough that a socket opened by a port
#: scanner does not sit here.
HELLO_TIMEOUT_S = 15.0


def websockets_available() -> bool:
    """Whether the client library is installed.

    ``websockets`` is a declared dependency, but an install can be older than the dependency
    list. Advertising a relay we cannot open would be worse than not advertising one: the
    client would stop falling back to the chat path, which still carries directives.
    """
    try:
        import websockets  # noqa: F401

        return True
    except Exception:
        return False


def homepilot_target() -> tuple[str, str] | None:
    """``(ws_url, api_key)`` for the configured HomePilot, or ``None`` if there is not one.

    Reads the same runtime settings the HomePilot *source* uses, so enabling HomePilot under
    Local Runtimes is the only thing an operator does. There is no second place to configure.
    """
    try:
        from ollabridge.core import runtime_settings as rts
        from ollabridge.core.settings import settings
    except Exception:
        return None

    cfg = rts.get_all()
    if not cfg.get("homepilot_enabled", False):
        return None
    base = str(cfg.get("homepilot_base_url") or settings.HOMEPILOT_BASE_URL or "").strip()
    if not base:
        return None
    key = str(cfg.get("homepilot_api_key") or settings.HOMEPILOT_API_KEY or "").strip()

    url = base.rstrip("/")
    if url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    elif not url.startswith(("ws://", "wss://")):
        url = "ws://" + url
    return url + HOMEPILOT_SESSION_PATH, key


def relay_node(app: Any) -> str | None:
    """A connected node that advertises ``avatar``, or ``None``.

    This is the Cloud case. The browser reaches the Cloud, the Cloud cannot reach the
    operator's HomePilot — that is what the relay link exists for — and a node on the machine
    that *can* has said so in its hello. Picking by advertised capability rather than by
    "any node" is what makes a node without a HomePilot decline in advance instead of
    accepting a socket it will then fail.
    """
    try:
        registry = app.state.obridge.registry
        for node in registry.healthy_nodes():
            caps = list((node.meta or {}).get("capabilities") or [])
            if node.connector == "relay_link" and "avatar" in caps:
                return node.node_id
    except Exception:
        return None
    return None


def health_block(app: Any = None) -> dict[str, Any] | None:
    """The ``avatar`` block for ``/health``, or ``None`` when there is nothing to advertise.

    Absence is the whole version negotiation: every OllaBridge released before this module
    omits it, and the client reads that as "this bridge cannot relay the session" rather than
    as an error. So this must return ``None`` whenever the relay would not actually work.
    """
    # Either route will do, and they are checked in the order the proxy will try them: a
    # HomePilot this process can reach directly, else one behind a relay node.
    direct = websockets_available() and homepilot_target() is not None
    relayed = app is not None and relay_node(app) is not None
    if not (direct or relayed):
        return None
    return {"session": "/v1/avatar/session", "features": list(AVATAR_FEATURES)}


def authorize(token: str, websocket: WebSocket) -> bool:
    """Validate a browser's token as an OllaBridge credential.

    Mirrors :func:`ollabridge.core.security.require_api_key` — the same three modes, the same
    loopback trust — rather than inventing a second rule for sockets. It cannot *call* that
    function, which is an HTTP dependency wanting a ``Request`` and headers; a browser cannot
    set headers on a WebSocket, which is why the token arrives in the ``hello`` at all.
    """
    from ollabridge.core import security

    mode = security._effective_auth_mode()
    client = websocket.client
    loopback = bool(client and client.host in ("127.0.0.1", "::1", "localhost"))

    if mode == "local-trust":
        return loopback or bool(token and token in security._keys())

    key = (token or "").strip()
    if mode == "pairing":
        if key and key in security._keys():
            return True
        mgr = security._pairing_manager
        if key and mgr and mgr.validate_token(key):
            return True
        return loopback

    return bool(key) and key in security._keys()


def upstream_token(configured_key: str) -> str:
    """What travels to HomePilot in the hello.

    The operator's key when there is one. When there is not, a named marker rather than the
    empty string: HomePilot's default verifier is a presence check, so an empty token is
    refused — which is exactly how the browser's direct path failed before this proxy existed.
    Returning "" here would reproduce that bug one layer down.
    """
    return (configured_key or "").strip() or DEFAULT_UPSTREAM_TOKEN


def _error(code: str, msg: str) -> str:
    """An error in HomePilot's own envelope, so the client needs no special case for ours."""
    return json.dumps({"v": 1, "type": "error", "code": code, "msg": msg}, separators=(",", ":"))


async def _pump(read, write) -> None:
    """Forward frames until one side stops. Verbatim: this is a pipe, not a participant."""
    while True:
        message = await read()
        if message is None:
            return
        await write(message)


@router.websocket("/v1/avatar/session")
async def avatar_session(websocket: WebSocket) -> None:  # pragma: no cover - transport
    """Browser ⇄ OllaBridge ⇄ HomePilot, with the credential swapped in the middle."""
    await websocket.accept()

    target = homepilot_target()
    node_id = relay_node(websocket.app)
    if target is None and node_id is None:
        await websocket.send_text(_error("homepilot_unavailable", "no HomePilot is enabled on this bridge"))
        await websocket.close()
        return
    if target is not None and not websockets_available():
        await websocket.send_text(_error("relay_unavailable", "this bridge cannot open an upstream socket"))
        await websocket.close()
        return

    upstream_url, upstream_key = target if target is not None else ("", "")

    # The hello carries the token, so it is the one frame this proxy reads.
    try:
        first_raw = await asyncio.wait_for(websocket.receive_text(), timeout=HELLO_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close()
        return

    try:
        hello = json.loads(first_raw)
    except Exception:
        await websocket.send_text(_error("bad_json", "not JSON"))
        await websocket.close()
        return

    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await websocket.send_text(_error("unauthenticated", "send hello first"))
        await websocket.close()
        return

    if not authorize(str(hello.get("auth") or ""), websocket):
        # Deliberately the same code HomePilot uses, because from the client's side it is the
        # same event: the pairing it presented was not accepted.
        await websocket.send_text(_error("unauthorized", "pairing rejected"))
        await websocket.close()
        return

    # The swap. Everything else in the hello — client, caps, version — is the client's to say.
    hello["auth"] = upstream_token(upstream_key)

    # Cloud: HomePilot is on the operator's machine, which this process cannot reach. Hand the
    # session to the node that can, and pump through the relay instead.
    if target is None:
        await _relayed_session(websocket, node_id, hello)
        return

    import websockets

    try:
        upstream = await websockets.connect(upstream_url, max_size=None, open_timeout=10)
    except Exception as exc:  # noqa: BLE001 — every failure here is the same to the client
        logger.info("[avatar-session] upstream connect failed: %s", exc)
        await websocket.send_text(_error("homepilot_unreachable", "HomePilot did not accept the session"))
        await websocket.close()
        return

    async def from_client():
        try:
            return await websocket.receive_text()
        except WebSocketDisconnect:
            return None
        except Exception:
            return None

    async def from_upstream():
        try:
            return await upstream.recv()
        except Exception:
            return None

    try:
        await upstream.send(json.dumps(hello, separators=(",", ":")))
        # Both directions, and whichever ends first ends the session: a half-open relay is a
        # client that thinks it is connected and a server that has stopped answering.
        up = asyncio.create_task(_pump(from_client, upstream.send))
        down = asyncio.create_task(_pump(from_upstream, websocket.send_text))
        _, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    except Exception as exc:  # noqa: BLE001
        logger.info("[avatar-session] relay ended: %s", exc)
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


async def _relayed_session(websocket: WebSocket, node_id: str, hello: dict[str, Any]) -> None:  # pragma: no cover
    """The Cloud path: browser ⇄ Cloud ⇄ relay node ⇄ HomePilot.

    Same shape as the direct path — one hello, then a verbatim pipe — but the two halves speak
    different transports. Down is a ``sig`` frame per message; up is an ``ev`` frame arriving on
    the stream's queue. The stream id is what keeps one node's several browser sessions apart,
    and closing it is what stops a node relaying into a socket nobody is holding.
    """
    hub = websocket.app.state.relay_hub
    stream_id, inbox = await hub.open_stream(node_id)
    try:
        await hub.signal(node_id, stream_id, "avatar_open", {"hello": hello})
    except Exception as exc:
        logger.info("[avatar-session] node signal failed: %s", exc)
        await hub.close_stream(stream_id)
        await websocket.send_text(_error("homepilot_unreachable", "the paired device did not accept the session"))
        await websocket.close()
        return

    async def pump_down() -> None:
        while True:
            try:
                raw = await websocket.receive_text()
            except Exception:
                return
            try:
                await hub.signal(node_id, stream_id, "avatar_send", raw)
            except Exception:
                return

    async def pump_up() -> None:
        while True:
            # `None` is end-of-stream: the node's socket to HomePilot closed, or the node
            # itself went away. Either way the browser is told rather than left waiting.
            payload = await inbox.get()
            if payload is None:
                return
            try:
                await websocket.send_text(payload if isinstance(payload, str) else json.dumps(payload))
            except Exception:
                return

    down = asyncio.create_task(pump_down())
    up = asyncio.create_task(pump_up())
    try:
        _, pending = await asyncio.wait({down, up}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        with contextlib.suppress(Exception):
            await hub.signal(node_id, stream_id, "avatar_close", {})
        await hub.close_stream(stream_id)
        with contextlib.suppress(Exception):
            await websocket.close()
