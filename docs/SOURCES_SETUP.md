# Setting up AI sources — step-by-step examples

This page walks through connecting each kind of AI source from the dashboard,
one worked example per provider. It complements
[Provider Keys (BYOK)](PROVIDER_KEYS.md) (where keys live, CLI commands,
rotation) and [Open WebUI provider](OPEN_WEBUI_PROVIDER.md) (adapter
internals). Nothing here requires the CLI: everything is done in the UI, with
the equivalent API call shown at the end.

OllaBridge knows two families of sources:

| Family | Where in the dashboard | Examples |
|---|---|---|
| **Local runtimes** — hardware you run | **Runtimes** page | Ollama, HomePilot |
| **External sources** — accounts and endpoints you own | **Sources** page → **Add Source** | Open WebUI, OpenAI-compatible gateways, OpenAI, Gemini, Groq, OpenRouter, Hugging Face, DeepSeek, Mistral, Together, Fireworks, Azure OpenAI, AWS Bedrock, IBM watsonx.ai |

Every new external source starts **local-only, private, routing-off**. Keys
are stored on this machine (encrypted when `OLLA_SECRET` is set, see
[Provider Keys](PROVIDER_KEYS.md#1-where-keys-live)), redacted everywhere
after saving, and never synced unless you opt in.

---

## 1. The add-source form, field by field

Open **Sources → Add Source**, pick a provider, and the same form appears for
all of them. Only the hints and the required fields differ.

| Field | What to enter | Notes |
|---|---|---|
| **Provider** | Pre-selected from the catalog | Fixed after creation. One record per provider kind. |
| **Display name** | Any label, e.g. `BlueChat`, `Work OpenAI` | Cosmetic. Shown on the card and as `owned_by` for models the source serves. |
| **API key** | The provider credential | Write-only. After saving only a redacted hint (`sk-4…`) is shown. |
| **Server / Base URL** | The API root | Pre-filled for hosted providers. **Required** for Open WebUI, Generic OpenAI-compatible and Azure OpenAI. A trailing slash is fine. |
| **Default model** | A model id this source should answer with | Leave blank on providers that support discovery and the best reachable chat model is picked. Required for a Generic OpenAI-compatible source to serve anything. |
| **Storage mode** | `Local only` / `Encrypted vault` / `Org vault` | `Local only` is the safe default and the only mode that is fully active today; the vault modes record intent and keep the key local until cloud pairing and the explicit opt-in are both in place. |
| **Sharing** | `Private` / `Account` / `Workspace` / `Org` | Who may see this source's models once published. Start with `Private`. |
| **Allow routing** | Checkbox, off by default | When on, routing profiles may pick this source. For most non-discovery providers this switch is also what registers the source as a runtime, see §3. |

The primary button is **Connect and discover** (providers that can list their
models) or **Save & Test**. Saving always probes the provider's model-list
endpoint with your key: it validates the key and reachability and costs no
tokens. The result is stamped on the card as **Connected** or an exact error.

### Status badges

| Badge | Meaning |
|---|---|
| **Connected** | Key present, last test passed, required config present, source enabled. |
| **Error** | Last test failed (`key rejected (HTTP 401)`, timeout, …). Fix the key or URL and save again. |
| **Missing key** / **Missing config** | No key stored, or a required extra field (e.g. watsonx Project ID) is empty. |
| **Disabled** | You switched the source off. Its models are not served. |

**Connected means the key and the model list work.** It does not run a chat.
After connecting, send one request through the gateway (§4) to confirm the
source really answers.

---

## 2. Worked examples

### 2.1 Open WebUI (compatible) — e.g. a company BlueChat server

Any Open WebUI server (self-hosted or company-run) can be a source. The
example below is a team.blue BlueChat instance; replace the host with yours.

1. In Open WebUI: **Settings → Account → API keys → Create new key**. Copy the `sk-…` key.
2. In OllaBridge: **Sources → Add Source → Open WebUI (compatible)**.
3. **Provider**: leave as `Open WebUI (compatible)`.
4. **Display name**: anything you like, for example `BlueChat`. It is only a label.
5. **API key**: paste the key. It stays on this machine and is only ever sent to that server.
6. **Server URL**: the server's `/api` root, e.g. `https://chat.ai.team.blue/api`. A trailing slash is fine, the adapter strips it.
7. **Default model**: leave blank, or type the upstream id you want, e.g. `internal-gemma4-31b`. Blank lets discovery pick a plain chat model; typing it pins the choice.
8. **Storage mode**: `Local only`.
9. Click **Connect and discover**. The save lists the models your key may use and shows a discovery summary (for the example server: 54 models, split into plain chat models, `ext-*` gateway presets and workspace presets).

What you get:

- Models are namespaced `openwebui/<upstream-id>` so they never collide with
  local Ollama or other providers, e.g. `openwebui/internal-gemma4-31b`.
  OllaBridge strips the prefix before calling the server.
- The list is exactly what *your* Open WebUI user may access: plain models,
  presets and pipes alike. Presets and workflows are tagged
  `preset_or_workflow` and are not offered as default chat models.
- Explicit requests to an `openwebui/...` id are served as soon as the source
  is **Connected**; **Allow routing** only controls automatic selection.
- Only one Open WebUI source can exist per OllaBridge (the namespace prefix is fixed).

### 2.2 Generic OpenAI-compatible — e.g. a company inference gateway

Use this for vLLM, LiteLLM, llama.cpp server, text-generation-inference, or
any internal gateway that speaks `/v1/chat/completions`.

1. **Sources → Add Source → Generic OpenAI-compatible**.
2. **Display name**: e.g. `BlueCode`.
3. **API key**: the gateway's key.
4. **Base URL**: the OpenAI root *including* `/v1`, e.g. `https://inference.example.com/v1`.
   The test probes `<base>/models`, so `https://inference.example.com/v1/models` must answer.
5. **Default model**: the exact model id the gateway serves, e.g. `Gemma-4-31B`. **Required**: this is the model OllaBridge exposes for the source.
6. **Storage mode**: `Local only`. Click **Save & Test**.
7. Tick **Allow routing** and keep the source **Enabled**. For this kind the source is registered as a runtime only when it is enabled, has a key, has a default model **and** routing is on. With routing off it shows **Connected** but serves nothing.

Clients then call the model by its plain id (`Gemma-4-31B`); it appears in
`/v1/models` with `owned_by` set to the display name.

### 2.3 OpenAI

1. Create a key at platform.openai.com → **API keys** (`sk-…`).
2. **Add Source → OpenAI**. Base URL is pre-filled (`https://api.openai.com/v1`).
3. **Default model**: e.g. `gpt-4o-mini`. **Save & Test**.
4. Tick **Allow routing** to serve the model through the gateway (same rule as §2.2).

### 2.4 Google Gemini

1. Create a key in Google AI Studio (`AIza…`).
2. **Add Source → Google Gemini**. The pre-filled base URL is Gemini's OpenAI-compatible endpoint
   (`https://generativelanguage.googleapis.com/v1beta/openai`).
3. **Default model**: leave blank or use a free-tier id such as `gemini-2.5-flash`. **Connect and discover**.

Gemini is one of the *seeded* providers (with Groq, OpenRouter, Hugging Face,
DeepSeek): the dashboard key is pushed into the built-in provider, so model
aliases such as `fast`, `cheap` and `best` can resolve to it without any
further switch.

### 2.5 Groq

1. Key from console.groq.com → **API Keys** (`gsk_…`).
2. **Add Source → Groq**. Base URL `https://api.groq.com/openai/v1` (a bare `https://api.groq.com` also works).
3. **Default model**: blank, or a free one such as `openai/gpt-oss-20b`. **Connect and discover**.

### 2.6 OpenRouter

1. Key from openrouter.ai/keys (`sk-or-…`).
2. **Add Source → OpenRouter**. Base URL `https://openrouter.ai/api/v1`.
3. **Default model**: ids ending in `:free` cost nothing, e.g. `meta-llama/llama-3.3-70b-instruct:free`. **Connect and discover**.

### 2.7 Hugging Face (Inference Providers)

1. Token from huggingface.co → **Settings → Access Tokens** (`hf_…`).
2. **Add Source → Hugging Face**. Base URL `https://router.huggingface.co/v1`.
3. **Default model**: blank, or e.g. `meta-llama/Llama-3.3-70B-Instruct`. **Connect and discover**. Uses your monthly HF credits.

### 2.8 DeepSeek

1. Key from platform.deepseek.com (`sk-…`).
2. **Add Source → DeepSeek**. Base URL `https://api.deepseek.com/v1`.
3. **Default model**: `deepseek-chat` (or `deepseek-reasoner`). **Connect and discover**.

### 2.9 Mistral, Together AI, Fireworks AI

All three are plain OpenAI-compatible hosted APIs. Add the source, paste the
key, keep the pre-filled base URL, type a default model, **Save & Test**, then
tick **Allow routing** (rule from §2.2).

| Provider | Base URL (pre-filled) | Default model example |
|---|---|---|
| Mistral | `https://api.mistral.ai/v1` | `mistral-small-latest` |
| Together AI | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Fireworks AI | `https://api.fireworks.ai/inference/v1` | `accounts/fireworks/models/llama-v3p3-70b-instruct` |

### 2.10 Azure OpenAI

1. In the Azure portal copy a key from your Azure OpenAI resource.
2. **Add Source → Azure OpenAI**. **Base URL is required**: `https://<resource>.openai.azure.com`.
3. **Default model**: your *deployment* name. **Save & Test**.

Serving goes through the generic OpenAI-compatible adapter, so it works where
the resource exposes an OpenAI-compatible `/v1` surface; otherwise the source
is useful for key storage, test and rotation only.

### 2.11 IBM watsonx.ai

1. Create an IBM Cloud API key at cloud.ibm.com → **Manage → Access (IAM) → API keys**.
2. **Add Source → IBM watsonx.ai**.
3. **Base URL** carries the region: `https://us-south.ml.cloud.ibm.com` (or `eu-de`, `eu-gb`, `jp-tok`, `au-syd`).
4. **Project ID** (required extra field): watsonx.ai → **Manage → General → Project ID**. A **Deployment Space ID** can be used instead; the project wins when both are set.
5. **Default model**: leave blank; discovery lists the foundation models your account can reach and prefers `ibm/granite-*`. **Connect and discover**.
6. Tick **Allow routing** to serve it (rule from §2.2).

### 2.12 Anthropic and AWS Bedrock

Both can be added for key storage, test and rotation. Anthropic is tested by
probing `https://api.anthropic.com/v1/models` with your key in `x-api-key`.
Bedrock has no default endpoint, so enter your region endpoint as **Base URL**
before saving or the test reports `no base_url configured`; the bearer token
(`AWS_BEARER_TOKEN_BEDROCK`) is the credential. Neither speaks the OpenAI
catalog format and neither has a local adapter yet, so their models are not
served by the local gateway today. Use them through routing profiles that
target the cloud side, or wait for the native adapters (see the roadmap).

---

## 3. Which switch does what (per provider kind)

| Kind | Discovers models | Served when… | Model ids clients use |
|---|---|---|---|
| Open WebUI | yes | source **Enabled** (routing switch is only for automatic selection) | `openwebui/<id>` |
| Gemini, Groq, OpenRouter, Hugging Face, DeepSeek | yes | key saved and source enabled (seeded provider) | the upstream id, or aliases such as `fast`, `cheap`, `best` |
| watsonx | yes | **Enabled + Allow routing + default model** | the upstream id |
| OpenAI, Generic OpenAI-compatible, Mistral, Together, Fireworks, Azure OpenAI | list only (`/models`) | **Enabled + Allow routing + default model** | the default model id |
| Anthropic, Bedrock | no | not served locally yet | — |

---

## 4. Verify a source really answers

Replace the model id with the one your source exposes. In `local-trust` auth
mode no key is needed from this machine; otherwise send your OllaBridge key as
`Authorization: Bearer …`.

```bash
curl -s http://localhost:11435/v1/models | jq '.data[].id'
```

```bash
curl -s http://localhost:11435/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"openwebui/internal-gemma4-31b","messages":[{"role":"user","content":"Reply with the single word pong."}],"max_tokens":20}'
```

A JSON `choices[0].message.content` of `pong` proves the whole path: client →
OllaBridge → source. Recent requests and their outcome are listed under
**Sources → Usage** and at `GET /admin/recent`.

To see which source serves a model, read the extra fields on each `/v1/models`
entry: `source` is one of `ollama`, `homepilot`, `relay`, `direct_endpoint`,
`open_webui` or `byok:<name>`, and `source_display_name` is the label you gave
the source. The dashboard's Ollama card counts only `source: ollama` entries.

---

## 5. Local runtimes (Runtimes page)

### Ollama

1. **Runtimes → Ollama → Enable Ollama**.
2. **Ollama Base URL**: `http://localhost:11434` when Ollama runs on the same OS.
   If OllaBridge runs in WSL and Ollama on the Windows host, `localhost` is **not**
   the host; start Ollama with `OLLAMA_HOST=0.0.0.0` and point the URL at the
   host's address. The saved URL is the one chat, embeddings and model listing
   use, and the same one **Test Connection** probes.
3. **Default Model**: the Ollama tag to use when a request names no model (e.g. `deepseek-r1`). This is also the gateway-wide fallback.
4. **Test Connection** fetches `<url>/api/tags` and reports how many models Ollama has.
5. **Share Ollama models** publishes the discovered tags to OllaBridge Cloud; per-model control is under **Sources → Models & Access**.

### HomePilot

1. **Runtimes → HomePilot → Enable HomePilot**.
2. **Base URL**: `http://localhost:8000`; **API key** only if HomePilot auth is on.
3. **Node tags**: comma-separated, used for routing filters (`homepilot,persona`).
4. Personas and personalities appear as `persona:<id>` / `personality:<id>` models on `/v1/chat/completions`.

---

## 6. Same thing without the UI

**Environment variables** are a fallback for the seeded providers: export
`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `HUGGINGFACE_API_KEY`,
`DEEPSEEK_API_KEY`, `OPEN_WEBUI_API_KEY`, … before starting OllaBridge. The
encrypted store is checked first, the env var second.

**CLI**: `ollabridge providers add <kind> [--base-url …] [--storage 1|2|3]`,
then `ollabridge providers test <kind>`. Full reference in
[Provider Keys](PROVIDER_KEYS.md#4-the-ollabridge-providers-commands).

**API** (what the form calls), for the Open WebUI example above:

```bash
curl -s -X POST http://localhost:11435/admin/sources/open_webui -H 'Content-Type: application/json' -d '{"api_key":"<paste-your-key>","display_name":"BlueChat","base_url":"https://chat.ai.team.blue/api","default_model":"internal-gemma4-31b","storage_mode":"local_only"}'
```

The response carries the saved record (key redacted), the test outcome and
the discovery summary. Other kinds use the same shape at
`/admin/sources/<kind>`; add `"allow_routing": true` for the kinds in §3 that
need it, and `"extra": {"project_id": "…"}` for watsonx.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `key rejected (HTTP 401)` on save | Wrong or expired key, or the Open WebUI admin has API keys disabled for your role | Create a new key; ask the admin to enable API keys. |
| `base_url is required for this source` | Open WebUI, Generic or Azure saved without a URL | Enter the API root (§2.1, §2.2, §2.10). |
| **Connected** but chat returns `no compatible chat endpoint (404 …)` | Base URL points at the wrong root | Open WebUI: use `https://<host>/api`. Generic: include `/v1`. |
| **Connected** but the model is missing from `/v1/models` | Generic / OpenAI / Mistral / … source with **Allow routing** off or no default model | Tick **Allow routing** and set a default model (§3). |
| Chat answers `502 Ollama not reachable at <url>` | The request fell through to Ollama and Ollama is down at the saved URL (typical in WSL, where `localhost` is not the Windows host) | Fix the Ollama URL on the Runtimes page (§5), or name an external source's model explicitly. |
| Key is in plaintext on disk | `OLLA_SECRET` unset | `export OLLA_SECRET="$(openssl rand -hex 32)"`, restart, re-add the key. |

After upgrading OllaBridge or editing its code, restart the server (`Ctrl+C`,
then `make run`); sources are reloaded from `~/.ollabridge/providers.yaml`
and the key store at start.
