# Cloud Sync — Exactly What Leaves Your Machine

OllaBridge Cloud sync is **explicit, consent-based, and metadata-only by
default**. This page documents precisely what syncs, what never syncs without
an explicit opt-in, where the switch lives, and how to turn everything off.

Implementation references (source of truth):
`src/ollabridge/cloud/sync_config.py` (schema + defaults),
`src/ollabridge/cli/sync.py` (commands),
`src/ollabridge/cloud/preferences_sync.py` (the actual payload).

---

## 1. What syncs vs. what does not

**Syncs (metadata, only after login and while `enabled: true`):**

- Device status (online/offline, device id)
- Model **names** available on the device (never weights, never outputs)
- Routing profiles: provider names/kinds and alias→candidate maps
- Health metrics without prompt content

**Never syncs unless you flip the flag yourself** (no code path enables these
automatically):

- Conversation history
- Prompt logging
- Provider secrets (cloud vault) — and even with the flag on, nothing uploads
  until the paired cloud ships its vault API; see `docs/PROVIDER_KEYS.md`
- RAG documents
- Persona memory

**Never syncs, ever, under any flag:**

- Provider API keys, HF tokens, or any other secret in the preferences
  payload — `build_payload()` is secrets-free by construction and hard-codes
  `token_synced: false`
- Request/response bodies

## 2. The sync file: `~/.ollabridge/sync.yaml`

Written with mode `0o600`. Full example with all defaults:

```yaml
# OllaBridge cloud sync configuration.
# Metadata fields sync only while enabled: true.
# Sensitive fields (conversation_history, prompt_logging,
# provider_secrets_cloud_vault, rag_documents, persona_memory)
# are NEVER enabled automatically. See docs/CLOUD_SYNC.md.
cloud_sync:
  enabled: false                        # flips to true on `ollabridge login`

  # Safe metadata (on by default once sync is enabled)
  device_status: true
  model_metadata: true
  routing_profiles: true
  health_metrics: true

  # Sensitive — explicit opt-in only
  conversation_history: false
  prompt_logging: false
  provider_secrets_cloud_vault: false
  rag_documents: false
  persona_memory: false
```

### Defaults table

| Field | Class | Default | Effective behavior |
|---|---|---|---|
| `enabled` | master switch | `false` | Nothing syncs while false. Set to `true` by `ollabridge login`; back to `false` by `logout`/`sync disable`. |
| `device_status` | metadata | `true` | Syncs once enabled |
| `model_metadata` | metadata | `true` | Syncs once enabled |
| `routing_profiles` | metadata | `true` | Syncs once enabled |
| `health_metrics` | metadata | `true` | Syncs once enabled |
| `conversation_history` | **sensitive** | `false` | Never auto-enabled |
| `prompt_logging` | **sensitive** | `false` | Never auto-enabled |
| `provider_secrets_cloud_vault` | **sensitive** | `false` | Never auto-enabled; vault API also required |
| `rag_documents` | **sensitive** | `false` | Never auto-enabled |
| `persona_memory` | **sensitive** | `false` | Never auto-enabled |

A missing or unreadable `sync.yaml` always yields these safe defaults.

## 3. How login enables metadata sync

`ollabridge login` runs the TV-style device pairing flow
(`POST /device/start` → approve in browser → `POST /device/poll`), saves
credentials to `~/.ollabridge/cloud_device.json` (0600), and then — as an
explicit consequence of the login you initiated — sets `enabled: true` in
`sync.yaml`. **Sensitive flags are left untouched.** The post-login summary
shows you exactly what is on:

```
✅ Device paired: dev_a1b2c3
✅ Cloud API ready: https://api.ollabridge.com/v1
Credentials saved to /home/you/.ollabridge/cloud_device.json (0600)

Cloud sync (metadata only — change with `ollabridge sync`):
  ✅ device_status
  ✅ model_metadata
  ✅ routing_profiles
  ✅ health_metrics
  ❌ conversation_history  (sensitive — off by default)
  ❌ prompt_logging  (sensitive — off by default)
  ❌ provider_secrets_cloud_vault  (sensitive — off by default)
  ❌ rag_documents  (sensitive — off by default)
  ❌ persona_memory  (sensitive — off by default)
```

## 4. The `ollabridge sync` commands

### `ollabridge sync status` (add `--json` for automation)

```
$ ollabridge sync status
        Cloud sync — enabled
┌──────────────────────────────┬───────┬───────────┐
│ Category                     │ Syncs │ Class     │
├──────────────────────────────┼───────┼───────────┤
│ device_status                │ ✅    │ metadata  │
│ model_metadata               │ ✅    │ metadata  │
│ routing_profiles             │ ✅    │ metadata  │
│ health_metrics               │ ✅    │ metadata  │
│ conversation_history         │ ❌    │ sensitive │
│ prompt_logging               │ ❌    │ sensitive │
│ provider_secrets_cloud_vault │ ❌    │ sensitive │
│ rag_documents                │ ❌    │ sensitive │
│ persona_memory               │ ❌    │ sensitive │
└──────────────────────────────┴───────┴───────────┘
Config file: /home/you/.ollabridge/sync.yaml
```

If you are not paired it prints `Not paired with OllaBridge Cloud. Run:
ollabridge login` first; while disabled it adds `Nothing syncs while sync is
disabled.`

### `ollabridge sync enable`

```
$ ollabridge sync enable
✅ Cloud sync enabled (metadata only).
```

If any sensitive category was previously opted in, it warns in red:
`⚠ Sensitive categories are also enabled: …`.

### `ollabridge sync disable`

```
$ ollabridge sync disable
✅ Cloud sync disabled. Nothing will be sent to the cloud.
```

### `ollabridge sync config [field] [true|false]`

Show all settings (no args) or change one. Sensitive fields require an extra
interactive confirmation:

```
$ ollabridge sync config prompt_logging true
⚠ prompt_logging is sensitive — it will sync to the cloud only because you
explicitly enabled it.
Are you sure? [y/N]:
```

```
$ ollabridge sync config model_metadata false
✅ model_metadata = False
```

### `ollabridge sync push`

Push the current metadata snapshot now (requires pairing and `enabled: true`):

```
$ ollabridge sync push
✅ Pushed metadata snapshot to https://api.ollabridge.com
Stored at: 2026-06-10T09:14:02+00:00
```

### `ollabridge sync pull`

Read-only preview of what the cloud has stored for this device
(`GET /api/devices/me/preferences` with the device token). If the paired
cloud does not support pull yet, it says so and exits cleanly:

```
$ ollabridge sync pull
The paired cloud does not support preferences pull yet (or nothing has been pushed).
```

## 5. Turning everything off

Two levels, both immediate:

```bash
# Keep the pairing, stop all sync:
ollabridge sync disable

# Unpair entirely: deletes ~/.ollabridge/cloud_device.json and disables sync
ollabridge logout
```

`logout` reminds you that the device may still be listed in the cloud
dashboard — revoke it there to fully invalidate the (already-deleted) token
server-side. Local mode is unaffected either way.

## 6. What the metadata payload actually contains

`preferences_sync.build_payload()` builds the only thing `sync push` sends —
to `POST /api/devices/me/preferences` with the device token:

```json
{
  "device_id": "dev_a1b2c3",
  "synced_at": "2026-06-10T09:14:01.512Z",
  "schema_version": 1,
  "providers": [
    {"id": "openai", "name": "openai", "kind": "openai",
     "enabled": true, "tier": null, "category": null, "tags": []}
  ],
  "aliases": {
    "coding": [{"provider": "local", "model": "qwen2.5-coder:14b"}]
  },
  "hf_status": {
    "connected": true,
    "mode": "free_credit_only",
    "bill_to": null,
    "encrypted_at_rest": true,
    "catalog_entries": 12,
    "token_synced": false
  }
}
```

Notes:

- Provider entries are **names and kinds only** — fields are explicitly
  allow-listed; API keys are structurally absent.
- Aliases are `{provider, model}` name pairs only.
- `token_synced` is **hard-coded to `false`** in the source; the gateway
  never ships secrets through this path.
- The cloud uses the snapshot to display the device's routing setup in the
  admin UI and for alias fail-over when the device is offline.

## 7. Transport and server-side handling

- All sync traffic is HTTPS; the relay is WSS. The device authenticates with
  `Authorization: Bearer <device_token>`.
- The cloud **stores only an HMAC-SHA256 hash (with a server pepper) of
  device tokens** — the plaintext is returned once at pairing/enrollment and
  never persisted server-side (cloud repo: `DeviceToken` model).
- Locally the token lives in `~/.ollabridge/cloud_device.json` (0o600);
  `ollabridge doctor security` flags loose permissions.

To verify your actual sync posture at any time: `ollabridge doctor cloud`.
