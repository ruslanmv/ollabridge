# OllaBridge — Enterprise Readiness Audit

Date: 2026-06-10
Scope: `ruslanmv/ollabridge` (local gateway) with cross-reference to
`ruslanmv/ollabridge-cloud` (cloud control plane / relay).

This audit was produced **before** any code changes, as the baseline for the
enterprise hardening work tracked in `docs/ROADMAP_ENTERPRISE.md`.

---

## 1. Current architecture summary

OllaBridge today is a local-first, OpenAI-compatible gateway in front of
Ollama (and optionally HomePilot personas and hosted providers), with an
optional outbound WebSocket bridge to OllaBridge Cloud.

```
                        ┌────────────────────────────────────────────┐
   OpenAI SDK / curl ──▶│  Local gateway (FastAPI, :11435)           │
                        │   /v1/chat/completions  /v1/models         │
                        │   /v1/embeddings  /health  /ui  /admin/*   │
                        │                                            │
                        │  core.router ──▶ connectors:               │
                        │    • local Ollama (default node)           │
                        │    • relay_link (nodes dial in via WS)     │
                        │    • direct_endpoint                       │
                        │    • homepilot (personas)                  │
                        │    • addons/providers (Gemini, Groq, HF,   │
                        │      OpenRouter, DeepSeek, OpenAI-compat)  │
                        └───────────────┬────────────────────────────┘
                                        │ outbound WSS (CloudBridgeManager)
                                        ▼
                        ┌────────────────────────────────────────────┐
                        │  OllaBridge Cloud (/relay/connect)         │
                        │  TV-style pairing: /device/start|poll      │
                        │  Bootstrap enroll: /device/enroll (obt_*)  │
                        │  Tenant-scoped relay routing               │
                        └────────────────────────────────────────────┘
```

Key components (local repo):

| Area | Location | State |
|---|---|---|
| CLI | `src/ollabridge/cli/main.py` | `start`, `up`, `doctor` (basic), `models`, `test-chat`, `enroll-create`, `pair-refresh` |
| Node agent CLI | `src/ollabridge/node/cli.py` | `join`, `cloud-pair`, `cloud-connect` |
| API | `src/ollabridge/api/main.py` | `/v1/*`, `/admin/*`, `/pair/*`, `/relay/connect` |
| Auth | `core/security.py` | `required` / `local-trust` / `pairing` modes |
| Cloud client | `cloud/api_client.py`, `cloud/bridge_manager.py` | TV-style pairing + auto-reconnecting relay bridge |
| Cloud credentials | `cloud/device_config.py` | `~/.ollabridge/cloud_device.json`, `0o600` |
| Provider addon | `addons/providers/*` | registry, score-based router, quotas, health, encrypted `SecretStore` |
| Persistence | `db/` | SQLite `RequestLog` (path, model, latency, ok, client — **no prompt content**) |

Cloud wire protocol (verified against `ollabridge-cloud`):

- Pairing: `POST /device/start` → `user_code` + `verification_url`;
  `POST /device/poll` → `{status, device_id, device_token}` (`dvt_*`).
- Enterprise enrollment: `POST /device/enroll` with one-time `obt_*` token.
- Relay: `wss://…/relay/connect` with `Authorization: Bearer <device_token>`;
  JSON frames `hello | ping | pong | req | res | delta | done | error`;
  cloud routes `/v1/chat/completions` to a device that registered the model,
  scoped to the owning user (tenant isolation in `RelayHub`).

## 2. Existing strengths

1. **Local-first already true.** `ollabridge start` requires no cloud login;
   the cloud bridge only activates when `~/.ollabridge/cloud_device.json`
   exists or pairing is started explicitly.
2. **No prompt logging.** `RequestLog` stores only path/model/latency/ok/client.
   No telemetry phone-home was found.
3. **Secrets are encrypted at rest** when `OLLA_SECRET` is set
   (`SecretStore`, Fernet + HKDF-SHA256), with `0o600` plaintext fallback.
4. **Relay bridge is robust**: exponential backoff reconnect (2/4/8/16/30s),
   WS-level ping/pong, periodic model re-registration, model discovery via
   the gateway's own `/v1/models`.
5. **Cloud preferences sync is secrets-free by construction**
   (`cloud/preferences_sync.py` strips everything but provider/alias metadata
   and hard-codes `token_synced: False`).
6. **Auth defaults to required** API keys; pairing tokens are stored hashed.
7. **Cloud side hashes credentials** (HMAC-SHA256 + pepper), enforces
   tenant isolation in relay routing, and collapses enrollment errors to
   prevent token probing.

## 3. Existing risks

| # | Risk | Severity | Detail |
|---|---|---|---|
| R1 | Default bind `0.0.0.0` | Medium | `Settings.HOST` and `start --host` default to all interfaces. Auth is required by default, which mitigates — but exposure is silent. |
| R2 | Default placeholder API key | Medium | `API_KEYS="dev-key-change-me"` in settings; CLI replaces it at `start`, but a bare `uvicorn ollabridge.api.main:app` would run with the placeholder. |
| R3 | Plaintext device token | Medium | `cloud_device.json` stores `device_token` in plaintext (0o600). Acceptable for a device credential, but not keychain-backed. |
| R4 | Plaintext secret fallback | Medium | Without `OLLA_SECRET`, provider keys are stored plaintext (0o600) with only a log warning. |
| R5 | CORS wildcard when empty | Low | `CORS_ORIGINS=""` becomes `allow_origins=["*"]` with `allow_credentials=True`. |
| R6 | No request size limits | Low | No explicit body-size limit middleware. |
| R7 | `local-trust`/pairing loopback bypass | Low | Reasonable design, but undocumented threat model (anything on localhost can call the API). |
| R8 | Errors leak internals | Low | `chat_completions` raises `HTTPException(500, str(e))` — upstream exception text reaches the client. |

## 4. Missing enterprise features (pre-work)

- **No `ollabridge login`** — cloud pairing existed only via the node CLI
  (`ollabridge-node cloud-pair`) or the admin HTTP API.
- **No explicit sync model** — preferences push exists but there is no
  `sync.yaml`, no consent surface, no `ollabridge sync …` commands.
- **No relay diagnostics** — `doctor` checked only Ollama + local health;
  nothing verified cloud credentials, the WSS handshake, reconnect, or an
  end-to-end request path.
- **No provider CLI** — providers are seeded from YAML/env or managed via
  `/admin/providers/*`; no `providers add/test/rotate/export` UX, no
  storage-mode choice (local / cloud vault / org vault).
- **No policy engine** — aliases exist (`model_aliases.yaml`, hf_catalog) but
  there is no user-editable policy file, no allow/deny, no cost/latency
  ceilings, no `route explain`.
- **No request tracing** — no `request_id`, no `X-Request-ID` header, no
  trace store, no `traces` CLI.
- **No enterprise docs** — SECURITY/PRIVACY/THREAT_MODEL/CLOUD_SYNC/
  PROVIDER_KEYS/ENTERPRISE/DEPLOYMENT_HARDENING did not exist.
- **No RBAC surface locally** — single shared API key class; no scoped keys,
  roles, orgs, or audit log file. (Cloud has orgs/memberships already.)

## 5. Security concerns (summary)

1. Bind-all default + silent exposure (R1) — needs explicit confirmation/warning.
2. Secrets-at-rest depend on an env var users may not set (R4) — needs a
   first-run nudge and a `doctor security` check.
3. No redaction helper — nothing prevents future code from logging a key.
4. No security test suite asserting: secrets never printed, auth rejects
   unauthenticated calls, CORS defaults safe, prompt logging off by default.
5. `Settings.ENROLLMENT_SECRET` defaults to `dev-enroll-change-me`.

## 6. Cloud/local compatibility gaps

| Gap | Detail |
|---|---|
| Streaming over relay | Cloud protocol defines `delta`/`done`; the local bridge (`CloudBridgeManager._handle_request`) only answers with a single `res`. Streaming requests are degraded to buffered responses. |
| App-level ping | Cloud expects optional app-level `ping`→`pong`; local bridge relies on WS-protocol ping only (works, but `last_seen` style liveness on cloud is coarser). |
| `embeddings` op | Cloud may send `op: embeddings`; local bridge handles `chat`, `models`, `media_fetch` only. |
| Pull-side sync | Preferences push exists; there is no pull, no sync status surface, and no consent file. |
| Bootstrap enrollment | Cloud supports `obt_*` one-paste enrollment; local CLI exposes only TV-style pairing. |
| Device naming | Poll response carries `device_id` only; local UX cannot show the human device name without an extra API. |

## 7. Relay reliability gaps

- No way for a user to *verify* the relay path without sending real traffic
  from another machine (no `doctor relay`, no `doctor e2e`).
- No measurement of relay vs model latency.
- No diagnostics for the common failure modes: missing credentials, expired
  or revoked token (WS close `4401`), cloud unreachable, device offline,
  model not registered.
- Reconnect works but is unobservable except via logs / `/admin/cloud/status`.

## 8. Recommended implementation roadmap

Implemented in this order (see `docs/ROADMAP_ENTERPRISE.md` for phases):

1. **P1 — Preserve the local gateway.** Baseline test run; no behavioral
   changes to `/v1/*`; all new behavior is additive and opt-in.
2. **P2 — Diagnostics.** `ollabridge doctor` suite with `local | cloud |
   relay | providers | security | e2e` subcommands and `--json` output.
3. **P3 — Explicit cloud sync.** `~/.ollabridge/sync.yaml` with metadata-only
   defaults; `ollabridge sync status|enable|disable|push|pull|config`;
   `ollabridge login` (TV-style pairing) and `logout`.
4. **P4 — Provider hardening.** `ollabridge providers
   list|add|remove|test|rotate|status|export --redacted`, storage-mode choice,
   normalized provider catalog (OpenAI, Anthropic, Gemini, Azure OpenAI,
   Bedrock, Groq, OpenRouter, HF, DeepSeek, Mistral, Together, Fireworks,
   generic OpenAI-compatible), redaction everywhere.
5. **P5 — Policy routing.** `~/.ollabridge/policies.yaml`, built-in aliases
   (`local-private`, `fast`, `cheap`, `best`, `coding`, …),
   `policies validate|list|explain`, `route explain`.
6. **P6 — Tracing.** `request_id` on every request (`X-Request-ID`), trace
   store without prompt content, `traces list|show`.
7. **P7 — Enterprise docs & interfaces.** RBAC/permission constants and docs
   without faking unimplemented cloud features.

## 9. Out of scope for this pass (documented, not built)

- SSO/OIDC/SAML, SCIM, billing — interface notes only (`docs/ENTERPRISE.md`).
- Cloud-side organization vault — the local CLI records intent and keeps the
  secret local until the cloud vault API ships.
- Relay streaming (`delta`/`done`) emission from the local bridge — tracked
  as a compatibility gap; requires coordinated change in both repos.
