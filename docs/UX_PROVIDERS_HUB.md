# Providers Hub — UX Redesign Spec

The Providers Hub is the place to connect external LLM APIs, discover models,
route aliases, and monitor usage. For a **new user it is the main onboarding
task**, but the current UI treats provider setup as one narrow tab. This spec
restructures it so a first-time user can answer: *Where do I add my API key?
Which providers are connected? How do I test it? What do I do next?*

Implementation target: `frontend/src/pages/providers/ProvidersPage.tsx`
(today: `Connect | Discover | Route | Usage`).

## Information architecture

```
Connect   ->  Setup + Providers
Discover  ->  Models
Route     ->  Routes
Usage     ->  Usage + Logs
```

New tab bar with a **status line** that tells the user where they stand:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Providers Hub                                              ● Online       │
│ Connect LLM providers, sync models, and route requests through aliases.   │
│                                                                           │
│ Setup status: 1 of 5 providers connected · 32 models synced · sync 2m ago │
│                                                                           │
│ [ Setup ] [ Providers ] [ Models ] [ Routes ] [ Usage ] [ Logs ]          │
└─────────────────────────────────────────────────────────────────────────┘
```

| Tab | Purpose |
|---|---|
| **Setup** | First-run checklist: from zero to first working request |
| **Providers** | Add / edit / test / rotate API keys per provider (all providers, not just HF) |
| **Models** | Browse the model catalog with filters; was *Discover* |
| **Routes** | System + custom aliases and routing rules; was *Route* |
| **Usage** | Requests, latency, failures, cost, provider health |
| **Logs** | Failed requests, provider errors, sync history |

## 1. Setup tab (new — default for first-run)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Setup — complete these steps to start routing through OllaBridge.        │
│                                                                          │
│ 1. Connect a provider          Add at least one external LLM API key.    │
│    ○ Not completed             [ Add your first provider ]               │
│                                                                          │
│ 2. Sync model catalog          Fetch models from connected providers.    │
│    ○ Waiting for provider      [ Sync catalog ]                          │
│                                                                          │
│ 3. Test a route                Send a test request via ollabridge:auto.  │
│    ○ Not tested                [ Test ollabridge:auto ]                   │
│                                                                          │
│ 4. Use in your app             Copy OpenAI-compatible SDK config.        │
│                                [ Copy SDK example ]                       │
└─────────────────────────────────────────────────────────────────────────┘
```

Empty state when nothing is connected:

```
No provider connected yet.

Add an API key for Gemini, Groq, OpenRouter, Hugging Face, DeepSeek, or
another supported provider. OllaBridge tests the key, syncs models, and
makes them available through stable aliases like ollabridge:auto.

[ Add your first provider ]   [ Import from .env ]
```

## 2. Providers tab (the biggest fix)

The old Connect tab was a Hugging-Face-only token form. Replace it with a
card per provider, each with real actions and an explicit status.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Providers — connect and manage external LLM APIs.                        │
│ [ + Add Provider ]  [ Refresh All ]  [ Import from .env ]                │
│                                                                          │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ Google Gemini API                                  ● Connected        │ │
│ │ id: gemini-free · 12 models · last test: success · sync 2m ago        │ │
│ │ Key: ••••••••••••••••  [Edit] [Test] [Rotate] [Sync] [Disable] [Models]│ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ Groq API                                        ⚠ Not configured      │ │
│ │ Fast free-tier inference for selected open models.                    │ │
│ │ [ Add API key ]  [ Learn requirements ]                               │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ OpenRouter / Hugging Face / DeepSeek / OpenAI / Anthropic / …         │ │
│ │ ⚠ Not configured            [ Add API key ]  [ Learn requirements ]   │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

**Provider status vocabulary** (never just "Enabled"):
`No key · Connected · Healthy · Failing · Rate limited · Quota exhausted · Disabled`

### Add Provider modal

```
┌───────────────────────────────────────────────┐
│ Add Provider                                  │
│ Provider     [ Google Gemini API        ▾ ]   │
│ API key      [ ••••••••••••••••••• ] [Show]   │
│ Spend policy [ Free-credit only (402 stop) ▾] │
│ Org / project ID (optional) [            ]    │
│ Capabilities ☑ Text  ☑ Tools  ☑ JSON  ☐ Embed │
│                       [ Cancel ] [ Save & Test ]│
└───────────────────────────────────────────────┘
```

After Save & Test:

```
Testing provider...
✓ API key accepted   ✓ Models discovered   ✓ Free route available
✓ Added to ollabridge:auto
[ View models ]  [ Configure routes ]  [ Copy SDK example ]
```

## 3. Models tab (was Discover)

Add a primary **Sync Catalog** action and a real empty state.

```
[ Sync Catalog ] [All providers ▾] [All tasks ▾] [Free only ☐] [Search…]

Model            Provider       Capabilities  Cost  Ctx   Status
gemini-2.5-flash Gemini         text, json    free  1M    available
llama-3.3-70b    Groq           text, tools   free  128k  available
qwen2.5:14b      Ollama local   text          free  32k   local
```

Empty state:

```
No models found. To populate this catalog:
1. Add a provider API key   2. Test the provider   3. Sync the catalog
[ Add provider ]  [ Sync catalog ]
```

## 4. Routes tab (was Route) — split system vs custom

```
System aliases
┌─ ollabridge:auto ──────────────────────────────  Active ─┐
│ Best available across local + cloud.                      │
│ 1. qwen2.5:14b            via local device                │
│ 2. Llama-3.3-70B          via huggingface-free            │
│ 3. gemini-2.5-flash       via gemini-free                 │
│ [Edit priority] [Test] [Copy model name]                  │
└───────────────────────────────────────────────────────────┘

Custom aliases
┌─ free-fast ───────────────────────────────────  Active ──┐
│ [Edit] [Test] [Duplicate] [Delete]                        │
└───────────────────────────────────────────────────────────┘
```

Route editor: alias name, routing goal (lowest latency / cheapest / best),
allowed providers (checkboxes), spend policy (free only / allow paid
fallback), ordered fallback list.

## 5. Usage tab — actionable health table

```
Requests 1,240 · Success 98.4% · Failures 20 · Avg 420ms · Est cost $0.00

Provider     Status      Requests  Latency  Failures  Actions
Gemini       Healthy     820       380ms    2         Test
Groq         Degraded    310       240ms    18        View log
OpenRouter   No key      0         —        —         Add key
HuggingFace  No key      0         —        —         Add key
```

## 6. Logs tab (new) — debug provider/routing

```
[All events ▾] [All providers ▾] [Search error…]
12:41  Gemini      Test request      Success  200 OK
12:39  Groq        Model sync        Failed   Invalid API key
12:35  OpenRouter  Request           Failed   402 payment required
12:31  Router      Alias resolution  Success  free-fast -> Groq
```

## Onboarding flow

```
Add Provider → Save & Test → Sync Models → Configure Routes → Copy SDK Example
```

## Copywriting fixes

| Current | Better |
|---|---|
| "Providers: 5 enabled / Healthy: 0" | "Providers configured: 0 of 5 · Working: 0 · Action needed: add an API key" |
| "No sync yet. Connect a token and refresh." | "No models synced yet. Add an API key for a provider, then click Sync Catalog." |
| "No rows match. Try widening filters or running a catalog refresh." | "No models available yet. Connect a provider, then refresh the catalog." |

## The two highest-impact changes

1. **Providers tab = all providers** with Add key / Test / Rotate / Sync /
   Status — not a Hugging-Face-only token field. (Maps onto the existing
   `/admin/providers/*` API + the `ollabridge providers` CLI.)
2. **Add a Setup tab with a checklist**, shown first, so users know what to
   do instead of exploring tabs.

## Backend mapping (already available)

The redesign needs almost no new backend — it surfaces what exists:

| UI action | Backend |
|---|---|
| Add / edit / rotate key | `ollabridge providers add/rotate` · `POST /admin/providers/*` · encrypted `SecretStore` |
| Test key | `ollabridge providers test` · `provider_ops.test_provider` (models-list probe, no token cost) |
| Provider status vocabulary | `addons/providers/health.py` `HealthStatus` (OK/SLOW/DEGRADED/DOWN/QUOTA_EXHAUSTED) |
| Sync catalog | `POST /admin/providers/huggingface/refresh` and per-provider sync |
| Routes / aliases | `model_aliases.yaml` · `ollabridge route explain` · `policies` engine |
| Usage / health table | `GET /admin/flow-metrics` + provider registry state |
| Logs | request traces (`ollabridge traces`) + provider test/sync events |
