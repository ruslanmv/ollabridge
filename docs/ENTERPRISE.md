# OllaBridge Enterprise Architecture

This document describes how OllaBridge fits into an enterprise environment:
what runs on your machines, what (optionally) runs in OllaBridge Cloud, how
fleets are provisioned, and which access-control features are implemented
today versus designed for the next phases.

**Honesty contract:** everything in this document is labelled as either
*shipped* (verifiable in this repository or in `ollabridge-cloud`) or
*design / planned*. Nothing planned is presented as if it works today.

---

## 1. Two-plane architecture

OllaBridge is **local-first**. The gateway is fully functional with no cloud
account, no login, and no outbound connection.

```
                       ┌────────────────────────────────────────────┐
  OpenAI SDK / curl ──▶│  Local gateway (FastAPI, :11435)           │
                       │   /v1/chat/completions  /v1/models         │
                       │   /v1/embeddings  /health  /ui  /admin/*   │
                       │                                            │
                       │  Router → local Ollama, direct endpoints,  │
                       │  HomePilot personas, BYOK providers        │
                       └───────────────┬────────────────────────────┘
                                       │ optional outbound WSS only
                                       ▼
                       ┌────────────────────────────────────────────┐
                       │  OllaBridge Cloud (control plane / relay)  │
                       │   TV-style pairing: /device/start|poll     │
                       │   Bootstrap enroll: /device/enroll (obt_*) │
                       │   Relay: wss://…/relay/connect             │
                       │   Tenancy: Org / OrgMembership / ApiKey    │
                       └────────────────────────────────────────────┘
```

- **Local gateway** (this repo, `ruslanmv/ollabridge`): OpenAI-compatible API,
  policy routing, BYOK provider management, tracing, diagnostics. All state
  lives under `~/.ollabridge/` (`sync.yaml`, `providers.yaml`,
  `policies.yaml`, `secrets.enc`, `cloud_device.json`, `traces.db`).
- **Cloud control plane** (`ruslanmv/ollabridge-cloud`): device pairing and
  enrollment, tenant-scoped relay routing, cloud API keys, the org/tenancy
  model, and the append-only audit trail. Everything in section 2–4 below
  that mentions database models or cloud endpoints lives in that repo.

The connection is always **outbound** from the gateway (WSS with a Bearer
device token). The cloud never dials into your network.

## 2. Organizations, users, and devices (shipped, cloud-side)

The cloud repo implements multi-tenancy in `src/ollabridge_cloud/db/models.py`
and `src/ollabridge_cloud/auth/tenant.py`:

| Concept | Model | Status |
|---|---|---|
| Organization (tenant) | `Org` — `plan: personal \| enterprise`, unique slug | Shipped |
| Membership & role | `OrgMembership` — roles `org_admin`, `member`, `viewer` | Shipped (viewer reserved/read-only) |
| User | `User` — email login or Google; `primary_org_id` | Shipped |
| Device | `Device` — a machine running the OllaBridge gateway, scoped by `org_id` | Shipped |
| Device token | `DeviceToken` — HMAC-SHA256 hashed at rest, revocable | Shipped |
| Cloud API key | `ApiKey` — `ob_*` bearer keys; admin-, user-, or org-minted | Shipped |
| Org provider keys | `ProviderKey` — envelope-encrypted (per-row DEK wrapped by a master KEK) | Shipped cloud-side schema; see `docs/PROVIDER_KEYS.md` for the local story |
| Audit trail | `AuditEvent` — append-only, never stores secrets (key ids + last-4 only) | Shipped |

Key tenancy properties (cloud-side, shipped):

- Every secret-bearing row carries an `org_id`; individual signups get an
  auto-created **personal Org**, enterprises use `plan: enterprise`.
- The relay hub scopes routing by Org: a request authenticated to Org A can
  never reach an Org B device (`auth/tenant.py` resolves the tenant before
  any secret is touched).
- Tenant resolution order: `ob_*` API key → session cookie → JWT bearer →
  dev stub header.

**What is design-only:** *workspaces* and *teams* below the Org level. The
local policy schema reserves `scope: {workspace, project, users, teams}`
(`src/ollabridge/policies/models.py`) but it is advisory locally and not yet
enforced anywhere. There is one tenancy level today: the Org.

## 3. Fleet provisioning: bootstrap enrollment (shipped, cloud-side)

For individuals, pairing is TV-style (`ollabridge login` → open URL → type
code). For fleets, the cloud supports **one-paste bootstrap enrollment**:

1. An org admin mints a single-use bootstrap token (`obt_*`) from the tenant
   admin surface (cloud repo: `BootstrapToken` model). The plaintext is shown
   once; only its HMAC-SHA256 hash is stored.
2. The token is distributed via config management to the target machine.
3. The machine POSTs `POST /device/enroll` with the token
   (cloud repo: `src/ollabridge_cloud/api/enroll.py`) and immediately
   receives a `device_id` + `device_token` joined to the issuing Org —
   no human code dance.

Security properties of `/device/enroll` (shipped):

- Tokens are **single-use** (`used_at` stamps on consumption) and expiring,
  and can be revoked before use.
- Failure modes are collapsed (invalid → 400, expired/consumed/revoked → 410
  with a stable error code) so a probing attacker cannot distinguish token
  states; failed attempts are audited as `device.enroll_failed`.
- Successful enrollment is audited as `device.enrolled`.

**Current local gap (be aware):** the local CLI ships TV-style pairing
(`ollabridge login`) today; first-class `obt_*` consumption from the local
CLI is on the roadmap (see `docs/ROADMAP_ENTERPRISE.md`, Phase 4). The cloud
endpoint is live and can be driven directly.

## 4. RBAC: target contract vs. current enforcement

OllaBridge defines its target RBAC contract locally in
`src/ollabridge/enterprise/rbac.py`. These are **stable interface
definitions** — permission strings are `<resource>:<action>` identifiers that
will never be renamed, only added to.

Permission strings (defined, shipped as constants):

`models:read`, `chat:invoke`, `devices:pair`, `devices:share`,
`providers:create`, `providers:use`, `providers:rotate`, `logs:read`,
`audit:read`, `billing:read`, `policies:write`, `org:admin`

Target roles and grants:

| Role | Permissions |
|---|---|
| Owner | all permissions |
| Admin | all except `billing:read` |
| Developer | `models:read`, `chat:invoke`, `devices:pair`, `providers:use`, `logs:read` |
| Viewer | `models:read`, `logs:read` |
| Billing Admin | `billing:read`, `models:read` |
| Security Auditor | `audit:read`, `logs:read`, `models:read` |
| Device Operator | `devices:pair`, `devices:share`, `models:read` |

**Current enforcement — the honest version:** the cloud today enforces a
coarser three-role model on `OrgMembership`: `org_admin` (manage providers,
devices, keys, members), `member` (use org resources; cannot mint keys or
rotate provider keys), and `viewer` (reserved, read-only). The seven-role /
twelve-permission contract above is what both sides converge on as the cloud
matures; locally it is available as `Role`, `Permission`,
`permissions_for()`, and `role_allows()` (fail-closed on unknowns) for
integrators who want to build against the target model now.

## 5. Audit and policy

- **Cloud audit (shipped):** `AuditEvent` rows record every privileged
  action (key mint/rotate/revoke, member invite, provider-key paste, device
  enrollment, plan upgrade) with actor, org, IP, and user agent. Secrets are
  never stored — key ids and last-4 only. An audit *export API* surfaced to
  org admins is Phase 4 work.
- **Local tracing (shipped):** every gateway request gets a `request_id`
  (`X-Request-ID`); `~/.ollabridge/traces.db` stores routing metadata —
  model, backend, relay involvement, latency, token counts — and **never
  prompt or response content**. Inspect with `ollabridge traces list|show`.
- **Policy routing (shipped, local):** `~/.ollabridge/policies.yaml` plus
  built-in aliases (`local-private`, `fast`, `cheap`, `best`, `coding`,
  `reasoning`, `vision`, `team-default`, `cloud-relay`, `local-gpu`) with
  allow/deny lists, ordered preferences, cost ceilings, and a `fallback`
  switch. `ollabridge policies validate|list|explain` and
  `ollabridge route explain <alias>` show exactly what would happen — and
  why — without sending a prompt.

Example: guarantee a class of traffic never leaves the machine:

```yaml
policies:
  - name: confidential
    match: {alias: local-private}
    route:
      allow: [{type: local_device}]
      deny: [{type: external_provider}, {type: cloud_relay}]
      fallback: false
    logging: {prompt_logging: false}
```

## 6. Deployment options

| Option | Description | Status |
|---|---|---|
| Local only | `ollabridge start --host 127.0.0.1`; no cloud, no login. Auth defaults to required API keys. | Shipped |
| LAN gateway | `ollabridge start --lan`; static keys or pairing-code auth for devices on your network. | Shipped |
| Managed cloud | Pair against `https://api.ollabridge.com` with `ollabridge login`. | Shipped |
| Self-hosted cloud | Run `ollabridge-cloud` yourself (Docker Compose / HF Spaces recipes in that repo); point the gateway at it with `--cloud` or `OLLABRIDGE_CLOUD_URL`. | Shipped |
| Fleet provisioning | `obt_*` bootstrap tokens against `/device/enroll`. | Cloud-side shipped; local CLI integration planned |

Hardening checklist before exposing a gateway beyond localhost:
run `ollabridge doctor security` (secret encryption, file permissions,
auth mode, CORS, bind host, prompt-logging posture) and act on every
FAIL/WARN.

## 7. SSO, SCIM, and compliance — future compatibility

The following are **not implemented** in either repository. They are listed
so enterprise evaluators know the intended direction (see
`docs/ROADMAP_ENTERPRISE.md`, Phases 4–5):

- **SSO via OIDC / SAML** — the cloud's tenant resolver
  (`auth/tenant.py`) was deliberately placed so OIDC integrations have a
  natural home, and `Org.settings_json` reserves space for an SSO subject
  domain; no identity-provider integration exists today (local email/password
  and Google sign-in only).
- **SCIM provisioning** — planned alongside SSO; today membership is managed
  by org-admin invitation.
- **Billing administration** — usage rolls up per-Org (`UsageEvent`), and the
  `billing:read` permission is reserved; there is no billing API surface yet.

If a vendor questionnaire asks "does OllaBridge support SAML?", the accurate
answer today is: *no — planned; the tenancy and audit substrate it requires
is already in production shape.*
