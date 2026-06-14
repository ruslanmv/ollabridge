# Provider Keys (BYOK) — Storage, Rotation, and Guarantees

OllaBridge is **bring-your-own-key**: you supply credentials for the hosted
providers you already pay for, and the gateway routes to them under your
policies. With cloud pairing, this becomes **secure BYOK routing across your
authorized devices and workspaces** — your keys, usable where you authorize
them, governed by org policy.

Implementation references: `src/ollabridge/providers_meta.py` (catalog,
storage modes, `providers.yaml`), `src/ollabridge/provider_ops.py`
(operations, health checks), `src/ollabridge/cli/providers.py` (CLI),
`src/ollabridge/core/redact.py` (redaction).

---

## 1. Where keys live

| File | Contents | Protection |
|---|---|---|
| `~/.ollabridge/secrets.enc` | The actual API keys | **Fernet-encrypted** (HKDF-SHA256 key derived from `OLLA_SECRET`). If `OLLA_SECRET` is unset, falls back to **plaintext with mode 0o600** — the CLI warns loudly and `ollabridge doctor security` reports FAIL. |
| `~/.ollabridge/providers.yaml` | Metadata **only**: name, kind, storage mode, base URL, created/rotated timestamps, last health-test result | 0o600. The file header says it plainly: *SECRETS ARE NEVER STORED IN THIS FILE.* |

Set the encryption secret before adding keys:

```bash
export OLLA_SECRET="$(openssl rand -hex 32)"   # persist it in your shell profile
```

Environment variables (e.g. `OPENAI_API_KEY`) work as a **fallback** source:
the resolver checks the encrypted store first, then the provider's env var.

## 2. Storage modes — honest current behavior

When adding a key you choose one of three storage modes:

| Mode | Intent | Current behavior |
|---|---|---|
| `local_only` (1) | Safest; key never leaves this device | **Fully implemented.** |
| `cloud_encrypted_vault` (2) | Usable from your paired devices | **Records intent; key stays local.** Upload additionally requires: cloud pairing (`ollabridge login`), the explicit sync opt-in `provider_secrets_cloud_vault: true`, *and* a paired cloud that exposes its vault API. Until all three hold, the CLI tells you the key stays LOCAL-ONLY. Nothing is uploaded silently. |
| `organization_vault` (3) | Usable by your team according to org policy | Same as above; requires an org-enabled cloud. The cloud-side schema (envelope-encrypted `ProviderKey`, per-row DEK wrapped by a master KEK, last-4 display, rotation with audit history) is implemented in the `ollabridge-cloud` repo; the end-to-end push from the local CLI ships with the vault API (roadmap Phase 3). |

The `vault_synced` field in `providers.yaml` flips to `true` only after an
explicit, successful vault push — today it is always `false`.

## 3. Provider catalog

`ollabridge providers add <provider>` accepts any of these. Each has an env
var fallback and a key-prefix sanity check (warning only):

| Provider | Label | Env var fallback | Key prefix | Default base URL |
|---|---|---|---|---|
| `openai` | OpenAI | `OPENAI_API_KEY` | `sk-` | `https://api.openai.com/v1` |
| `anthropic` | Anthropic | `ANTHROPIC_API_KEY` | `sk-ant-` | `https://api.anthropic.com/v1` |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | `AIza` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `azure-openai` | Azure OpenAI | `AZURE_OPENAI_API_KEY` | — | *(required via `--base-url`)* |
| `bedrock` | AWS Bedrock | `AWS_BEARER_TOKEN_BEDROCK` | — | region-specific; IAM via AWS env also supported |
| `groq` | Groq | `GROQ_API_KEY` | `gsk_` | `https://api.groq.com/openai/v1` |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | `sk-or-` | `https://openrouter.ai/api/v1` |
| `huggingface` | Hugging Face | `HUGGINGFACE_API_KEY` | `hf_` | `https://router.huggingface.co/v1` |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` | `sk-` | `https://api.deepseek.com/v1` |
| `mistral` | Mistral | `MISTRAL_API_KEY` | — | `https://api.mistral.ai/v1` |
| `together` | Together AI | `TOGETHER_API_KEY` | — | `https://api.together.xyz/v1` |
| `fireworks` | Fireworks AI | `FIREWORKS_API_KEY` | — | `https://api.fireworks.ai/inference/v1` |
| `custom` | Generic OpenAI-compatible | `CUSTOM_LLM_API_KEY` | — | *(required via `--base-url`)* |

## 4. The `ollabridge providers` commands

### `add`

```
$ ollabridge providers add openai
Where should this provider secret live?

[1] Local only — safest, usable when this device is online
[2] Cloud encrypted vault — usable from your devices
[3] Organization vault — usable by your team according to policy

Choice [1]: 1
OpenAI API key: ********
✅ OpenAI key stored (encrypted at rest) as sk-p…(redacted)
Test it:  ollabridge providers test openai
```

Flags: `--api-key` (omit to be prompted with hidden input), `--storage 1|2|3`
or the mode name, `--base-url` (required for `azure-openai` and `custom`).
If `OLLA_SECRET` is unset you get
`(plaintext 0o600 — set OLLA_SECRET!)` plus a warning to set it and re-add.
For modes 2/3, a vault notice explains exactly why the key currently stays
local (not paired / opt-in disabled / cloud vault API not available).

### `list`

```
$ ollabridge providers list
                       BYOK providers
┌───────────┬───────────┬────────────┬──────────────────┬────────────────────────────┐
│ Provider  │ Kind      │ Storage    │ Key              │ Last test                  │
├───────────┼───────────┼────────────┼──────────────────┼────────────────────────────┤
│ anthropic │ anthropic │ local_only │ sk-a…(redacted)  │ ✅ 2026-06-10T08:41:12+00:00│
│ openai    │ openai    │ local_only │ sk-p…(redacted)  │ ✅ 2026-06-10T08:40:55+00:00│
└───────────┴───────────┴────────────┴──────────────────┴────────────────────────────┘
```

`--json` emits the redacted export (same as `export --redacted`).

### `test`

```
$ ollabridge providers test openai
✅ openai: key valid, https://api.openai.com/v1 reachable
$ ollabridge providers test groq
❌ groq: key rejected (HTTP 401)
```

### `rotate`

```
$ ollabridge providers rotate openai
New openai API key: ********
✅ Rotated openai key (sk-p…(redacted)), rotated_at=2026-06-10T09:02:31+00:00
✅ post-rotation test: key valid, https://api.openai.com/v1 reachable
```

### `remove`

```
$ ollabridge providers remove groq
Remove provider 'groq' and delete its key? [y/N]: y
✅ Removed groq (key deleted: True).
```

(`--yes`/`-y` skips the confirmation for scripting.)

### `status`

```
$ ollabridge providers status
Configured providers: anthropic, openai
Encrypted at rest: ✅ yes
Secret store: /home/you/.ollabridge/secrets.enc
```

### `export --redacted`

Exports are **always** redacted; the flag exists so you acknowledge that:

```
$ ollabridge providers export --redacted
{
  "providers": [
    {
      "name": "openai", "kind": "openai", "storage_mode": "local_only",
      "base_url": "https://api.openai.com/v1",
      "created_at": "2026-06-09T17:20:11+00:00",
      "rotated_at": "2026-06-10T09:02:31+00:00",
      "last_test_ok": true, "last_test_at": "2026-06-10T09:02:33+00:00",
      "vault_synced": false,
      "key": "sk-p…(redacted)", "key_configured": true
    }
  ],
  "note": "keys are redacted; full keys are never exported"
}
```

Running `export` without `--redacted` refuses and explains.

## 5. Health checks — what `test` actually does

`test_provider()` calls the provider's **model-listing endpoint**
(`GET <base_url>/models`; Anthropic uses its `x-api-key` +
`anthropic-version` header convention). This validates reachability *and*
the key with:

- **no prompt content** — no completion is requested;
- **no token cost** — list-models is free on all supported providers.

Failures map to actionable messages: 401/403 → key rejected, 429 → rate
limited / quota exhausted, 402 → quota or billing failure, timeouts and other
errors are reported with the body **passed through the redactor** first. The
outcome stamps `last_test_ok` / `last_test_at` in `providers.yaml`.

`ollabridge doctor providers` summarizes the same picture across all
providers; add `--probe` to run the health check for each configured one.

## 6. Key rotation guidance

1. Mint the new key in the provider console (keep the old one active).
2. `ollabridge providers rotate <provider>` — paste the new key at the hidden
   prompt; the post-rotation health check runs immediately.
3. Confirm `✅ post-rotation test`, then revoke the old key upstream.
4. Verify routing still resolves: `ollabridge route explain best`.

Rotation timestamps live in `providers.yaml`, so
`ollabridge providers export --redacted` doubles as a rotation-age report
for compliance reviews. Suggested cadence: 90 days, or immediately on
suspicion of exposure.

## 7. Redaction guarantees

- Full keys are never printed, logged, or exported by any `providers`,
  `doctor`, or `traces` command. Display uses `redact_secret()` — a 4-char
  hint plus `…(redacted)` (e.g. `sk-p…(redacted)`).
- Free-form error text (provider error bodies, exception messages) passes
  through `redact_text()`, which scrubs every known credential shape:
  `sk-*`, `sk-ant-*`, `sk-or-*`, `sk-proj-*`, `hf_*`, `gsk_*`, `AIza*`,
  `AKIA*`, OllaBridge tokens (`dvt_*`, `obt_*`, `ob_*`,
  `sk-ollabridge-*`), and `Bearer`/`X-API-Key` header values.
- A `RedactionFilter` can be attached to any logger so future code cannot
  accidentally log a key.
- The cloud sync payload is allow-listed and structurally key-free
  (`token_synced: false` always — see `docs/CLOUD_SYNC.md`).

One-line audit of your secret posture: `ollabridge doctor security`.
