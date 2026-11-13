# Configuration & Authentication

Environment variables, API keys, auth modes, and enrollment tokens for the local gateway.
Moved from the README; see also `docs/SECURITY.md` and `docs/DEPLOYMENT_HARDENING.md`.

---

## 🔐 Security & Configuration

### Authentication

OllaBridge auto-generates a secure API key on first run (saved in `.env`):

```env
API_KEYS=sk-ollabridge-xY9kL2mN8pQ4rT6vW1zA
```

Use it in your apps:

```python
# Option 1: Bearer token
headers = {"Authorization": "Bearer sk-ollabridge-..."}

# Option 2: Custom header
headers = {"X-API-Key": "sk-ollabridge-..."}
```

### Configuration (`.env`)

```env
# API Keys (comma-separated for multiple)
API_KEYS=sk-ollabridge-abc123,sk-ollabridge-def456

# Server
HOST=0.0.0.0
PORT=11435

# Default models
DEFAULT_MODEL=deepseek-r1
DEFAULT_EMBED_MODEL=nomic-embed-text

# Inbound rate limit: the starting value for Settings → Rate limits.
# The limit itself is off until you turn it on there (see "Rate limits").
RATE_LIMIT=60/minute

# Security
ENROLLMENT_SECRET=your-secret-here
ENROLLMENT_TTL_SECONDS=3600

# Database (optional)
DATABASE_URL=postgresql://user:pass@localhost/ollabridge

# Logging (optional; see "Logging" below)
OLLABRIDGE_LOG_LEVEL=info
OLLABRIDGE_LOG_FORMAT=auto
```

### Logging

Every line the gateway writes (its own, uvicorn's and libraries') goes to
stderr in one format. Each setting is read from the CLI flag first, then the
environment, then `.env`, then the default.

| Variable | CLI flag | Default | Values |
|---|---|---|---|
| `OLLABRIDGE_LOG_LEVEL` | `--log-level` | `info` | `debug` `info` `warning` `error`. `LOG_LEVEL` is still read as a deprecated alias. |
| `OLLABRIDGE_LOG_LEVELS` | `--log-level component=level` (repeatable) | none | Per component or logger: `catalog=debug,server=info,httpx=warning` |
| `OLLABRIDGE_LOG_FORMAT` | `--log-format` | `auto` | `auto` is `pretty` on a colour terminal and `plain` otherwise. `json` writes one object per line. |
| `OLLABRIDGE_LOG_UTC` | none | off | `1` shows UTC on the console. JSON is always UTC. |
| `NO_COLOR` / `FORCE_COLOR` | none | none | Standard colour overrides |

Components you can name in a rule: `gateway`, `http`, `server`, `providers`,
`router`, `network`, `secrets`, `hfcatalog`, `catalog`, `runtime`, `cloud`,
`relay`, `node`, `sources`, `models`, `pairing`, `consumers`, `session`,
`media`, `traces`, `store`, `avatar`, `mcp`. Any other key is a logger-name
prefix.

### Network loss

When this machine loses its connection (a tunnel, a train, a Wi-Fi switch, a
VPN drop), requests for remote models answer within seconds with HTTP 503
`network_offline` or `connection_lost` and a `Retry-After`, instead of a
120 s `provider_timeout`; local models keep working, the dashboard shows
"No network", and the gateway recovers by itself. Design and details:
[NETWORK_RESILIENCE.md](NETWORK_RESILIENCE.md).

| Variable | Default | Values |
|---|---|---|
| `OLLABRIDGE_NETWORK_CHECK` | `on` | `off` disables probes, fail-fast and the stall watchdog |
| `OLLABRIDGE_NETWORK_PROBE_TARGETS` | the configured remote providers | `host:port,host:port` to probe instead (e.g. a proxy) |
| `OLLABRIDGE_CONNECT_TIMEOUT_S` | `10` | Seconds to open a connection to a provider |
| `OLLABRIDGE_STALL_CHECK_AFTER_S` | `15` | Seconds before an unanswered request is checked; `0` disables |

The default level shows real work, problems and changes, and stays quiet
otherwise:

- **One line per request that does something:** chat completions,
  embeddings and settings changes, with the model, the route that served it,
  tokens and time.
- **Every server error (5xx).**
- **The first client error (4xx) per client,** with the reason (for example
  "no API key sent"). Repeats from the same client are counted and reported
  again every 10 minutes while they continue.
- **State changes:** startup, the local model catalog gaining or losing
  models, runtimes going down or recovering, shutdown.

Successful reads (health checks, model-list refreshes, dashboard polls), the
provider router's per-attempt detail and unchanged catalog syncs are DEBUG.
Run `ollabridge start -v` (or `make start VERBOSE=1`) to see everything, or
open one component, for example `--log-level http=debug` for every request.

```text
── OllaBridge 0.1.9 · gateway · 2026-10-29 · pid 35191 · level info · format pretty ──────
08:36:33.412  INFO   gateway    Starting gateway  bind=0.0.0.0:11435 auth=local-trust model=deepseek-r1 workers=1
08:36:33.580  INFO   gateway    Ready in 0.9s  url=http://localhost:11435 bind=0.0.0.0:11435
11:24:20.090  WARN   http       GET /v1/models 401 0.00s: no API key sent (local-trust exempts loopback clients only); repeats from this client are counted and summarised every 10m  client=172.19.0.14
11:29:24.715  INFO   http       POST /v1/chat/completions 200 2.63s  req=40c4fb35 model=openwebui/qwen3-32b route=openwebui tokens=42 client=172.19.0.14
```

For containers and log shippers, set `OLLABRIDGE_LOG_FORMAT=json`. Each line
then carries `ts`, `level`, `component`, `logger`, `msg`, `pid`, `version`,
any fields, and `request_id` for lines written while a request runs. Credential
shapes are scrubbed from every line in every format. The full design is in
[LOGGING_DESIGN.md](LOGGING_DESIGN.md).

### Rate limits

**Dashboard → Settings → Rate limits** (`http://localhost:11435/ui`). Changes
apply at once, without a restart, and are saved in `runtime_settings.json` in
the data directory, beside the dashboard's other settings. The defaults change
nothing: the inbound limit is off, and a provider left at the defaults is not
paced and answers a rate limit with a 429 at once, as before.

**OllaBridge's own limit (inbound).** Turn on *Limit incoming model calls* and
set *Requests per minute*. It counts model calls (`POST /v1/...`) in a sliding
60-second window per client address, and per API key when the client sends
one; the dashboard and reads such as `GET /v1/models` are never counted. Past
the limit a call gets HTTP 429 with `Retry-After`, `X-RateLimit-Limit` and
`X-RateLimit-Remaining: 0`. `RATE_LIMIT` only sets the starting value shown in
the dashboard.

**Per provider (outbound).** Some providers enforce a per-user limit whose
numbers are not published and that lasts minutes once tripped (an Open WebUI
server answers it with HTTP 400 `{"detail": "Rate limit exceeded. Please try
again later."}`). A heavy agent run trips it and fails. Set limits for that
provider and its calls wait their turn inside OllaBridge instead:

| Setting | Meaning |
|---|---|
| Requests / minute | Calls start evenly spaced, at most one every 60/N seconds. `0` = no pacing. |
| Max concurrent | At most this many calls to the provider at once. `0` = no cap. |
| On a rate limit | **Fail fast**: answer the client with a 429 at once. **Wait and retry**: wait and try again, first after the cooldown (or 5 s when it is 0), then doubling; a longer `Retry-After` from the provider wins. Other calls to that provider wait meanwhile. |
| Max wait (s) | The longest one call waits inside OllaBridge (queue, pacing, cooldown and retries together) before it is answered with a 429. Your client's own timeout must be longer than this plus the model's answer time. |
| Cooldown (s) | After a rate-limit answer the provider is left alone this long. In fail-fast mode, calls meanwhile get a 429 without reaching the provider. `0` = none. |

The provider list shows every provider that is limited, in use, or was just
rate limited; add any other from *Add a provider…*. Each card shows calls
running and waiting, *cooling down until …*, and the recent rate-limited
answers with what OllaBridge did about each. *Use suggested* fills in a
cautious starting point for a provider whose limit you do not know:
12 requests/minute, 2 at a time, wait and retry, max wait 180 s, cooldown
60 s. Lower the rate if it still trips, raise it if calls wait too long.

A 429 that OllaBridge hands back always carries `Retry-After`: the provider's
own value, the remaining cooldown, or 5 seconds when neither is known.

The same settings over the API (`GET`/`PUT /admin/rate-limits`, admin auth):

```bash
curl -s -X PUT http://127.0.0.1:11435/admin/rate-limits \
  -H 'Content-Type: application/json' \
  -d '{"inbound": {"enabled": false, "requests_per_minute": 60},
       "providers": {"openwebui": {"requests_per_minute": 12, "max_concurrent": 2,
                                   "on_rate_limit": "wait_retry",
                                   "max_wait_seconds": 180, "cooldown_seconds": 60}}}'
```

Provider ids are the ones the dashboard lists (`openwebui` for an Open WebUI
source, `byok-<name>` for a BYOK source, `groq-free` and the like for the
built-in catalog). A `PUT` replaces the whole object; an unknown field or an
out-of-range value is refused with HTTP 422.

### Enrollment Tokens

Create short-lived tokens for nodes to join:

```bash
ollabridge enroll-create --ttl 3600
```

Tokens expire automatically for security.

---

