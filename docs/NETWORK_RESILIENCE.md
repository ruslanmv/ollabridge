# OllaBridge — Working Through Network Loss

## Problem

A laptop running OllaBridge goes where its user goes: into a metro tunnel, onto
a train, from office Wi-Fi to a phone hotspot, through a VPN reconnect. Each
of these drops the network for seconds to minutes. Before this change the
gateway could not tell that apart from a slow provider:

```text
11:54:03.776  WARN   router   Provider openwebui failed (120225ms): chat timeout:  — trying next candidate
11:54:03.778  WARN   gateway  Provider failure for model=openwebui/<model> reported to the client as HTTP 504 (provider_timeout) …
11:54:03.796  ERROR  http     POST /v1/chat/completions 504 120.3s … route=ollama/local … error=HTTPException
11:54:21.837  INFO   http     POST /v1/chat/completions 200 50.3s … route=openwebui
11:56:04.412  ERROR  http     POST /v1/chat/completions 504 120.2s … route=ollama/local … error=HTTPException
```

Four things were wrong:

1. **Every request waited the full 120 s** read timeout, even when no
   connection could be opened at all. There was a single timeout for
   "connect" and "generate".
2. **The answer was `provider_timeout`**, the same as for an overloaded model.
   The user (and an agent's retry logic) could not know the network was the
   cause.
3. **Each new request while offline waited 120 s again.** Nothing remembered
   that the network was down.
4. **The log was misleading:** `route=ollama/local` on a request that never
   touched local Ollama, `chat timeout: ` with an empty reason, and
   `error=HTTPException` instead of what went wrong. Network failures were
   also counted against the provider's health score.

## Goals

- Say **"you are offline"** when that is the cause, and say it within seconds.
- Keep a slow but reachable provider working: a 60 s generation is not an outage.
- Stop paying a timeout per request while offline; recover by itself, quickly.
- One log line per outage, one per recovery; the dashboard shows the state.
- Never contact a host the user has not configured.

## How the industry does it

| Practice | Where it comes from | Used here as |
|---|---|---|
| Passive failure signal + **active validation probe** | Android `ConnectivityManager`, iOS `NWPathMonitor`, Windows NCSI | A transport error triggers a TCP probe of the configured providers |
| **Separate connect and request timeouts** | Envoy, gRPC, every HTTP client guide | 10 s connect, 120 s answer |
| **Circuit breaker** (open → fail fast, half-open probe, close) | Hystrix, resilience4j, service meshes | Offline → 503 at once; background probe with backoff closes it |
| **Distinct status for "unreachable"** | gRPC `UNAVAILABLE` vs `DEADLINE_EXCEEDED`; OpenAI SDK `APIConnectionError` | `503 network_offline` / `connection_lost` vs `504 provider_timeout` |
| **`Retry-After`** on 503 | RFC 9110 | Seconds until the next probe; OpenAI SDKs honour it |
| **Path-change detection** | iOS/Android cancel and retry when the network interface changes | Local source address change aborts a pending request |
| **Offline banner** that clears itself | Gmail, Slack, Teams | Dashboard strip + "No network" pill |

OS-level connectivity checks call a vendor beacon (`generate_204`,
`msftconnecttest`). OllaBridge does not: it probes only the providers already
configured here, or the proxy their traffic goes through. Privacy and
air-gapped / intranet-only setups are unaffected.

## Design

All of it lives in `src/ollabridge/core/connectivity.py`; the provider router
(`addons/providers/router.py`) is its only caller on the request path.

### 1. Classify the failure

`classify(exc)` walks the exception, its causes and any exception group and
returns a `TransportFault`, or `None` when the provider answered with an HTTP
status (that is the provider talking, not the network failing):

| Kind | Typical cause | Suspects the network? |
|---|---|---|
| `dns` | `getaddrinfo failed`, "Temporary failure in name resolution" | yes |
| `unreachable` | `ENETUNREACH`, `EHOSTUNREACH` | yes |
| `connect_timeout` | TCP SYN unanswered | yes |
| `connection_lost` | reset, "Server disconnected without sending a response" | yes |
| `read_timeout` | no answer before the timeout | yes, the probe decides |
| `tls` | certificate mismatch: often a Wi-Fi sign-in page (captive portal) | yes |
| `refused` | host answered with RST | **no**: something answered, the network is up |

### 2. Validate with a probe

A fault that suspects the network calls `NETWORK.check()`: a TCP connect
(3 s limit) to up to four configured remote providers, concurrently. Loopback
providers are never probed. Keyless or disabled providers are left out.

- **Any probe answers** → `online`. The failing provider has its own problem;
  its error is reported as before, and the log adds "the network itself is up".
- **None answers** → `offline`, with the first probe's reason
  ("DNS lookup for chat.example failed"), or "this machine has no network
  route" when the OS has no route at all.

Concurrent callers share one probe round; a result younger than 2 s is reused.
If `HTTPS_PROXY` (or the system proxy) applies to a provider, the proxy is
probed instead of the provider, the same path httpx takes.

### 3. Circuit breaker

While `offline`:

- A request for a **remote** provider re-checks first if the last probe is
  older than 2 s, so the first request after the tunnel goes through. If
  still offline it is refused at once: no connection attempt, no timeout.
- A **local** provider (loopback URL) and local Ollama keep serving.
- A background task probes with backoff 2 → 4 → 8 → 15 → 30 s and closes the
  circuit as soon as one probe answers.
- Failures during the outage are **not** recorded against the provider's
  health, so it is not ranked down when the network returns.

### 4. Stall watchdog for requests in flight

A connection that dies mid-request (the train enters the tunnel after the
request left) gives no error: TCP waits. The router runs each remote call
under `NETWORK.guard()`:

- After **15 s** without an answer, probe the provider's host every 5 s.
- **Two misses in a row** → cancel the request: `connection_lost` (about
  25 s instead of 120 s), and the shared state goes `offline`.
- **This machine's source address changed** (Wi-Fi → hotspot) → cancel at
  once: the open connection's address no longer exists.
- **Probes keep answering** → keep waiting. If the 120 s timeout still fires,
  the error says the server stayed reachable, so the model is slow, not the
  network.

The source address comes from `connect()` on a UDP socket to an RFC 5737
documentation address, which sends no packet.

### 5. Timeouts

Adapters use `BaseProviderAdapter.http_timeout()`: the provider's own timeout
for the answer, **10 s to open the connection**
(`OLLABRIDGE_CONNECT_TIMEOUT_S`). A dead network now fails in at most 10 s
even before the watchdog. The Open WebUI adapter's timeout text names the
phase and limit (`chat timeout while waiting for the answer (limit 120 s)`).

### 6. What the client sees

```http
HTTP/1.1 503 Service Unavailable
Retry-After: 4
X-OllaBridge-Network: offline

{"detail": {"error": {
  "type": "api_connection_error",
  "code": "network_offline",
  "message": "OllaBridge is offline, so openwebui/<model> could not be reached (DNS lookup for chat.example failed). This happens when the network drops: a tunnel, a train, a Wi-Fi switch, a VPN disconnect. Local models still work; retry once the connection is back."
}}}
```

| Code | Status | Meaning | Retry? |
|---|---|---|---|
| `network_offline` | 503 | This machine cannot reach any configured provider | After `Retry-After` |
| `connection_lost` | 503 (`X-OllaBridge-Network: lost`) | The link dropped while the answer was pending | Yes, safe |
| `provider_timeout` | 504 | The provider was reachable but did not answer in time | Client's choice |
| `provider_unavailable` | 502 | The provider answered with an error, or is down while the network is up | Client's choice |

OpenAI-compatible SDKs retry 503 with `Retry-After` on their own, so an agent
resumes by itself once the network is back.

### 7. Observability

Console, at the default level:

```text
11:52:31.120  WARN   network  Network connection lost: DNS lookup for chat.example failed. Requests for remote models now fail fast with HTTP 503 (network_offline) instead of waiting for a timeout; local models keep working. Checking again every few seconds.
11:52:31.140  WARN   http     POST /v1/chat/completions 503 0.02s: network offline; repeats from this client are counted and summarised every 10m  req=… model=openwebui/<model> route=openwebui error=network_offline
11:55:43.402  INFO   network  Network connection restored after 3 min 12 s (14 request(s) failed fast while offline).
```

- The access line names the provider that was tried (`route=openwebui`) and
  the error code (`error=network_offline`), and repeated offline refusals are
  summarised like client errors instead of one ERROR each.
- `GET /health` has a `network` block: `state` (`online` / `offline` /
  `unknown`), `since`, `reason`, `last_check`, `failed_fast`, `outages`,
  `retry_after_s`. Monitoring can alert on it.
- The dashboard shows a **No network** pill in the header and a strip under
  it with the cause and the next check; it polls every 3 s while offline and
  shows "Back online" for a few seconds after recovery.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `OLLABRIDGE_NETWORK_CHECK` | `on` | `off` restores the old behaviour (no probes, no fail-fast, no watchdog). |
| `OLLABRIDGE_NETWORK_PROBE_TARGETS` | configured providers | Comma-separated `host:port` list to probe instead, e.g. a corporate proxy. |
| `OLLABRIDGE_CONNECT_TIMEOUT_S` | `10` | Limit for opening a connection to a provider. |
| `OLLABRIDGE_STALL_CHECK_AFTER_S` | `15` | When the watchdog starts probing an unanswered request; `0` disables it. |

## Not in this change

- **Offline fallback to a local model.** Answering `openwebui/<model>` with a
  local model while offline would change what the client gets without
  asking. A later, opt-in setting (`offline_fallback_model`) with a response
  header naming the substitute is the safe form.
- **A `doctor` check** that runs the same probe on demand.
- **Captive-portal sign-in detection** beyond the TLS hint: telling a sign-in
  page apart needs an HTTP probe with a known answer, which in turn needs a
  host the user chooses.

## Tests

`tests/test_connectivity.py` covers classification, the probe decision, the
circuit breaker and its recovery, the watchdog (dead link, network switch,
slow but reachable), the router (fail fast, local still served, health not
penalised, the access-line route) and the API contract (503, `Retry-After`,
`/health`). The probe is a fake; no test touches the network, and the
process-wide monitor is off for the suite (`tests/conftest.py`).
