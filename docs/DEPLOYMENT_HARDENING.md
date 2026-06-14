# Deployment Hardening

How to run OllaBridge safely beyond a single developer laptop. The gateway
itself serves **plain HTTP** and binds `0.0.0.0` by default — every section
below assumes you want to tighten that.

Quick verification after any change:

```bash
ollabridge doctor security
ollabridge doctor --json     # machine-readable, suitable for cron/CI
```

---

## TLS via reverse proxy

OllaBridge has no built-in TLS. For any non-loopback access, bind the
gateway to localhost and terminate TLS in front of it.

### Caddy (automatic certificates)

```caddyfile
llm.example.com {
    reverse_proxy 127.0.0.1:11435
}
```

Run the gateway with `HOST=127.0.0.1` so only Caddy can reach it.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name llm.example.com;

    ssl_certificate     /etc/letsencrypt/live/llm.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llm.example.com/privkey.pem;

    client_max_body_size 10m;          # OllaBridge has no body-size limit of its own

    location / {
        proxy_pass http://127.0.0.1:11435;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;           # required for streaming responses
        proxy_read_timeout 300s;       # long generations
    }
}
```

Note: the rate limiter keys on the remote address; behind a proxy all
requests share the proxy's address unless you account for forwarded headers.
Prefer enforcing per-client rate limits at the proxy as well.

The cloud relay needs **no inbound TLS or ports** — it is a single outbound
WSS connection from the gateway to OllaBridge Cloud.

## Firewall guidance

- Keep `HOST=127.0.0.1` and expose only the proxy's 443.
- If you must bind `0.0.0.0` (e.g. LAN use without a proxy), restrict the
  port at the firewall:

```bash
# ufw: allow gateway port from one subnet only
ufw allow from 192.168.1.0/24 to any port 11435 proto tcp
ufw deny 11435/tcp
```

- Do not expose Ollama (`11434`) at all — OllaBridge talks to it over
  localhost; Ollama has no authentication.
- Outbound: the gateway needs egress to Ollama (local), any configured
  provider APIs (HTTPS), and OllaBridge Cloud (WSS) if you use the relay.

## Docker hardening

The shipped `Dockerfile` is minimal (`python:3.11-slim`, runs as root,
listens on 11343 with `--host 0.0.0.0`, which is normal inside a
container). Harden the deployment around it:

```yaml
services:
  ollabridge:
    image: ollabridge:0.1.2          # pin a specific tag/digest, never :latest
    user: "10001:10001"              # non-root
    read_only: true                  # read-only root filesystem
    tmpfs:
      - /tmp
    volumes:
      - ollabridge-data:/home/app/.ollabridge   # persistent state only
    environment:
      - AUTH_MODE=required
      - API_KEYS=${API_KEYS}         # injected, not baked into the image
      - OLLA_SECRET=${OLLA_SECRET}
      - CORS_ORIGINS=https://your-app.example.com
    ports:
      - "127.0.0.1:11435:11343"      # publish to loopback only; proxy fronts it
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
```

Rules of thumb:

- **Never mount the Docker socket** (`/var/run/docker.sock`) into the
  container — there is no feature that needs it.
- Pin the image by tag or digest; rebuild for base-image security updates.
- Pass secrets via environment/secret store, never `COPY` a `.env` into
  the image.
- Set `OLLABRIDGE_HOME` (or mount the default home) to a volume so
  `secrets.enc` and `cloud_device.json` survive restarts — and protect that
  volume like the secrets it contains.

## Environment variables reference

| Variable | Default | Hardened recommendation |
|---|---|---|
| `API_KEYS` | `dev-key-change-me` (placeholder; `ollabridge start` generates a real `sk-ollabridge-*` key) | Set explicit, random keys; comma-separated for multiple clients |
| `AUTH_MODE` | `required` | Keep `required`; use `local-trust`/`pairing` only on single-user machines (loopback bypasses auth in those modes) |
| `HOST` | `0.0.0.0` | `127.0.0.1` behind a TLS proxy |
| `PORT` | `11435` | As needed |
| `CORS_ORIGINS` | localhost dev origins (`5173,3000,8080`) | Explicit production origins. **Never empty** — empty becomes wildcard `*` with credentials |
| `RATE_LIMIT` | `60/minute` (slowapi syntax, per remote address) | Tune per deployment, e.g. `120/minute` |
| `OLLA_SECRET` | unset (plaintext secret fallback, `0o600`) | **Always set** — long random string; enables Fernet encryption of `secrets.enc`. Rotating it invalidates stored provider keys |
| `ENROLLMENT_SECRET` | `dev-enroll-change-me` | Set a real secret if you use multi-node enrollment |
| `OLLABRIDGE_CLOUD_URL` | unset | Point `ollabridge login` at your cloud instance (or use `--cloud`) |
| `OLLABRIDGE_HOME` | `~/.ollabridge` | Relocate state (e.g. to a dedicated volume); all `0o600` handling follows it |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Keep Ollama loopback-only |

Settings load from the environment and an optional `.env` file
(`src/ollabridge/core/settings.py`).

## Rate limits

Rate limiting uses `slowapi` with `get_remote_address` as the key and
`RATE_LIMIT` as the default limit for all routes. It is in-process (no
shared store), so limits apply per gateway instance. For multi-instance or
proxied deployments, add limits at the proxy (nginx `limit_req`, Caddy
`rate_limit` plugin).

## API key rotation

`API_KEYS` accepts a comma-separated list, which makes zero-downtime
rotation straightforward:

1. Add the new key alongside the old: `API_KEYS=sk-ollabridge-new,sk-ollabridge-old`.
2. Restart the gateway; migrate clients to the new key.
3. Remove the old key and restart again.

Provider keys: rotate with `ollabridge providers rotate <provider>` (stores
the new key in `secrets.enc`). Cloud device token: `ollabridge logout` +
revoke in the cloud dashboard, then `ollabridge login` again. Pairing
tokens (`AUTH_MODE=pairing`) are revocable per device via `/pair/revoke`.

## CORS

- Defaults allow localhost dev origins only.
- Set `CORS_ORIGINS` to a comma-separated list of exact production origins.
- An **empty** value becomes `allow_origins=["*"]` with credentials allowed
  — `ollabridge doctor security` reports this as a failure.

## Logging

- **No prompts by default.** Neither the request log
  (`~/.ollabridge/ollabridge.sqlite`) nor the trace store
  (`~/.ollabridge/traces.db`) has columns for prompt/response content.
  Prompt logging is an explicit opt-in flag in `sync.yaml`, default `false`.
- **Redaction filter.** `ollabridge.core.redact.install_redaction_filter()`
  attaches a `logging.Filter` that scrubs credential shapes
  (`sk-*`, `dvt_*`, `mtx_*`, `hf_*`, `Bearer …`, …) from log records.
  CLI/doctor output shows keys only as 4-character hints.
- If you ship gateway logs to a central system, treat them as low-sensitivity
  metadata, but keep the redaction filter installed as defense in depth —
  upstream error bodies pass through `redact_text` but may still contain
  non-credential internals.

## Monitoring

- **Liveness:** `GET /health` (no auth required) — wire it into your proxy
  health checks, Docker `HEALTHCHECK`, or uptime monitoring.
- **Posture:** run the doctor suite on a schedule and alert on failures:

```bash
# cron / CI example
ollabridge doctor --json > /var/log/ollabridge-doctor.json || alert
ollabridge doctor security --json | jq '.results[] | select(.status=="fail")'
```

  Sections: `local`, `cloud`, `relay`, `providers`, `security`, `e2e`.
  `doctor relay` verifies the WSS handshake, token validity (detects
  revoked/expired tokens), and reconnection; `doctor e2e` sends one fixed,
  non-sensitive test prompt.
- **Relay state:** `/admin/cloud/status` exposes connection state, models
  shared, uptime, and reconnect attempts.
- **Traces:** `ollabridge traces list` for recent request metadata
  (model, provider, latency, cloud_relay flag, error category).

## Backups

Back up `~/.ollabridge` (or `$OLLABRIDGE_HOME`), with caveats:

| File | Back up? | Caveat |
|---|---|---|
| `sync.yaml`, `policies.yaml`, `providers.yaml`, `config.yaml` | Yes | Plain config, no secrets by design |
| `secrets.enc` | Yes, if encrypted | Useless without the same `OLLA_SECRET` (HKDF-derived key — restoring on another machine with the same secret works). **If `OLLA_SECRET` was unset, this file is plaintext keys — treat the backup accordingly or exclude it.** |
| `cloud_device.json` | Prefer **not** to | Contains the raw device token. Easier to re-pair (`ollabridge login`) on restore; revoke the old device in the dashboard if a backup leaks |
| `pair_tokens.json` | Optional | Hashes only; re-pairing devices is cheap |
| `traces.db`, `ollabridge.sqlite`, `audit.log` | Optional | Metadata only; recreated automatically if absent |

After restoring, re-tighten permissions and verify:

```bash
chmod 600 ~/.ollabridge/*
ollabridge doctor security
```

## Not yet available (roadmap)

For clarity, these are **not** shipped features — do not assume them:

- Built-in TLS on the local API (use a reverse proxy).
- Request body size limits in the gateway (enforce at the proxy).
- Scoped/role-based local API keys (single shared key class today).
- OS keychain storage for the cloud device token (plaintext `0o600` today).
- Distributed rate limiting (in-process per instance today).
