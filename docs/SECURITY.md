# Security Policy

OllaBridge is a local-first, OpenAI-compatible gateway in front of Ollama
(and optional hosted providers), with an optional outbound relay to
OllaBridge Cloud. This document describes how to report vulnerabilities,
how OllaBridge handles secrets, and how to deploy it securely.

Related documents:

- [PRIVACY.md](PRIVACY.md) — what data stays local vs. what syncs
- [THREAT_MODEL.md](THREAT_MODEL.md) — assets, trust boundaries, attacker profiles
- [DEPLOYMENT_HARDENING.md](DEPLOYMENT_HARDENING.md) — TLS, Docker, env vars, monitoring

---

## Supported versions

OllaBridge is pre-1.0. Security fixes land on the current `0.x` line only.

| Version | Supported |
|---|---|
| Latest `0.x` release (currently `0.1.x`) | Yes |
| Older `0.x` releases | No — upgrade to the latest release |

There are no long-term support branches. Always run the most recent release.

## Reporting a vulnerability

Please report vulnerabilities privately. **Do not open a public GitHub issue
for a security problem.**

- Preferred: open a private report via
  **GitHub Security Advisories** on the `ruslanmv/ollabridge` repository
  (Security tab → "Report a vulnerability").
- Alternatively, email **contact@ruslanmv.com** with a description,
  reproduction steps, and the affected version/commit.

What to expect: an acknowledgement, a fix or mitigation plan, and credit in
the release notes if you want it. Please give us reasonable time to ship a
fix before public disclosure.

In scope: the local gateway (`src/ollabridge`), its CLI, the cloud bridge
client, and the published Docker image. Cloud-side issues
(`ollabridge-cloud`) can be reported through the same channels.

---

## Secret handling

### Provider API keys (`SecretStore`)

Provider credentials (OpenAI, Anthropic, Groq, Hugging Face, …) are stored in
`~/.ollabridge/secrets.enc` via the `SecretStore`
(`src/ollabridge/addons/providers/secret_store.py`):

- **Encryption**: Fernet (AES-128-CBC + HMAC-SHA256, authenticated) with a
  key derived from the `OLLA_SECRET` environment variable using HKDF-SHA256.
- **`OLLA_SECRET` is required for encryption at rest.** The same secret on
  another machine reads the same store (useful for backup/migration);
  rotating `OLLA_SECRET` invalidates the store and keys must be re-entered.
- **Fallback**: if `OLLA_SECRET` is unset (or the `cryptography` package is
  missing), keys are stored **in plaintext** with file mode `0o600` and a
  loud log warning. This is acceptable for throwaway dev setups only —
  always set `OLLA_SECRET` in production. `ollabridge doctor security`
  reports this condition as a failure when secrets are present.
- Writes are atomic (temp file + `os.replace`) and `chmod 0o600`.

### Local tokens

- **Local API keys** (`sk-ollabridge-*`): `ollabridge start` auto-generates a
  random key if `API_KEYS` is missing and can persist it to `.env`
  (only when explicitly enabled; it never overwrites a user-provided value).
- **Pairing tokens** (`mtx_*`, `AUTH_MODE=pairing`): stored **SHA-256 hashed**
  in `~/.ollabridge/pair_tokens.json` — only the client holds the raw token.
  Tokens are revocable per device.
- **Cloud device token** (`dvt_*`): stored in plaintext in
  `~/.ollabridge/cloud_device.json` with mode `0o600`. The cloud side stores
  only a hash. See THREAT_MODEL.md for the residual risk.

### What is never logged or printed

- The `RequestLog` database and the trace store (`~/.ollabridge/traces.db`)
  contain **no prompt or response content** — only metadata (path, model,
  latency, token counts, ok/error category).
- Doctor checks never print a full credential; configured keys are shown as
  `sk-a…(redacted)` via `redact_secret`.
- `providers export` supports `--redacted` output.

### Redaction layer (`core/redact.py`)

A defense-in-depth layer scrubs credential shapes from any text that might
be logged or displayed:

- `redact_secret(value)` — keeps a 4-character hint, redacts the rest.
- `redact_text(text)` — scrubs known token patterns (`sk-ollabridge-*`,
  `dvt_*`, `obt_*`, `mtx_*`, `sk-ant-*`, `sk-or-*`, `sk-proj-*`, generic
  `sk-*`, `hf_*`, `gsk_*`, Google `AIza*`, AWS `AKIA*`, and
  `Bearer <token>` / `X-API-Key:` header shapes) from free-form text such as
  upstream error bodies and exception messages.
- `redact_mapping(dict)` — recursively redacts secret-looking keys
  (`api_key`, `token`, `secret`, `password`, `authorization`, …).
- `RedactionFilter` / `install_redaction_filter()` — a `logging.Filter`
  that scrubs log records defensively.

Tests in `tests/enterprise/test_redact.py` assert this behavior.

---

## Secure deployment summary

### Authentication modes (`AUTH_MODE`)

| Mode | Behavior | Use when |
|---|---|---|
| `required` (default) | Every request needs a valid API key (`X-API-Key` or `Authorization: Bearer`) | Default; any shared or networked machine |
| `local-trust` | Loopback clients (127.0.0.1/::1) bypass auth; remote clients need a key | Single-user desktop where all local processes are trusted |
| `pairing` | Short-lived console code exchanged for a revocable `mtx_*` token; static keys still work; loopback also bypasses | Pairing phones/tablets/other devices on a trusted host |

Note: in both `local-trust` and `pairing` modes, **any process on the same
machine can call the API without credentials**. Use `required` on shared
machines.

### API keys

- `API_KEYS` is a comma-separated list. The shipped default is the
  placeholder `dev-key-change-me`; `ollabridge start` replaces it with a
  generated `sk-ollabridge-*` key, but a bare
  `uvicorn ollabridge.api.main:app` would run with the placeholder —
  always set real keys when running the app directly.

### Bind host

- Default is `HOST=0.0.0.0` (all interfaces). `ollabridge start` prints a
  warning when binding to all interfaces without an explicit `--host` flag.
- Prefer `HOST=127.0.0.1` and put a TLS reverse proxy in front for any
  remote access. The local API serves **plain HTTP** — there is no built-in
  TLS.

### CORS

- Default `CORS_ORIGINS` allows localhost dev origins only
  (`http://localhost:5173,3000,8080` and `http://127.0.0.1:8080`).
- **Caveat:** an empty `CORS_ORIGINS` value becomes a wildcard `*` with
  credentials allowed. Never set it to an empty string; list explicit
  origins instead. `doctor security` flags the empty/wildcard case.

### Rate limiting

- Enforced via `slowapi`, keyed by remote address. Default `RATE_LIMIT=60/minute`
  (slowapi syntax, e.g. `120/minute`, `10/second`).

### Cloud relay

- The bridge to OllaBridge Cloud is **outbound-only WSS**
  (`wss://…/relay/connect`, `Authorization: Bearer <device_token>`).
  No inbound port needs to be opened. The relay only activates when
  `~/.ollabridge/cloud_device.json` exists or pairing is started explicitly.

---

## Production checklist

Before exposing OllaBridge beyond your own machine:

- [ ] **Set `OLLA_SECRET`** to a long random string so provider keys are
      Fernet-encrypted at rest (do this *before* adding provider keys).
- [ ] **Set real `API_KEYS`** — no `dev-key-change-me` placeholder; keep
      `AUTH_MODE=required`.
- [ ] **Bind to `HOST=127.0.0.1`**, or front the gateway with a TLS
      reverse proxy if remote access is needed (see DEPLOYMENT_HARDENING.md).
- [ ] **Set `CORS_ORIGINS`** to the explicit origins of your web clients;
      never leave it empty (empty = wildcard).
- [ ] **Set `ENROLLMENT_SECRET`** if you use multi-node enrollment — the
      default is `dev-enroll-change-me`.
- [ ] **Check file permissions**: everything under `~/.ollabridge`
      (`secrets.enc`, `cloud_device.json`, `sync.yaml`, `traces.db`, …)
      should be `0o600`. OllaBridge tightens these itself; verify after
      restores/copies.
- [ ] **Keep prompt logging off** unless you explicitly need it
      (`ollabridge sync status` shows the current state; all sensitive sync
      categories default to off).
- [ ] **Verify**: run `ollabridge doctor security` and resolve all
      FAIL/WARN results. Use `ollabridge doctor --json` in CI or cron for
      continuous verification.

```bash
ollabridge doctor security
ollabridge doctor          # full suite: local | cloud | relay | providers | security | e2e
```
