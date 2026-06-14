# Privacy

OllaBridge is local-first by design. `ollabridge start` requires no account,
no login, and sends nothing anywhere except to the backends you configure
(local Ollama by default). Cloud connectivity is optional, explicit, and
metadata-only unless you opt in to more.

This document describes what actually happens in the code — see
`src/ollabridge/cloud/sync_config.py`, `src/ollabridge/tracing/store.py`,
and `src/ollabridge/core/paths.py` for the implementation.

---

## What stays local

The following never leaves your machine (unless you explicitly route a
request to a hosted provider or opt in to a sensitive sync category):

| Data | Where it lives | Notes |
|---|---|---|
| Prompts and responses | In memory only, per request | Not written to any local database; not synced |
| Provider API keys | `~/.ollabridge/secrets.enc` | Fernet-encrypted when `OLLA_SECRET` is set; never synced by default (`provider_secrets_cloud_vault: false`) |
| RAG documents | Local | Sync category `rag_documents` defaults to `false` |
| Persona memory | Local | Sync category `persona_memory` defaults to `false` |
| Request traces | `~/.ollabridge/traces.db` | Metadata only — **no prompt or response content is ever written** |
| Request logs | `~/.ollabridge/ollabridge.sqlite` | Path, model, latency, ok, client — no prompt content |
| Local audit trail | `~/.ollabridge/audit.log` | Local file |
| Pairing tokens | `~/.ollabridge/pair_tokens.json` | SHA-256 hashes only |
| Cloud device credentials | `~/.ollabridge/cloud_device.json` | `0o600`; used only to authenticate the outbound relay |

Caveat: when you configure a hosted provider (OpenAI, Anthropic, Groq, …)
and a request routes to it, the prompt content goes to that provider — that
is the point of routing. The trace records *that* it happened
(provider, model, tokens, latency), not what was said.

## What syncs after login — metadata only

Nothing syncs until you run `ollabridge login` (TV-style device pairing) and
sync is enabled (`enabled: true` in `~/.ollabridge/sync.yaml`). Even then,
only safe **metadata** categories sync, each individually toggleable:

| Category | Default (once sync enabled) | Content |
|---|---|---|
| `device_status` | on | Device online/offline state |
| `model_metadata` | on | Model names/capabilities the device shares |
| `routing_profiles` | on | Routing/alias configuration |
| `health_metrics` | on | Latency/health numbers — no prompt content |

The relay bridge also registers your local model names with the cloud
(`hello` frame) so cloud-routed requests can find your device.

## Optional, explicit opt-in only

Five sensitive categories exist in `sync.yaml`. **All default to `false`,
and there is no code path that enables them automatically:**

| Category | Default | What enabling would mean |
|---|---|---|
| `conversation_history` | `false` | Conversation content stored/synced |
| `prompt_logging` | `false` | Prompt content may be logged |
| `provider_secrets_cloud_vault` | `false` | Provider keys stored in a cloud vault |
| `rag_documents` | `false` | RAG document sync |
| `persona_memory` | `false` | Persona memory sync |

Enable/inspect them only via explicit commands:

```bash
ollabridge sync status                       # shows every flag, sensitive ones marked
ollabridge sync config prompt_logging true   # explicit opt-in (not recommended)
```

`ollabridge doctor cloud` and `ollabridge doctor security` warn when any
sensitive category is enabled.

## Prompt logging defaults

Prompt logging is **off by default**, in two layers:

- `prompt_logging: false` in `~/.ollabridge/sync.yaml` (never auto-enabled).
- Every trace record carries a `prompt_logging` flag (default `false`);
  the trace store schema has no column for prompt or response text, so even
  a bug elsewhere could not persist content into `traces.db`.

## Data retention

- Traces are kept locally in SQLite (`~/.ollabridge/traces.db`) until pruned.
  Inspect with:

  ```bash
  ollabridge traces list
  ollabridge traces show <request_id>
  ```

- The trace store supports pruning to the newest N records
  (`TraceStore.prune(keep=10000)`); deleting `~/.ollabridge/traces.db` is
  always safe — it is recreated empty on next start.
- Request logs live in `~/.ollabridge/ollabridge.sqlite` with the same
  metadata-only property.
- There is no automatic time-based retention/expiry — retention is whatever
  you keep on disk.

## How to delete your data

Local data:

```bash
ollabridge logout                 # disconnects the relay and removes cloud credentials
rm ~/.ollabridge/traces.db        # request traces
rm ~/.ollabridge/ollabridge.sqlite
rm ~/.ollabridge/audit.log
rm ~/.ollabridge/secrets.enc      # provider keys (you will need to re-add them)
rm ~/.ollabridge/sync.yaml ~/.ollabridge/policies.yaml ~/.ollabridge/providers.yaml
# or remove everything:
rm -rf ~/.ollabridge
```

Cloud data: after `ollabridge logout`, also **revoke the device in the
OllaBridge Cloud dashboard** so the device token is invalidated server-side
and any synced metadata is detached from your account.

## Local vs. cloud modes

| Aspect | Local only (no login) | Logged in (sync enabled) |
|---|---|---|
| Account required | No | Yes (TV-style pairing) |
| Network connections | Your configured backends only (Ollama / providers) | Plus one **outbound** WSS to OllaBridge Cloud |
| Inbound ports for cloud | None | None — relay is outbound-only |
| Prompts/responses leave machine | Only to providers you route to | Same; relay forwards request payloads to *your* device for execution, content is not stored by default |
| Device status / model names in cloud | No | Yes (metadata) |
| Provider keys in cloud | No | No, unless `provider_secrets_cloud_vault: true` (default false) |
| Conversation history in cloud | No | No, unless explicitly opted in (default false) |
| Telemetry / phone-home | None found in the codebase | Only the sync categories you enabled |

## How to verify

Don't take this document's word for it:

```bash
ollabridge sync status            # every sync flag, with sensitive ones highlighted
ollabridge doctor security        # prompt logging, secrets-at-rest, permissions, auth posture
ollabridge doctor cloud           # whether you're paired, what sync state is
ollabridge traces show <id>       # see exactly what a trace contains (no content fields)
cat ~/.ollabridge/sync.yaml       # the consent file itself, human-readable YAML
```

You can also inspect `traces.db` directly with any SQLite client — the
schema contains only routing metadata columns.
