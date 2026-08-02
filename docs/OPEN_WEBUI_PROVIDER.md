# Open WebUI-compatible provider (generic)

OllaBridge can use any **Open WebUI-compatible** server as an upstream LLM
provider. The integration is generic and vendor-neutral: there is no product
name or hard-coded host anywhere in the code — you point it at a server's `/api`
root and OllaBridge discovers and serves its models through the standard local
OpenAI-compatible gateway.

```text
Client (HomePilot persona / agent / any OpenAI client)
        │  OpenAI-compatible API, model: <prefix>/<remote-model-id>
        ▼
Local OllaBridge :11435/v1        ← the upstream key lives ONLY here
        │
        ├── GET  {base}/v1/models   (falls back to {base}/models)
        └── POST {base}/v1/chat/completions   (falls back to {base}/chat/completions)
        ▼
Open WebUI-compatible server
```

The client authenticates only to its local OllaBridge; OllaBridge authenticates
to the upstream. The upstream key never leaves the machine.

## Why a dedicated adapter

The stock generic OpenAI-compatible adapter builds `{base_url}/v1/...`. Open
WebUI serves its OpenAI-compat surface under an `/api` prefix
(`/api/v1/models`, `/api/v1/chat/completions`), so the stock adapter only works
if the operator happens to set `base_url` to `<host>/api`. The dedicated
`OpenWebUIAdapter` removes that guesswork and adds behavior the generic adapter
must not carry (so Groq/DeepSeek/OpenRouter/custom cannot regress):

- **Preferred + fallback path negotiation** — tries `/v1/models` then `/models`
  (and the chat equivalents), remembering which answered.
- **Model namespacing** — upstream ids are exposed locally as `<prefix>/<id>`
  (default prefix `openwebui`) so they never collide with local Ollama or other
  providers, and the prefix is stripped before the upstream call.
- **Full-response preservation** — tool calls, `finish_reason`, `usage`, and
  structured output pass through unchanged; only the top-level `model` is
  re-labelled to the namespaced id the caller asked for.
- **Honest error mapping** — upstream status → OllaBridge `Provider*` errors so
  the router can retry / fail-over / abort correctly.
- **Credential redaction** — the key never appears in errors, logs, or the model
  cache; discovery on `401/403` never surfaces stale models.
- **Optional `x-api-key` transport** — for servers configured with a custom
  API-key header instead of `Authorization: Bearer`.
- **Fail-closed** — an explicit namespaced model errors rather than silently
  rerouting to a different provider.

Capabilities that cannot be known from the model list stay `null` — they are
never inferred from a model name.

## Configuration (additive, private by default)

Add a provider record of `kind: open_webui`. Like every BYOK source it defaults
to **local-only, private, and excluded from automatic routing** until you opt
in. The record carries only metadata; the key is stored in the encrypted
`SecretStore`.

`ProviderConfig` gained these optional fields (defaults preserve every existing
provider exactly):

| Field | Default | Purpose |
|---|---|---|
| `models_path` | `/v1/models` | Preferred model-listing path. |
| `chat_path` | `/v1/chat/completions` | Preferred chat path. |
| `fallback_models_path` | `/models` (for this kind) | Tried on a 404. |
| `fallback_chat_path` | `/chat/completions` (for this kind) | Tried on a 404. |
| `model_prefix` | `openwebui` | Local namespace; set a distinct value per instance to isolate two servers. |
| `auth_header` | `authorization` | `authorization` (Bearer) or `x-api-key`. |
| `fail_closed` | `false` (`true` for this adapter) | Explicit model errors instead of rerouting. |
| `dynamic_models` | `false` | Discover models at runtime. |

`base_url` is the server's `/api` root, e.g. `https://<host>/api`. The adapter
appends the version paths, so it reaches `https://<host>/api/v1/models` and
`https://<host>/api/v1/chat/completions`, with the legacy non-`/v1` paths as
fallback.

## Authentication (optional, non-interactive)

Open WebUI's API authenticates a request in this order: `Authorization` header →
login session cookie → a configured API-key header. A headless gateway is not a
browser, so it uses a **machine credential**, never an interactive login. The
adapter supports three non-interactive `auth_strategy` values:

| `auth_strategy` | Credential (the stored secret is…) | When to use |
|---|---|---|
| `api_key` *(default)* | a long-lived API key (`sk-…`) | Recommended. Created once by a human in Open WebUI; resolves to that user and inherits their role, groups, and model access. Sent as `Authorization: Bearer` (or `x-api-key`). |
| `bearer` | a static, externally-minted access token / JWT | When your platform already issues IdP tokens out-of-band. OllaBridge sends it as-is and does **not** manage its lifecycle. |
| `oauth2_client_credentials` | an OAuth2 **client secret** | Machine-to-machine SSO. OllaBridge mints a short-lived token from the IdP's token endpoint (`grant_type=client_credentials`), caches it with an expiry skew, refreshes automatically, and drops the cache on a resource-side 401. Works with any OIDC/OAuth2 IdP. |

Config fields (all optional; defaults keep `api_key` behavior):
`auth_strategy`, `token_url`, `client_id`, `oauth_scope`, `oauth_audience`. The
client secret is stored like any provider key (encrypted `SecretStore`), never
in config or logs.

### What OllaBridge deliberately does NOT do

An interactive **authorization-code** login — the "Sign in / Continue with
<IdP>" browser flow, e.g. an authorize URL like
`…/oauth2/v1/authorize?response_type=code&scope=openid…&redirect_uri=…/oauth/oidc/callback`
— is a **human, in a browser**, and its product is a session, not a machine
credential. A headless provider adapter never drives it, never stores a user
password, and never screen-scrapes a session cookie. The supported path is: a
human signs in that way *in Open WebUI*, creates an `sk-` API key, and stores
that key in OllaBridge (`auth_strategy: api_key`). Organizations that require
short-lived, auto-rotating, IdP-issued credentials use
`oauth2_client_credentials` with a service account instead.

Security invariants for every strategy: HTTPS + TLS verification for non-local
servers; the client secret and any minted token are redacted from errors and
never written to the model cache; a resource-side `401/403` invalidates a cached
OAuth token and fails closed rather than replaying a dead one.

## Upstream requirements

The upstream administrator must enable API keys and permit at least the model
and chat endpoints for the key's user (and, if endpoint restrictions are on,
allow both the `/v1` and legacy paths). API keys are resolved to a user, so the
models OllaBridge sees are exactly the models that user may access — never a
global or guessed catalog.

## Model naming

A local `/v1/models` entry looks like:

```json
{
  "id": "openwebui/qwen3-coder",
  "object": "model",
  "owned_by": "openwebui",
  "name": "Qwen 3 Coder",
  "upstream_model_id": "qwen3-coder",
  "status": "available",
  "stale": false,
  "capabilities": {"chat": true, "tools": null, "vision": null, "image_generation": null, "structured_output": null}
}
```

A request for `openwebui/qwen3-coder` is sent upstream as `qwen3-coder`.

## Catalog metadata, classification, and filtering

The models returned are exactly those the API key's user may access — Open WebUI
aggregates local Ollama, external providers, OpenAI-compatible endpoints,
function/pipe models, presets, and (when enabled) arena models, then applies the
user's permissions. Being *listed* does not mean an entry is a normal chat LLM
(a tag like `image` may be an image pipe; a preset may be a workflow), so the
adapter preserves the upstream catalog metadata and classifies each entry:

- **Preserved per model:** `connection_type` (drives the Local/External views),
  `tags` (normalized to `[{"name": …}]` whether the server sends objects or bare
  strings), `description`/`hidden` from `info.meta`, `preset`, `pipe`,
  `action_count`, `filter_count`, and `upstream_owned_by`.
- **`capabilities`** are read ONLY from the upstream `info.meta.capabilities`
  (vision / image_generation / tools / structured_output). They are never
  inferred from a model name. `chat` is set to `true` only for a plain model
  entry (no `pipe`, not a `preset`); pipes/presets/image-only entries leave
  `chat` null.
- **`category`** is a coarse persona-safety class:
  `chat | tools | vision | image_generation | preset_or_workflow | unknown`,
  and **`persona_compatible`** is `true` only when `chat` is confirmed.

`OpenWebUIAdapter.filter_models(models, connection_type=…, tag=…, category=…,
persona_compatible=…)` is a pure helper that reproduces every view over the
normalized list — so the dashboard, the gateway, and a persona picker filter the
identical catalog:

```text
All  ·  Local (connection_type=local)  ·  External (connection_type=external)
Tags: image / internal / … (tag=<name>)
Persona-compatible: persona_compatible=true   ← excludes image pipes & workflows
```

A persona LLM selector should offer only `persona_compatible` models by default
and keep the rest under an "Advanced / other models" section, so a persona can
never accidentally pick an image-only pipe or a non-chat internal workflow.

## Security

- The upstream key is encrypted at rest and redacted from logs, errors, exports,
  and the model cache.
- Discovery fails closed on auth errors (never shows stale models as available).
- Namespaced models are private to this device until explicitly shared.
- Use HTTPS for non-local servers; a remote provider means prompts leave the
  machine — surface that clearly in any UI.

## Live discovery + serving

Saving a source registers its adapter in the live registry, so its models are
both listed in `/v1/models` and servable via `/v1/chat/completions`. Browse and
filter the key's models at `GET /admin/sources/{name}/models` (`?connection_type=`,
`?tag=`, `?category=`, `?persona_compatible=`, `?search=`); the connect modal
shows the Local / External / persona-compatible discovery counts.

## Scope of this change

This is the reviewable first unit: the adapter, the generic catalog entry, the
optional config fields, seeder registration, and unit/seeding tests — all
additive. Streaming, richer tool-forwarding at the gateway edge, dynamic-sync
triggers, and UI affordances are independent additive follow-ups; with no
`open_webui` record configured, OllaBridge behaves exactly as before.
