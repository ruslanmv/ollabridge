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

# Rate limiting
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
`router`, `secrets`, `hfcatalog`, `catalog`, `runtime`, `cloud`, `relay`,
`node`, `sources`, `models`, `pairing`, `consumers`, `session`, `media`,
`traces`, `store`, `avatar`, `mcp`. Any other key is a logger-name prefix.

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
11:29:24.715  INFO   http       POST /v1/chat/completions 200 2.63s  req=40c4fb35 model=openwebui/internal-qwen3-8-27b route=openwebui tokens=42 client=172.19.0.14
```

For containers and log shippers, set `OLLABRIDGE_LOG_FORMAT=json`. Each line
then carries `ts`, `level`, `component`, `logger`, `msg`, `pid`, `version`,
any fields, and `request_id` for lines written while a request runs. Credential
shapes are scrubbed from every line in every format. The full design is in
[LOGGING_DESIGN.md](LOGGING_DESIGN.md).

### Enrollment Tokens

Create short-lived tokens for nodes to join:

```bash
ollabridge enroll-create --ttl 3600
```

Tokens expire automatically for security.

---

