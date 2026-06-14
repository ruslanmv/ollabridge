# External Sources Hub — design & API

The "Providers Hub" is being refactored from a Hugging-Face-catalog page into a
**local External Sources Manager**: the place where a user adds their own AI
accounts and endpoints (OpenAI, Claude, Gemini, Hugging Face, OpenRouter, Groq,
DeepSeek, Mistral, Together, Fireworks, local Ollama, custom endpoints), saves
keys locally, tests them, and decides — explicitly — what may be shared or used
for routing.

> OllaBridge is the user-controlled local control plane for AI sources.
> Configure once; apps connect once; OllaBridge only acts within the
> permissions the user explicitly set.

## Core principles (non-negotiable)

1. **Show what the user actually configured.** No fake providers, no fake
   usage, no hardcoded route aliases presented as if they were the user's setup.
2. **Safe by default.** A new source is **local-only, private, routing OFF**.
3. **Secrets stay local.** Keys live in `~/.ollabridge/secrets.enc`; only
   metadata may sync, and only on explicit opt-in. Keys are never shown after
   saving — only a redacted hint (`sk-…(redacted)`).
4. **Routing is optional & advanced.** Off until the user enables it.

## Terminology

| Term | Meaning |
|---|---|
| **Source** | An account, endpoint, or local runtime that can serve models |
| **Provider** | The company/protocol behind a source (OpenAI, Anthropic, …) |
| **Model** | A specific model served by a source |
| **Routing profile** | Rules for choosing among sources/models (opt-in) |

## Navigation

```
OllaBridge Hub
  Sources · Routing · Models · Usage · Cloud Sync
```

- **Sources** — add/manage accounts & endpoints (the main tab)
- **Routing** — optional rules; disabled by default
- **Models** — real models from configured sources
- **Usage** — real telemetry only; empty state when none
- **Cloud Sync** — metadata sync (default) vs encrypted vault (opt-in)

The HF catalog discovery becomes an *advanced section inside the Hugging Face
source card* — it no longer dominates the hub.

## Sources tab

```
┌─ External Sources ───────────────────────────────────────────────────┐
│  1 of 13 connected · 5 models                       [ + Add Source ]  │
│                                                                       │
│  ┌─ OpenAI ───────────── ● Connected ─┐  ┌─ Claude ──── ⚠ Missing key┐│
│  │ Personal OpenAI                     │  │ Anthropic / Claude        ││
│  │ Model: gpt-4o-mini  Local · Private │  │ [ Add API key ]           ││
│  │ Routing: Off   Last test: OK        │  └───────────────────────────┘│
│  │ Key: sk-…(redacted)                 │  ┌─ Ollama Local ─ ● Connected┐│
│  │ [Configure] [Test] [Rotate] [Remove]│  │ 5 models · This PC · Route ││
│  └─────────────────────────────────────┘  └───────────────────────────┘│
└───────────────────────────────────────────────────────────────────────┘
```

Each card shows: display name, provider, **status** (`Connected · Missing key ·
Error · Disabled`), default model, **storage** (Local / Cloud metadata / Vault),
**sharing** (Private / Account / Workspace / Org), **routing** (On/Off), last
test. Actions: Configure · Test · Rotate key · Enable/Disable · Remove.

### Add / Configure modal

```
Provider        [ OpenAI ▾ ]
Display name    [ Personal OpenAI            ]
API key         [ •••••••••••••••••• ] [Show]   (write-only; hidden after save)
Base URL        [ https://api.openai.com/v1 ]
Default model   [ gpt-4o-mini               ]
Storage mode    (●) Local only  ( ) Sync metadata  ( ) Encrypted vault
Sharing         (●) Private  ( ) Account  ( ) Workspace  ( ) Org
Routing         [ ] Allow this source in routing
                                              [ Cancel ]  [ Save & Test ]
```

Defaults are pre-selected to the safe values. After **Save & Test**:
`✓ Key accepted · ✓ Reachable` (or the exact error), and the key field is
cleared — only the redacted hint shows thereafter.

## Routing tab (opt-in)

```
Routing status: Disabled            [ Enable Routing ]

When disabled, requests use the source/model the caller selected.
When enabled, OllaBridge may choose among sources you marked "Allow routing",
following the active profile.
```

Profiles (user-defined, not hardcoded aliases): `private-local`, `cheap-cloud`,
`best-quality`, `coding`, custom. Each: name, description, allowed sources,
priority order, fallback on/off, cost/latency preference, cloud-allowed,
local-only. Empty state: *"Add at least one source before enabling routing."*

This maps onto the existing policy engine (`ollabridge route explain`,
`docs/ROADMAP_ENTERPRISE.md`).

## Usage & Cloud Sync

- **Usage:** real requests/latency/failures/cost per configured source from the
  trace store + flow metrics. No data → *"Send a request through a configured
  source to see usage."* Never fabricate cards.
- **Cloud Sync:** two clearly separated levels — metadata sync (names, enabled
  state, default models, routing profiles; **never keys**) and encrypted vault
  sync (keys, explicit opt-in, off by default). See `docs/CLOUD_SYNC.md`.

## Backend — `/admin/sources/*` (implemented)

| Method · Path | Purpose |
|---|---|
| `GET /admin/sources` | `{configured[], available[]}` — cards + add-catalog |
| `GET /admin/sources/{name}` | One source (redacted) |
| `POST /admin/sources/{name}` | Add/update; saves key encrypted, tests it |
| `POST /admin/sources/{name}/test` | Validate key (models probe, no token cost) |
| `POST /admin/sources/{name}/rotate` | Replace key, restamp |
| `DELETE /admin/sources/{name}` | Remove source + delete key |

Response shape per source:

```json
{
  "name": "openai", "kind": "openai", "label": "OpenAI",
  "display_name": "Personal OpenAI", "base_url": "https://api.openai.com/v1",
  "default_model": "gpt-4o-mini", "enabled": true,
  "allow_routing": false, "sharing": "private", "storage_mode": "local_only",
  "status": "connected", "key": "sk-…(redacted)", "key_configured": true,
  "last_test_ok": true, "last_test_at": "…", "rotated_at": null
}
```

Storage: metadata in `~/.ollabridge/providers.yaml` (never secrets); keys in
`~/.ollabridge/secrets.enc` (Fernet when `OLLA_SECRET` set). Same data the
`ollabridge providers` CLI manages.

## What to remove / hide

- The HF-only Connect tab (HF becomes one source among many; catalog discovery
  moves inside its card).
- Hardcoded route aliases shown as the user's routes.
- Fabricated Usage cards / `UNKNOWN` provider fleet.
