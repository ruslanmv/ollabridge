# Enterprise Roadmap

This roadmap tracks OllaBridge's path from a local-first gateway to an
enterprise-ready platform. Status markers are strict:

- **DONE** — shipped and verifiable in this repository (or, where noted, in
  `ollabridge-cloud`).
- **PARTIAL** — a usable subset shipped; the rest is explicitly listed.
- **PLANNED** — designed (sometimes with interfaces in place), not built.

Baseline analysis for all of this: `docs/AUDIT_ENTERPRISE_READINESS.md`.

---

## Phase 1 — Trust & reliability — **DONE in this release**

Goal: make the local gateway diagnosable, observable, and safe by default,
without changing `/v1/*` behavior.

| Item | Status | Where |
|---|---|---|
| `ollabridge doctor` suite: `local`, `cloud`, `relay`, `providers`, `security`, `e2e`, all with `--json` and non-zero exit on failure | DONE | `src/ollabridge/doctor/`, `cli/doctor.py` |
| Relay verification without a second machine (WSS connect, hello, model registration, ping/pong, reconnect, optional cloud-side model comparison) | DONE | `doctor/checks.py`; see `docs/RELAY_VERIFICATION.md` |
| End-to-end probe with latency breakdown (total / relay overhead / model) | DONE | `doctor/e2e.py` |
| Request tracing: `request_id` on every request (`X-Request-ID`), SQLite trace store with **no prompt content**, `ollabridge traces list\|show` | DONE | `src/ollabridge/tracing/store.py`, `cli/traces.py` |
| Redaction everywhere: secret-shape scrubbing, redacted display hints, logging filter | DONE | `src/ollabridge/core/redact.py` |
| Hardening: bind-all warning on `start`, placeholder-key detection, file-permission checks, CORS/auth/prompt-logging posture checks | DONE | `cli/main.py`, `doctor/checks.py` |
| Policy routing with built-in aliases (`local-private`, `fast`, `cheap`, `best`, `coding`, `reasoning`, `vision`, `team-default`, `cloud-relay`, `local-gpu`), validation, and `route explain` | DONE | `src/ollabridge/policies/`, `cli/policies.py` |

**Phase 1 exit criteria (met):** a user can verify the entire system —
local gateway, cloud pairing, relay handshake, provider credentials, security
posture, and a real end-to-end request — from one machine with
`ollabridge doctor`, in human or JSON form, and no diagnostic ever prints a
full credential or stores prompt content.

## Phase 2 — Cloud sync MVP — **PARTIAL (metadata push shipped)**

Goal: explicit, consent-based sync with privacy-first defaults.

| Item | Status | Notes |
|---|---|---|
| `~/.ollabridge/sync.yaml` consent file (metadata on-after-login; five sensitive categories off, never auto-enabled) | DONE | `cloud/sync_config.py`; see `docs/CLOUD_SYNC.md` |
| `ollabridge login` / `logout` (TV-style pairing, 0600 credentials, sync auto-enable/disable) | DONE | `cli/cloud_login.py` |
| `ollabridge sync status\|enable\|disable\|config\|push\|pull` | DONE | `cli/sync.py` |
| Metadata **push** (provider names/kinds, alias names; secrets structurally excluded, `token_synced` hard-coded false) | DONE | `cloud/preferences_sync.py` |
| **Pull** / two-way preferences sync | MATURING | `sync pull` is a read-only preview; degrades gracefully (404 → "cloud does not support pull yet") |
| Conflict handling, multi-device preference merge | PLANNED | requires the pull path to mature cloud-side |

**Phase 2 exit criteria:** push is DONE (a paired, sync-enabled device can
push its metadata snapshot and see `stored_at` confirmation). The phase
closes when pull returns a usable snapshot from a current cloud and the
device can apply (not just preview) it. The privacy contract is already
final: the payload schema in `cloud/preferences_sync.py` is allow-listed and
secrets-free by construction, and that does not loosen in later phases.

## Phase 3 — BYOK provider hub — **PARTIAL (local CLI shipped)**

Goal: secure BYOK routing across your authorized devices and workspaces.

| Item | Status | Notes |
|---|---|---|
| `ollabridge providers list\|add\|remove\|test\|rotate\|status\|export --redacted` | DONE | `cli/providers.py`; see `docs/PROVIDER_KEYS.md` |
| 13-provider catalog with env-var fallbacks; metadata-only `providers.yaml`; encrypted `secrets.enc` (Fernet via `OLLA_SECRET`) | DONE | `providers_meta.py`, `provider_ops.py` |
| No-cost health checks (models-list endpoint; no prompt content) | DONE | `provider_ops.test_provider` |
| Storage-mode selection (`local_only` / `cloud_encrypted_vault` / `organization_vault`) | DONE as **intent recording** — modes 2/3 keep the key local and say so; nothing uploads silently | `providers_meta.py` |
| Cloud encrypted vault API (per-user devices) | PLANNED cloud-side | local push activates once it ships; gated on the `provider_secrets_cloud_vault` opt-in |
| Organization vault API | PLANNED cloud-side | the envelope-encryption schema (`ProviderKey`: per-row DEK wrapped by master KEK, last-4 display, rotation with audit history) already exists in `ollabridge-cloud` |

**Phase 3 exit criteria:** a user (or org admin) who selected storage mode
2 or 3 — and explicitly enabled `provider_secrets_cloud_vault` — can push a
key to the cloud vault, see `vault_synced: true` in
`ollabridge providers export --redacted`, and use the provider from another
authorized device. Framing rule for all Phase 3 material: this is **secure
BYOK routing across your authorized devices and workspaces** — credentials
the org owns, governed by org policy and audit — never "sharing someone's
provider account".

Dependency: the vault API lands in `ollabridge-cloud`; the local CLI's
gating (pairing + explicit sync opt-in + cloud capability) is already in
place and will simply stop reporting "stays LOCAL-ONLY" once the cloud side
ships.

## Phase 4 — Enterprise admin — **PLANNED (interfaces in place)**

Goal: org-grade access control and administration.

| Item | Status | Notes |
|---|---|---|
| RBAC contract: 7 roles (Owner, Admin, Developer, Viewer, Billing Admin, Security Auditor, Device Operator) × 12 permission strings | INTERFACES DONE | `src/ollabridge/enterprise/rbac.py`; stable identifiers, fail-closed helpers |
| RBAC **enforcement** | PLANNED | cloud currently enforces `org_admin`/`member`/`viewer` on `OrgMembership`; convergence to the full contract as the cloud matures |
| Bootstrap fleet enrollment (`obt_*` tokens, `POST /device/enroll`) | DONE cloud-side | single-use, expiring, revocable, audited; first-class local-CLI consumption is this phase's work |
| Scoped local API keys (per-key permissions instead of one shared key class) | PLANNED | |
| Audit log API / export for org admins | PLANNED | append-only `AuditEvent` capture already shipped cloud-side |
| SSO (OIDC; SAML as demand requires) | PLANNED | tenant resolver and `Org.settings_json` deliberately leave room; **not implemented** |
| SCIM user provisioning | PLANNED | alongside SSO |
| Relay streaming (`delta`/`done` emission from the local bridge; today relay responses are buffered into a single `res`) | PLANNED | coordinated change across both repos |

**Phase 4 exit criteria:** an org admin can provision a fleet with `obt_*`
tokens entirely through the OllaBridge CLI, assign the seven-role model to
members, mint API keys scoped to a permission set, and export the audit
trail — with the permission strings in `enterprise/rbac.py` (`models:read`,
`chat:invoke`, `devices:pair`, `devices:share`, `providers:create`,
`providers:use`, `providers:rotate`, `logs:read`, `audit:read`,
`billing:read`, `policies:write`, `org:admin`) enforced cloud-side, not just
defined locally.

## Phase 5 — Compliance & production hardening — **PLANNED**

Goal: the artifacts and controls enterprise procurement asks for.

| Item | Status |
|---|---|
| SBOM published per release | PLANNED |
| Signed releases (artifact signing + provenance) | PLANNED |
| SOC 2-style control mapping (change management, access reviews, audit retention) | PLANNED |
| Data retention policies (trace/audit pruning defaults — `TraceStore.prune()` exists; policy surface does not yet) | PLANNED |
| Documented threat model and security disclosure process | PLANNED |
| Cloud-side rate limiting per device/user (protocol reserves it) | PLANNED |

---

## Summary: shipped vs. planned at a glance

**Shipped today:** local gateway with required-by-default auth; full doctor
suite; metadata-only cloud sync with explicit consent; BYOK provider CLI with
encrypted local storage, rotation, and redaction; policy routing with
explainability; request tracing without content; cloud-side multi-tenancy
(Org/OrgMembership), hashed device tokens, `obt_*` bootstrap enrollment, and
an append-only audit trail.

**Not shipped (do not claim in sales conversations):** cloud/org vault key
upload, RBAC enforcement beyond `org_admin`/`member`/`viewer`, scoped API
keys, audit export API, SSO/OIDC/SAML, SCIM, relay streaming, SBOM/signed
releases, SOC 2 attestation.
