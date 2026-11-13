"""The two kinds of endpoint the diagnosis talks to, and how each request
is read back as a :class:`~ollabridge.diagnose.models.Sample`.

* :class:`ChatTarget`: an OpenAI-compatible ``/chat/completions`` endpoint.
  That is a model gateway, an Open WebUI server, or OllaBridge itself (which
  measures the route a client really takes, pacing included).
* :class:`McpTarget`: an MCP server over Streamable HTTP. Only protocol
  methods are sent (``initialize``, ``ping``, ``tools/list``); a tool runs
  only when the caller names one.

Both keep one HTTP client with keep-alive for the whole run, so a level
measures the endpoint, not connection setup; the first request of a run is
the cold one and is reported apart.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from ollabridge.addons.providers.errors import upstream_reason
from ollabridge.core.connectivity import classify
from ollabridge.diagnose.models import (
    HTTP_ERROR,
    NETWORK,
    OK,
    PROTOCOL_ERROR,
    RATE_LIMITED,
    TIMEOUT,
    Sample,
)
from ollabridge.diagnose.ratelimit import is_rate_limit, rate_headers, retry_after

#: The same harmless prompt ``ollabridge doctor e2e`` sends.
DEFAULT_PROMPT = "Reply with the single word: pong"
_FILLER = "The quick brown fox jumps over the lazy dog. "

#: Tests set this to an ``httpx`` transport so nothing touches the network.
TRANSPORT: httpx.AsyncBaseTransport | None = None

CLIENT_INFO = {"name": "ollabridge-diagnose", "version": "1"}


def filler_prompt(tokens: int) -> str:
    """A prompt of roughly *tokens* tokens (about four characters each for
    English text). The endpoint's own count is what the report shows."""
    size = max(0, tokens) * 4
    body = (_FILLER * (size // len(_FILLER) + 1))[:size]
    return (
        "The text between the markers is filler that pads this request to a known size. Ignore it.\n"
        f"<filler>\n{body}\n</filler>\n{DEFAULT_PROMPT}"
    )


def display_url(url: str) -> str:
    """The URL without credentials or query string, safe to print."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


class _Target:
    kind = ""

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self._headers = dict(headers or {})
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._host = urlsplit(url).hostname or ""

    async def __aenter__(self):
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 10.0)),
            headers=self._headers,
            transport=self._transport or TRANSPORT,
            limits=httpx.Limits(max_connections=256, max_keepalive_connections=64),
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("use the target as an async context manager")
        return self._http

    def _redact(self, text: str | None) -> str:
        out = text or ""
        for value in self._headers.values():
            secret = value.split(" ", 1)[-1] if value.lower().startswith("bearer ") else value
            if len(secret) >= 6:
                out = out.replace(secret, "***")
        return out

    def _failure(self, exc: BaseException, started: float) -> Sample:
        """A request that got no HTTP answer."""
        fault = classify(exc)
        if fault is not None and fault.kind in ("read_timeout", "connect_timeout"):
            outcome = TIMEOUT
        elif fault is not None:
            outcome = NETWORK
        else:
            outcome = PROTOCOL_ERROR
        detail = fault.describe(self._host) if fault is not None else f"{type(exc).__name__}: {exc}"
        if outcome == TIMEOUT:
            detail += f" (limit {self.timeout:g} s)"
        return Sample(outcome, time.perf_counter() - started, detail=self._redact(detail), accepted_requests=0)

    def _from_response(self, status: int, headers: Mapping[str, str], body: str, seconds: float) -> Sample:
        limits = rate_headers(headers)
        if 200 <= status < 300:
            return Sample(OK, seconds, status=status, limits=limits, accepted_requests=1)
        reason = upstream_reason(self._redact(body)) or ""
        if is_rate_limit(status, body):
            return Sample(
                RATE_LIMITED,
                seconds,
                status=status,
                retry_after=retry_after(headers),
                detail=f"HTTP {status}" + (f": {reason}" if reason else ""),
                limits=limits,
                accepted_requests=0,
            )
        return Sample(
            HTTP_ERROR,
            seconds,
            status=status,
            detail=f"HTTP {status}" + (f": {reason}" if reason else ""),
            limits=limits,
            accepted_requests=1,
        )


# ── chat ──────────────────────────────────────────────────────────────────


class ChatTarget(_Target):
    kind = "chat"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        chat_path: str = "/chat/completions",
        timeout: float = 60.0,
        max_tokens: int = 16,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        merged = dict(headers or {})
        if api_key:
            merged.setdefault("Authorization", f"Bearer {api_key}")
        super().__init__(
            base_url.rstrip("/") + "/" + chat_path.lstrip("/"),
            headers=merged,
            timeout=timeout,
            transport=transport,
        )
        self.model = model
        self.max_tokens = max_tokens
        # Newer OpenAI-style servers want ``max_completion_tokens``; switched
        # once, when the endpoint says so.
        self._tokens_key = "max_tokens"
        self._stream_usage = True

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "url": display_url(self.url), "model": self.model, "timeout_s": self.timeout}

    def _payload(self, prompt: str | None, max_tokens: int | None) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt or DEFAULT_PROMPT}],
            self._tokens_key: max_tokens or self.max_tokens,
        }

    async def call(
        self, *, prompt: str | None = None, max_tokens: int | None = None, stream: bool = False
    ) -> Sample:
        started = time.perf_counter()
        try:
            sample = await (self._streamed if stream else self._plain)(prompt, max_tokens, started)
            if (
                sample.outcome == HTTP_ERROR
                and sample.status == 400
                and "max_completion_tokens" in sample.detail
                and self._tokens_key == "max_tokens"
            ):
                self._tokens_key = "max_completion_tokens"
                again = await (self._streamed if stream else self._plain)(prompt, max_tokens, time.perf_counter())
                again.http_requests += sample.http_requests
                again.accepted_requests += sample.accepted_requests
                return again
            return sample
        except Exception as exc:  # noqa: BLE001 - every failure becomes a sample
            return self._failure(exc, started)

    async def _plain(self, prompt: str | None, max_tokens: int | None, started: float) -> Sample:
        resp = await self.http.post(self.url, json=self._payload(prompt, max_tokens))
        sample = self._from_response(resp.status_code, resp.headers, resp.text, time.perf_counter() - started)
        if sample.ok:
            try:
                usage = (resp.json() or {}).get("usage") or {}
            except ValueError:
                usage = {}
            sample.tokens_in = usage.get("prompt_tokens")
            sample.tokens_out = usage.get("completion_tokens")
        return sample

    async def _streamed(self, prompt: str | None, max_tokens: int | None, started: float) -> Sample:
        payload = {**self._payload(prompt, max_tokens), "stream": True}
        if self._stream_usage:
            payload["stream_options"] = {"include_usage": True}
        async with self.http.stream("POST", self.url, json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "replace")
                if resp.status_code == 400 and "stream_options" in body and self._stream_usage:
                    self._stream_usage = False
                    again = await self._streamed(prompt, max_tokens, time.perf_counter())
                    again.http_requests += 1
                    again.accepted_requests += 1
                    return again
                return self._from_response(resp.status_code, resp.headers, body, time.perf_counter() - started)
            ttft: float | None = None
            chunks = 0
            usage: dict[str, Any] = {}
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                for choice in event.get("choices") or []:
                    delta = (choice or {}).get("delta") or {}
                    if delta.get("content") or delta.get("reasoning_content") or delta.get("reasoning"):
                        chunks += 1
                        if ttft is None:
                            ttft = time.perf_counter() - started
            return Sample(
                OK,
                time.perf_counter() - started,
                status=200,
                ttft=ttft,
                tokens_in=usage.get("prompt_tokens"),
                # One streamed chunk is about one token when the endpoint
                # does not report usage.
                tokens_out=usage.get("completion_tokens") or chunks or None,
                limits=rate_headers(resp.headers),
                accepted_requests=1,
            )

    def op(self, *, prompt: str | None = None, max_tokens: int | None = None, stream: bool = False):
        async def run() -> Sample:
            return await self.call(prompt=prompt, max_tokens=max_tokens, stream=stream)

        run.cost = 1  # type: ignore[attr-defined]
        return run


# ── MCP (Streamable HTTP) ─────────────────────────────────────────────────


def _rpc_message(content_type: str, body: str, want_id: Any) -> dict[str, Any] | None:
    """The JSON-RPC response in an answer that is plain JSON or an SSE stream."""

    def pick(obj: Any) -> dict[str, Any] | None:
        candidates = obj if isinstance(obj, list) else [obj]
        for item in candidates:
            if isinstance(item, dict) and ("result" in item or "error" in item):
                if item.get("id") == want_id or item.get("id") is None:
                    return item
        return None

    if "text/event-stream" in (content_type or "").lower():
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    found = pick(json.loads(line[5:].strip()))
                except ValueError:
                    continue
                if found is not None:
                    return found
        return None
    try:
        return pick(json.loads(body))
    except ValueError:
        return None


class McpTarget(_Target):
    kind = "mcp"

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        protocol_version: str = "2025-06-18",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(url, headers=headers, timeout=timeout, transport=transport)
        self.protocol_version = protocol_version
        self.server: dict[str, Any] = {}
        self.session: str | None = None  # the shared session, once opened
        self.stateful: bool | None = None  # does the server issue session ids?
        self._next_id = 0

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "url": display_url(self.url),
            "server": self.server.get("name"),
            "server_version": self.server.get("version"),
            "protocol": self.protocol_version,
            "sessions": self.stateful,
            "timeout_s": self.timeout,
        }

    async def rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session: str | None = None,
        notify: bool = False,
    ) -> Sample:
        """One JSON-RPC message: one HTTP request."""
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._next_id += 1
            body["id"] = self._next_id
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if session:
            headers["Mcp-Session-Id"] = session
        if method != "initialize":
            headers["MCP-Protocol-Version"] = self.protocol_version
        started = time.perf_counter()
        try:
            resp = await self.http.post(self.url, json=body, headers=headers)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a sample
            return self._failure(exc, started)
        sample = self._from_response(resp.status_code, resp.headers, resp.text, time.perf_counter() - started)
        sample.session = resp.headers.get("mcp-session-id") or session
        if sample.ok and not notify:
            message = _rpc_message(resp.headers.get("content-type", ""), resp.text, body["id"])
            if message is None:
                sample.outcome = PROTOCOL_ERROR
                sample.detail = "the answer holds no JSON-RPC response (is this a Streamable HTTP MCP endpoint?)"
            elif "error" in message:
                err = message.get("error") or {}
                sample.outcome = PROTOCOL_ERROR
                sample.detail = self._redact(f"JSON-RPC error {err.get('code')}: {err.get('message')}")
                sample.data = message
            else:
                sample.data = message.get("result")
        return sample

    async def handshake(self) -> Sample:
        """``initialize`` + ``notifications/initialized``: two HTTP requests."""
        init = await self.rpc(
            "initialize",
            {"protocolVersion": self.protocol_version, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        if not init.ok:
            return init
        if isinstance(init.data, dict):
            self.protocol_version = init.data.get("protocolVersion") or self.protocol_version
            self.server = init.data.get("serverInfo") or self.server
        self.stateful = bool(init.session)
        note = await self.rpc("notifications/initialized", session=init.session, notify=True)
        return Sample(
            OK if note.ok else note.outcome,
            init.seconds + note.seconds,
            status=note.status,
            retry_after=note.retry_after,
            detail=note.detail,
            limits=note.limits or init.limits,
            http_requests=2,
            accepted_requests=init.accepted_requests + note.accepted_requests,
            session=init.session,
            data=init.data,
        )

    async def end_session(self, session: str | None) -> Sample | None:
        """``DELETE`` the session; ``None`` when the server issued none."""
        if not session:
            return None
        started = time.perf_counter()
        try:
            resp = await self.http.request(
                "DELETE",
                self.url,
                headers={"Mcp-Session-Id": session, "MCP-Protocol-Version": self.protocol_version},
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(exc, started)
        sample = self._from_response(resp.status_code, resp.headers, resp.text, time.perf_counter() - started)
        if sample.outcome == HTTP_ERROR and sample.status in (404, 405):
            # The server does not end sessions on request: allowed by the spec.
            sample.outcome, sample.detail = OK, ""
        return sample

    async def open_session(self) -> Sample:
        sample = await self.handshake()
        if sample.ok:
            self.session = sample.session
        return sample

    async def close_session(self) -> Sample | None:
        session, self.session = self.session, None
        return await self.end_session(session)

    async def cycle(self, method: str = "ping", params: dict[str, Any] | None = None) -> Sample:
        """One call the way a client that opens a session per call makes it:
        handshake, the call, end the session. ``http_requests`` on the result
        is what that costs at the server's edge."""
        started = time.perf_counter()
        parts: list[Sample] = [await self.handshake()]
        if parts[0].ok:
            parts.append(await self.rpc(method, params, session=parts[0].session))
            ended = await self.end_session(parts[0].session)
            if ended is not None:
                parts.append(ended)
        failed = next((p for p in parts if not p.ok), None)
        last = failed or parts[-1]
        return Sample(
            failed.outcome if failed else OK,
            time.perf_counter() - started,
            status=last.status,
            retry_after=last.retry_after,
            detail=last.detail,
            limits=next((p.limits for p in reversed(parts) if p.limits), None),
            http_requests=sum(p.http_requests for p in parts),
            accepted_requests=sum(p.accepted_requests for p in parts),
            data=parts[1].data if len(parts) > 1 else None,
        )

    def op(self, method: str = "ping", params: dict[str, Any] | None = None, *, new_session: bool = False):
        """An operation for the engine: on the shared session (one request),
        or with a session of its own (``cost`` requests)."""

        async def reused() -> Sample:
            return await self.rpc(method, params, session=self.session)

        async def fresh() -> Sample:
            return await self.cycle(method, params)

        run = fresh if new_session else reused
        run.cost = (4 if self.stateful is not False else 3) if new_session else 1  # type: ignore[attr-defined]
        return run
