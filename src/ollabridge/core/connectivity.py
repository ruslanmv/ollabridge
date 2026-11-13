"""Is this machine offline, or is the provider just slow?

On a train, in a tunnel or when a laptop hops from Wi-Fi to a phone hotspot,
requests to remote providers used to hang until the 120 s read timeout and
then report ``provider_timeout``, the same answer as a model that is merely
slow. The user could not tell "my network dropped" from "the provider is
overloaded", and every request made while offline waited the full two
minutes again.

This module applies the pattern mobile OSes and service meshes use:

* **Classify the failure.** A DNS error, an unreachable network, a connect
  timeout or a connection dropped mid-request is a *transport* fault; an HTTP
  status is the provider talking. Only transport faults raise the question.
* **Validate with a probe, not a guess.** A transport fault triggers a quick
  TCP connect (``probe_timeout_s``, default 3 s) to the remote providers
  already configured here. If none answers, the network is down; if one does,
  the failing provider has its own problem. No third-party "connectivity
  check" host is ever contacted: only addresses this gateway already talks to
  (or the proxy it goes through).
* **Circuit breaker while offline.** Requests for remote models fail fast with
  HTTP 503 ``network_offline`` and a ``Retry-After``, instead of waiting for a
  timeout. Local models keep working. A background probe with exponential
  backoff (2 s … 30 s) closes the circuit as soon as the network is back, and
  any request while offline re-checks first when the last probe is older than
  ``recheck_s``, so the first request after the tunnel already goes through.
* **Stall watchdog for requests in flight.** A request that has not answered
  after ``stall_after_s`` (default 15 s) gets a probe every
  ``stall_every_s``. Two misses in a row, or a change of this machine's own
  network address (Wi-Fi → hotspot: the open TCP connection is gone for good),
  abort it with ``connection_lost`` after about 25 s instead of 120 s. When the
  provider stays reachable the request keeps waiting: a long generation is
  not an outage, and the eventual timeout says the server was reachable.
* **Change-only logging.** One WARNING when the connection is lost, one INFO
  with the outage length when it is back; ``snapshot()`` feeds ``/health`` so
  the dashboard can show it.

Settings (environment):

``OLLABRIDGE_NETWORK_CHECK``
    ``off`` disables all of this (behaviour as before). Default on.
``OLLABRIDGE_NETWORK_PROBE_TARGETS``
    Comma-separated ``host:port`` list to probe instead of the configured
    providers, e.g. a corporate proxy or gateway.
``OLLABRIDGE_STALL_CHECK_AFTER_S``
    Seconds before the watchdog starts probing an unanswered request
    (default 15, ``0`` disables the watchdog).
"""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import logging
import os
import socket
import ssl
import time
import urllib.request
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import urlsplit

log = logging.getLogger("ollabridge.network")

T = TypeVar("T")

ONLINE = "online"
OFFLINE = "offline"
UNKNOWN = "unknown"

# Probing more targets says nothing new and costs sockets.
MAX_PROBE_TARGETS = 4

# RFC 5737 documentation address. ``connect()`` on a UDP socket sends nothing:
# it only asks the kernel which local address would carry traffic off this
# machine, which is how a network switch (Wi-Fi → hotspot) shows up.
_ROUTE_PROBE_ADDR = ("192.0.2.1", 9)

_UNREACHABLE_ERRNOS = {
    getattr(errno, "ENETUNREACH", 101),
    getattr(errno, "EHOSTUNREACH", 113),
    getattr(errno, "ENETDOWN", 100),
    10050,  # WSAENETDOWN
    10051,  # WSAENETUNREACH
    10065,  # WSAEHOSTUNREACH
}
_REFUSED_ERRNOS = {getattr(errno, "ECONNREFUSED", 111), 10061}
_RESET_ERRNOS = {
    getattr(errno, "ECONNRESET", 104),
    getattr(errno, "ECONNABORTED", 103),
    getattr(errno, "EPIPE", 32),
    10053,  # WSAECONNABORTED
    10054,  # WSAECONNRESET
}
_DNS_WORDS = (
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "getaddrinfo failed",
    "no address associated",
    "name resolution",
    "failed to resolve",
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_enabled() -> bool:
    return os.environ.get("OLLABRIDGE_NETWORK_CHECK", "on").strip().lower() not in (
        "0",
        "off",
        "false",
        "no",
        "disabled",
    )


def _fmt_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min {int(seconds % 60):02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


# ── classification ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TransportFault:
    """A failure below HTTP: the request did not get an answer at all.

    ``kind`` is one of ``dns``, ``unreachable``, ``connect_timeout``,
    ``refused``, ``connection_lost``, ``read_timeout``, ``tls`` or
    ``transport``. ``refused`` means a host answered (with a reset), so the
    network itself is up.
    """

    kind: str
    detail: str

    @property
    def suspects_network(self) -> bool:
        return self.kind != "refused"

    def describe(self, host: str | None = None) -> str:
        where = f" {host}" if host else ""
        if self.kind == "dns":
            return f"DNS lookup{' for' + where if host else ''} failed"
        if self.kind == "unreachable":
            return "the network is unreachable"
        if self.kind == "connect_timeout":
            return f"connecting to{where or ' the provider'} timed out"
        if self.kind == "refused":
            return f"{host or 'the provider'} refused the connection"
        if self.kind == "connection_lost":
            return "the connection dropped before the answer arrived"
        if self.kind == "read_timeout":
            return "no answer arrived before the timeout"
        if self.kind == "tls":
            return (
                "the TLS handshake failed; a Wi-Fi sign-in page (captive portal) "
                "or a proxy may be intercepting the connection"
            )
        return self.detail or "transport error"


def _chain(exc: BaseException) -> Iterable[BaseException]:
    """The exception, its causes and contexts, and the members of any exception
    group among them (anyio reports "All connection attempts failed" that way)."""
    seen: set[int] = set()
    stack = [exc]
    while stack:
        cur = stack.pop()
        if cur is None or id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur
        stack.extend(getattr(cur, "exceptions", None) or ())
        stack.append(cur.__cause__)  # type: ignore[arg-type]
        stack.append(cur.__context__)  # type: ignore[arg-type]


def classify(exc: BaseException) -> TransportFault | None:
    """The transport fault behind *exc*, or ``None`` when the upstream answered
    (an HTTP status, a bad payload) or the error is not about the network."""
    try:
        import httpx
    except Exception:  # pragma: no cover - httpx is a hard dependency
        httpx = None  # type: ignore[assignment]

    # The provider answered with an HTTP status (a 504 from its own proxy
    # included): that is the provider talking, not the network failing.
    if getattr(exc, "upstream_status", None) is not None:
        return None

    chain = list(_chain(exc))
    text = " | ".join(str(e) for e in chain).lower()

    def _is(*names: str) -> bool:
        if httpx is None:
            return False
        types = tuple(getattr(httpx, n) for n in names if hasattr(httpx, n))
        return any(isinstance(e, types) for e in chain) if types else False

    # Most specific first: an OS error inside tells what really happened.
    for e in chain:
        if isinstance(e, socket.gaierror):
            return TransportFault("dns", str(e))
        if isinstance(e, ssl.SSLError):
            return TransportFault("tls", str(e))
        if isinstance(e, ConnectionRefusedError) or getattr(e, "errno", None) in _REFUSED_ERRNOS:
            return TransportFault("refused", str(e))
        if getattr(e, "errno", None) in _UNREACHABLE_ERRNOS:
            return TransportFault("unreachable", str(e))
    if any(w in text for w in _DNS_WORDS):
        return TransportFault("dns", text[:200])
    if "network is unreachable" in text or "no route to host" in text:
        return TransportFault("unreachable", text[:200])
    if "connection refused" in text:
        return TransportFault("refused", text[:200])
    if "certificate verify failed" in text or "ssl:" in text:
        return TransportFault("tls", text[:200])
    if _is("ConnectTimeout", "PoolTimeout"):
        return TransportFault("connect_timeout", text[:200])
    if _is("ReadTimeout", "WriteTimeout"):
        return TransportFault("read_timeout", text[:200])
    if _is("ConnectError"):
        return TransportFault("transport", text[:200] or "connect error")
    if _is("ReadError", "WriteError", "RemoteProtocolError", "CloseError"):
        return TransportFault("connection_lost", text[:200])
    for e in chain:
        if isinstance(e, ConnectionResetError) or getattr(e, "errno", None) in _RESET_ERRNOS:
            return TransportFault("connection_lost", str(e))
    if _is("TimeoutException") or any(isinstance(e, (TimeoutError, asyncio.TimeoutError)) for e in chain):
        return TransportFault("read_timeout", text[:200])
    if _is("TransportError", "NetworkError") or any(isinstance(e, ConnectionError) for e in chain):
        # A connection-level error without more detail: the probe decides.
        return TransportFault("transport", text[:200])
    # An adapter's own timeout type (ProviderTimeout raised without a cause).
    if any("timeout" in type(e).__name__.lower() for e in chain):
        return TransportFault("read_timeout", text[:200])
    return None


# ── addresses ─────────────────────────────────────────────────────────────


def _host_port(url: str) -> tuple[str, int] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw if "://" in raw else f"//{raw}", scheme="http")
    host = parts.hostname
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        port = None
    return host, port or (443 if parts.scheme == "https" else 80)


def is_loopback(host: str) -> bool:
    h = (host or "").strip("[]").lower()
    if h in ("localhost", "localhost.localdomain", "host.docker.internal") or h.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def is_remote(url: str) -> bool:
    """Does *url* need the network (anything that is not this machine)?"""
    hp = _host_port(url)
    return bool(hp) and not is_loopback(hp[0])


def probe_target(url: str) -> tuple[str, int] | None:
    """Where a reachability probe for *url* should connect: the host itself, or
    the proxy that traffic to it goes through (as httpx does by default).
    ``None`` for a local address or something that is not a URL."""
    hp = _host_port(url)
    if hp is None or is_loopback(hp[0]):
        return None
    scheme = urlsplit(url if "://" in url else f"http://{url}").scheme or "http"
    try:
        proxies = urllib.request.getproxies()
        proxy = proxies.get(scheme) or proxies.get("all")
        if proxy and not urllib.request.proxy_bypass(hp[0]):
            via = _host_port(proxy)
            if via is not None:
                return via
    except Exception:  # noqa: BLE001 - proxy discovery is best-effort
        pass
    return hp


def local_address() -> str | None:
    """The address this machine would send off-host traffic from, or ``None``
    when it has no route at all. Sends no packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(_ROUTE_PROBE_ADDR)
            return s.getsockname()[0]
    except OSError:
        return None


def _describe_probe_error(host: str, port: int, exc: BaseException, timeout: float) -> str:
    if isinstance(exc, socket.gaierror):
        return f"DNS lookup for {host} failed"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"no answer from {host}:{port} within {timeout:g} s"
    if getattr(exc, "errno", None) in _UNREACHABLE_ERRNOS:
        return f"no route to {host} (network unreachable)"
    text = str(exc).strip()
    return f"cannot connect to {host}:{port} ({text or type(exc).__name__})"


# ── the monitor ───────────────────────────────────────────────────────────


class NetworkLost(Exception):
    """Raised by :meth:`NetworkMonitor.guard` when the link to a provider
    dropped while its answer was pending. ``kind`` is ``connection_lost``."""

    def __init__(self, reason: str, *, kind: str = "connection_lost") -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


Prober = Callable[[str, int, float], Awaitable[None]]


async def _tcp_probe(host: str, port: int, timeout: float) -> None:
    """Open and close a TCP connection; raise on failure."""
    _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
    except Exception:  # noqa: BLE001 - the connect already proved the path
        pass


class NetworkMonitor:
    """Online/offline state of this machine as remote providers see it."""

    def __init__(
        self,
        *,
        probe_timeout_s: float = 3.0,
        recheck_s: float = 2.0,
        backoff_s: tuple[float, ...] = (2.0, 4.0, 8.0, 15.0, 30.0),
        stall_after_s: float | None = None,
        stall_every_s: float = 5.0,
        enabled: bool | None = None,
        prober: Prober | None = None,
        address: Callable[[], str | None] = local_address,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        logger: logging.Logger = log,
    ) -> None:
        self.probe_timeout_s = probe_timeout_s
        self.recheck_s = recheck_s
        self.backoff_s = backoff_s or (5.0,)
        self.stall_after_s = (
            _env_float("OLLABRIDGE_STALL_CHECK_AFTER_S", 15.0) if stall_after_s is None else stall_after_s
        )
        self.stall_every_s = stall_every_s
        self._enabled = enabled
        self._prober: Prober = prober or _tcp_probe
        self._address = address
        self._clock = clock
        self._wall = wall
        self._sleep = sleep
        self._log = logger
        self._targets_fn: Callable[[], Iterable[str]] | None = None
        self.reset()

    # ── configuration ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return _env_enabled() if self._enabled is None else self._enabled

    def set_targets(self, fn: Callable[[], Iterable[str]] | None) -> None:
        """Where the configured remote providers live: a callable returning
        their base URLs, read at every check so a provider added later counts."""
        self._targets_fn = fn

    def targets(self) -> list[tuple[str, int]]:
        override = os.environ.get("OLLABRIDGE_NETWORK_PROBE_TARGETS", "").strip()
        urls: list[str] = [u.strip() for u in override.split(",") if u.strip()] if override else []
        if not urls and self._targets_fn is not None:
            try:
                urls = [u for u in self._targets_fn() if u]
            except Exception as exc:  # noqa: BLE001 - never break a request over this
                self._log.debug("network: could not list probe targets: %s", exc)
                urls = []
        out: list[tuple[str, int]] = []
        for url in urls:
            target = probe_target(url) if not override else _host_port(url)
            if target and target not in out:
                out.append(target)
        return out[:MAX_PROBE_TARGETS]

    def reset(self) -> None:
        """Forget everything (tests; a restart of the event loop)."""
        self.state = UNKNOWN
        self.reason: str | None = None
        self.since: float | None = None
        self.since_wall: float | None = None
        self.last_check: float | None = None
        self.last_check_wall: float | None = None
        self.next_check: float | None = None
        self.failed_fast = 0
        self.outages = 0
        self._inflight: asyncio.Future[str] | None = None
        self._recovery: asyncio.Task[None] | None = None

    # ── probing ──────────────────────────────────────────────────────────

    async def probe(self, host: str, port: int) -> tuple[bool, str | None]:
        """Can this machine reach *host:port*? ``(True, None)`` when something
        answered, a refusal included; ``(False, reason)`` otherwise."""
        try:
            await self._prober(host, port, self.probe_timeout_s)
            return True, None
        except (ConnectionRefusedError, ConnectionResetError):
            return True, None  # a host answered: the network is up
        except Exception as exc:  # noqa: BLE001 - any other failure is "no"
            if getattr(exc, "errno", None) in _REFUSED_ERRNOS | _RESET_ERRNOS:
                return True, None
            return False, _describe_probe_error(host, port, exc, self.probe_timeout_s)

    async def check(self, *, max_age: float | None = None, reason: str | None = None) -> str:
        """Probe the configured remote providers and update the state.

        A check younger than *max_age* (default ``recheck_s``) is reused, and
        concurrent callers share one probe round."""
        if not self.enabled:
            return UNKNOWN
        age_limit = self.recheck_s if max_age is None else max_age
        now = self._clock()
        if self.last_check is not None and now - self.last_check < age_limit:
            return self.state
        loop = asyncio.get_running_loop()
        inflight = self._inflight
        if inflight is not None and not inflight.done() and inflight.get_loop() is loop:
            return await asyncio.shield(inflight)
        self._inflight = loop.create_task(self._run_check(reason))
        return await asyncio.shield(self._inflight)

    async def _run_check(self, reason: str | None) -> str:
        targets = self.targets()
        if not targets:
            # Nothing remote is configured: there is nothing to be offline from.
            self.last_check = self._clock()
            self.last_check_wall = self._wall()
            return self.state
        results = await asyncio.gather(*(self.probe(h, p) for h, p in targets))
        self.last_check = self._clock()
        self.last_check_wall = self._wall()
        if any(ok for ok, _ in results):
            self._mark_online()
        else:
            errors = [err for _, err in results if err]
            detail = errors[0] if errors else "no remote provider answered"
            if len(targets) > 1:
                detail += f"; none of the {len(targets)} configured remote providers answered"
            if self._address() is None:
                detail = "this machine has no network route (not connected to any network)"
            self._mark_offline(detail if not reason else f"{reason}: {detail}")
        return self.state

    # ── transitions ──────────────────────────────────────────────────────

    def _mark_offline(self, reason: str) -> None:
        self.reason = reason
        if self.state != OFFLINE:
            self.state = OFFLINE
            self.since = self._clock()
            self.since_wall = self._wall()
            self.failed_fast = 0
            self.outages += 1
            self._log.warning(
                "Network connection lost: %s. Requests for remote models now fail fast "
                "with HTTP 503 (network_offline) instead of waiting for a timeout; local "
                "models keep working. Checking again every few seconds.",
                reason,
            )
        self._start_recovery()

    def _mark_online(self) -> None:
        if self.state == OFFLINE:
            self._log.info(
                "Network connection restored after %s (%d request(s) failed fast while offline).",
                _fmt_duration(self._clock() - (self.since or self._clock())),
                self.failed_fast,
            )
        elif self.state == UNKNOWN:
            self._log.debug("network: remote providers reachable")
        if self.state != ONLINE:
            self.since = self._clock()
            self.since_wall = self._wall()
        self.state = ONLINE
        self.reason = None
        self.next_check = None

    def _start_recovery(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = self._recovery
        if task is not None and not task.done() and task.get_loop() is loop:
            return
        self._recovery = loop.create_task(self._recover())

    async def _recover(self) -> None:
        step = 0
        try:
            while self.state == OFFLINE:
                delay = self.backoff_s[min(step, len(self.backoff_s) - 1)]
                step += 1
                self.next_check = self._clock() + delay
                await self._sleep(delay)
                await self.check(max_age=0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - a background loop must not die noisily
            self._log.debug("network: recovery probe failed: %s", exc)

    # ── request-path helpers ─────────────────────────────────────────────

    @property
    def offline(self) -> bool:
        return self.enabled and self.state == OFFLINE

    def note_failed_fast(self) -> None:
        self.failed_fast += 1

    def retry_after_s(self) -> int:
        """Seconds until the next background probe, for ``Retry-After``."""
        if self.next_check is None:
            return int(self.backoff_s[0])
        return max(1, min(30, round(self.next_check - self._clock())))

    async def guard(self, call: Callable[[], Awaitable[T]], *, url: str, label: str) -> T:
        """Run *call* (a request to *url*) under the stall watchdog.

        After ``stall_after_s`` without an answer the provider's address is
        probed every ``stall_every_s``. Two misses in a row, or a change of this
        machine's network address, cancel the request with :class:`NetworkLost`.
        An error from *call* gets ``network_reachable`` set to what the probes
        saw (``True``, ``False`` or ``None`` when none ran), so a timeout can say
        whether the network or the provider was the slow part."""
        target = probe_target(url)
        if not self.enabled or target is None or self.stall_after_s <= 0:
            return await call()
        host, port = target
        start_addr = self._address()
        task: asyncio.Future[T] = asyncio.ensure_future(call())
        reachable: bool | None = None
        misses = 0
        try:
            done, _ = await asyncio.wait({task}, timeout=self.stall_after_s)
            while not done:
                addr = self._address()
                if start_addr and addr and addr != start_addr:
                    raise NetworkLost(
                        f"this machine's network changed ({start_addr} → {addr}) while "
                        f"{label} was answering, so the open connection is gone"
                    )
                ok, err = await self.probe(host, port)
                if task.done():
                    break
                if ok:
                    reachable, misses = True, 0
                else:
                    reachable, misses = False, misses + 1
                    if misses >= 2:
                        # Update the shared state too, so the next request fails fast.
                        await self.check(max_age=0)
                        raise NetworkLost(f"lost the connection to {label} while waiting for its answer ({err})")
                done, _ = await asyncio.wait({task}, timeout=self.stall_every_s)
            return task.result()
        except NetworkLost:
            raise
        except Exception as exc:
            try:
                exc.network_reachable = reachable  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - some exception types refuse attributes
                pass
            raise
        finally:
            if not task.done():
                task.cancel()

    # ── reading ──────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """JSON-friendly state for ``/health`` and the dashboard."""

        def _iso(ts: float | None) -> str | None:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts is not None else None

        out: dict[str, Any] = {
            "enabled": self.enabled,
            "state": self.state if self.enabled else UNKNOWN,
            "since": _iso(self.since_wall),
            "reason": self.reason,
            "last_check": _iso(self.last_check_wall),
            "failed_fast": self.failed_fast,
            "outages": self.outages,
        }
        if self.state == OFFLINE:
            out["retry_after_s"] = self.retry_after_s()
        return out


#: The process-wide monitor. The provider router reports to it and reads it;
#: ``/health`` shows its snapshot.
NETWORK = NetworkMonitor()
