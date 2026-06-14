# Threat Model

This document describes what OllaBridge protects, against whom, how, and —
just as importantly — what it does *not* protect against. It reflects the
code as shipped (see `src/ollabridge/core/security.py`,
`core/pairing.py`, `addons/providers/secret_store.py`,
`cloud/bridge_manager.py`, `core/redact.py`, `core/paths.py`).

---

## Assets

| Asset | Location | Sensitivity |
|---|---|---|
| Provider API keys (OpenAI, Anthropic, Groq, HF, …) | `~/.ollabridge/secrets.enc` (Fernet-encrypted when `OLLA_SECRET` is set) | High — directly monetizable |
| Cloud device token (`dvt_*`) | `~/.ollabridge/cloud_device.json` (plaintext, `0o600`) | High — authenticates the device to the relay |
| Local API keys (`sk-ollabridge-*`) | `.env` / environment | Medium-High — full access to the local API |
| Pairing tokens (`mtx_*`) | `~/.ollabridge/pair_tokens.json` (SHA-256 hashed) | Medium — device-scoped, revocable |
| Prompt and response content | In memory per request; sent to whichever backend serves it | High — user data |
| Model artifacts | Ollama's storage (outside OllaBridge) | Low-Medium |
| Traces / request logs | `~/.ollabridge/traces.db`, `ollabridge.sqlite` | Low-Medium — metadata only, no content, but reveals usage patterns |
| Sync/policy/provider config | `sync.yaml`, `policies.yaml`, `providers.yaml` | Low — no secrets by design |

## Trust boundaries

| # | Boundary | Transport | Authentication |
|---|---|---|---|
| B1 | Client ↔ local gateway (`/v1/*`, `/admin/*`) | HTTP (no TLS built in), default port 11435 | API key / pairing token / loopback-trust, per `AUTH_MODE` |
| B2 | Gateway ↔ Ollama | HTTP to `localhost:11434` (default) | None — Ollama is trusted local infrastructure |
| B3 | Gateway ↔ OllaBridge Cloud relay | **Outbound-only WSS** to `/relay/connect` | `Bearer <device_token>`; cloud stores token hashed; tenant-isolated routing |
| B4 | Gateway ↔ hosted providers | HTTPS to provider APIs | Provider API keys from the `SecretStore` |
| B5 | Localhost trust (in `local-trust`/`pairing` modes) | Loopback | **None** — any local process on 127.0.0.1/::1 is trusted |

Notes on B5: this is an intentional design choice for single-user desktops.
The implication is that in `local-trust` mode (and the loopback fallback of
`pairing` mode), *every process on the machine* — including malware running
as any user — can call the API without credentials.

### Data flow summary

A request's content touches, at most:

1. **Client → gateway** (B1): plaintext HTTP unless you add a TLS proxy;
   authenticated per `AUTH_MODE`.
2. **Gateway → backend** (B2 or B4): localhost HTTP to Ollama, or HTTPS to a
   hosted provider — whichever the router selects. The trace records which.
3. **Cloud → gateway → backend** (B3): when a request arrives via the relay,
   the cloud sends a `req` frame over the established outbound WSS; the
   bridge forwards it to the local gateway (`127.0.0.1`, marked
   `X-OllaBridge-Relay: 1` so the trace shows `cloud_relay=true`) and
   returns the result. The gateway never accepts inbound connections from
   the cloud.

What is persisted along the way: a metadata-only trace row (`traces.db`) and
request-log row (`ollabridge.sqlite`). No step writes prompt or response
content to disk.

## Attacker profiles

| Attacker | Capability | Primary targets |
|---|---|---|
| A1 LAN attacker | Can reach the gateway port if bound to `0.0.0.0` | Unauthenticated API use, prompt interception (no TLS) |
| A2 Malicious local process | Runs code on the same machine (same or other user) | Loopback auth bypass (B5), reading `~/.ollabridge` files |
| A3 Compromised cloud | Controls the relay / cloud control plane | Routing chat requests through your device, reading synced metadata |
| A4 Network MITM | On-path between gateway and cloud/providers | Device token, prompt content in transit |
| A5 Stolen laptop / disk | Offline access to the filesystem | `secrets.enc`, `cloud_device.json`, traces |
| A6 Malicious/compromised provider | Receives requests you route to it | Prompt content of routed requests |

## Threats and mitigations

| Threat | Attacker | Mitigation in code |
|---|---|---|
| Unauthenticated API access over the network | A1 | `AUTH_MODE=required` is the default; every `/v1/*` request needs a key (`core/security.py`). `start` warns when binding `0.0.0.0` without an explicit `--host`. Rate limiting (slowapi, `60/minute` default) slows brute force. |
| Default placeholder credentials | A1 | `ollabridge start` auto-generates a random `sk-ollabridge-*` key when `API_KEYS` is missing; `doctor security` fails on `dev-key-change-me` / `dev-*` placeholders. |
| Stolen pairing token reused after device loss | A2 | Pairing tokens stored **SHA-256 hashed** locally; per-device revocation via `/pair/revoke`. Pairing codes are single-use, short-TTL (300 s), generated with `secrets`. |
| Provider keys read from disk | A2, A5 | Fernet (AES-128-CBC + HMAC-SHA256) at rest with HKDF-derived key from `OLLA_SECRET`; atomic writes; `chmod 0o600` on all sensitive files (`paths.tighten_permissions`); `doctor security` verifies permissions. |
| Credentials leaking into logs/CLI output/error messages | A2, support channels | Redaction layer (`core/redact.py`): pattern-based scrubbing of all known token shapes, recursive mapping redaction, `RedactionFilter` for loggers; doctor prints only `sk-a…(redacted)` hints. Asserted by `tests/enterprise/test_redact.py`. |
| Prompt content persisted and later exfiltrated | A2, A5 | Trace store and request log are metadata-only by schema — no content columns exist. Prompt logging is a sync flag defaulting to `false` and never auto-enabled. |
| Inbound attack surface from cloud connectivity | A1, A3 | The relay is **outbound-only WSS** — no inbound port is opened. The bridge only starts when credentials exist or pairing is explicitly initiated. |
| Cloud operator replays/forges device credentials | A3 | Cloud stores device credentials hashed (HMAC-SHA256 + pepper) and collapses enrollment errors to prevent token probing (cloud-side, verified in the enterprise audit). |
| Cross-tenant request routing in the cloud | A3 | Tenant isolation in the cloud `RelayHub`: relay requests route only to devices owned by the requesting user (cloud-side). |
| MITM on the relay link | A4 | WSS (TLS) to the cloud; device token sent only as a Bearer header over TLS. |
| Secrets synced to the cloud by accident | A3 | `sync.yaml` defaults: all five sensitive categories `false`; preferences push strips secrets by construction and hard-codes `token_synced: false`; `providers.yaml` never contains secrets by design. |
| Unauthorized cloud pairing | A3 | TV-style pairing requires the user to confirm a short code in the cloud dashboard; bootstrap enrollment uses one-time `obt_*` tokens. |

## Remaining risks (accepted or open)

Be honest about these when deciding how to deploy:

| Risk | Detail | Recommended handling |
|---|---|---|
| Plaintext provider keys without `OLLA_SECRET` | If `OLLA_SECRET` is unset, `secrets.enc` is plaintext (`0o600`) with only a log warning. | Always set `OLLA_SECRET` before adding keys; `doctor security` fails loudly when secrets exist unencrypted. |
| Device token plaintext on disk | `cloud_device.json` holds the raw `dvt_*` token at `0o600` (not keychain-backed). Anyone with file read access as your user can impersonate the device. | Full-disk encryption; revoke the device in the cloud dashboard if the machine is lost. |
| Loopback bypass modes | `local-trust` mode and the loopback fallback in `pairing` mode trust every local process. | Use `AUTH_MODE=required` on shared or multi-user machines. |
| No TLS on the local API | The gateway serves plain HTTP. On `0.0.0.0`, LAN peers can sniff prompts and keys in transit. | Bind `127.0.0.1`, or terminate TLS at a reverse proxy (see DEPLOYMENT_HARDENING.md). |
| Error text leakage | Upstream exception text can reach clients (e.g. `HTTPException(500, str(e))` in chat completions). Redaction scrubs known credential shapes, but non-credential internals may still leak. | Front with a proxy that rewrites 5xx bodies if this matters; report any credential-shaped leak as a vulnerability. |
| Default bind `0.0.0.0` | Exposure is warned about at `start`, but a direct `uvicorn` launch is silent. | Set `HOST=127.0.0.1` explicitly. |
| Empty `CORS_ORIGINS` becomes wildcard | `""` → `allow_origins=["*"]` with credentials. | Never set `CORS_ORIGINS` empty; `doctor security` flags it. |
| No request body size limit | No explicit body-size middleware. | Enforce `client_max_body_size` (or equivalent) at the reverse proxy. |
| Default `ENROLLMENT_SECRET` | Ships as `dev-enroll-change-me`. | Set a real value for multi-node enrollment; `doctor security` warns. |

## Security assumptions

The mitigations above hold only if these assumptions do:

- The host OS and user account are not already compromised — file mode
  `0o600` and loopback trust are meaningless against an attacker running as
  your user.
- `OLLA_SECRET` is set from a high-entropy source and provided only via the
  environment (it is the sole input to the HKDF key derivation for
  `secrets.enc`).
- The OllaBridge Cloud instance you pair with is the one you intend
  (`OLLABRIDGE_CLOUD_URL` / `--cloud`); pairing trusts the TLS identity of
  that endpoint.
- On non-POSIX systems (Windows), the `0o600` permission checks are skipped
  (`paths.permissions_ok` returns `True`); NTFS ACLs are out of scope.

## Out of scope

- Compromise of the host OS or of Ollama itself (B2 is a trusted boundary).
- Confidentiality of prompts you deliberately route to hosted providers (A6)
  beyond their own terms — OllaBridge records the routing decision in traces
  so you can audit *where* content went.
- SSO/OIDC, SCIM, per-key RBAC scopes — roadmap items, not shipped; the
  local gateway currently has a single shared API-key class.

## Verification

```bash
ollabridge doctor security    # auth posture, secrets-at-rest, permissions, CORS, bind host
ollabridge doctor relay       # outbound WSS handshake, token validity, reconnect
ollabridge sync status        # sensitive sync categories
```
