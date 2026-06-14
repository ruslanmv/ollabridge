# Sources, Access, Routing, Keys — the canonical model

OllaBridge had one primitive, **"Source mode" (Ollama / HomePilot / Hybrid)**,
trying to answer four unrelated questions at once. It doesn't scale to IBM
watsonx.ai + local Ollama + remote nodes + cloud relay + per-app sharing.

This document defines the model the product is being rebuilt around. The rule:

> **Source ≠ Access ≠ Routing ≠ Key storage.** Sources provide models. Models
> are published to access surfaces. Routing is optional. Keys are separate from
> sharing.

"Source mode" is **removed**, not patched.

## The four (really five) independent axes

| Axis | Question it answers | Where it lives |
|---|---|---|
| **Source** | *Where does a model come from?* Ollama, watsonx.ai, OpenAI, HomePilot, a remote node | `providers.yaml` + Sources API (`/admin/sources`) |
| **Execution location** | *Where is the request run?* this PC (local), LAN node, cloud-direct, cloud-relay-to-device | derived: relay vs direct; `requires_device_online` |
| **Access / visibility** | *Where is each model exposed?* this PC, LAN, OllaBridge Cloud, a specific paired app | `model_access.yaml` + Model-Access API (`/admin/model-access`) |
| **Key storage** | *Where does the credential live?* on this PC, or an encrypted cloud vault | `storage_mode` on a source (never the same control as sharing) |
| **Routing** | *May OllaBridge auto-pick this model?* | `allow_routing` per model + the policy engine |

A model is `(source_id, model_id)`. Its **access** is a separate record from its
source's **config** and its source's **key** — three different files, three
different lifecycles.

## Data model (implemented)

```
Source              (providers.yaml — metadata only)
  name, kind, display_name, base_url, default_model,
  enabled, storage_mode (local_only | cloud_encrypted_vault | organization_vault)

ModelAccess         (model_access.yaml — metadata only)   ← NEW primitive
  source_id, model_id, enabled,
  visible_local (default on), visible_lan, visible_cloud,
  allowed_apps[], allowed_workspace, allow_routing (default off)

CloudModelManifest  (published to OllaBridge Cloud)
  model_id, source_id, source_label, allowed_apps[],
  allow_routing, requires_device_online
  ← only models with visible_cloud=true are published; secrets never sent
```

**Safe defaults for a new source / model:** enabled, **visible to this PC
only**; LAN, cloud, app access, and routing all **off**. The user opts in
explicitly — publishing to the cloud is never automatic, and does not imply
every app may use the model (that's the per-app allow-list).

## Information architecture

```
Overview · Sources · Models & Access · Apps · Routing · Cloud · Settings
```

| Tab | Purpose | Backend |
|---|---|---|
| **Sources** | Add/test/rotate/remove any source (Ollama, watsonx, OpenAI…) — peers, not modes | `/admin/sources/*` |
| **Models & Access** | Per-model toggles: This PC · LAN · Cloud · `<app>` · Routing | `/admin/model-access/*` |
| **Apps** | Per paired app (e.g. `yourfriend.online`): which models it may use | per-app allow-lists in ModelAccess |
| **Routing** | Optional routing profiles (replaces "Hybrid") | policy engine |
| **Cloud** | Pairing + relay status; the published manifest | `/admin/cloud/*`, `/admin/model-access/manifest/cloud` |

### Sources tab — cards, not modes

```
Sources   2 connected · 6 models · 4 published to cloud      [ + Add source ]

Ollama on this PC     Connected · 2 models · local      [Models] [Access] [Test]
IBM watsonx.ai        Connected · 4 models · external    [Models] [Access] [Rotate key]
HomePilot             Disabled                            [Enable]
```

watsonx.ai is a **first-class source** (catalog entry `watsonx`), with
provider-specific fields (`project_id`/space, `region`) surfaced by the Sources
API's `extra_fields`, not a generic "custom endpoint".

### Models & Access tab — the key fix

```
Model            This PC   LAN   Cloud   yourfriend.online   Routing
qwen2.5:0.5b       on       off    on          on             off
llama3.1:8b        on       off    off         off            off
granite-3-8b       on       off    on          on             off
```

Each column is an independent toggle backed by one `POST
/admin/model-access/{source}/{model}` call. This is what replaces "Hybrid".

### Apps tab — where `yourfriend.online` belongs

Publishing to the cloud ≠ every app can use every model. The Apps tab sets the
per-app allow-list (`allowed_apps`), so a model can be cloud-published yet
scoped to specific apps.

## Key storage vs sharing — never the same control

```
Who can use these models?              Where is the API key stored?
[ ] This computer only                 (•) Keep key on this computer
[ ] Local network                      ( ) Encrypted cloud vault
[ ] OllaBridge Cloud paired apps
[ ] Workspace
```

For **Ollama / local relay**: there is no key; the cloud relays the request
back to this device (`requires_device_online: true`). For **watsonx.ai**:
*keep key local* → cloud relays to this device; *cloud vault* → cloud calls IBM
directly (`requires_device_online: false`). These are different sentences and
get different labels — never both called "sharing".

## Vocabulary corrections

| Old / ambiguous | Canonical |
|---|---|
| Source mode (Ollama/HomePilot/Hybrid) | **removed** — sources are peers; Hybrid → a routing profile |
| Sharing | **Access scope** (per-model visibility) |
| Storage mode | **Key storage** (local vs vault) |
| Share provider / Cloud sharing | **Publish models** / **Publish to paired apps** |

## Workflow (the target)

```
1. Sources → add Ollama on this PC        (auto-detected, 2 models)
2. Sources → add IBM watsonx.ai           (project_id + region + key; Save & Test; sync models)
3. Cloud   → pair this computer
4. Models & Access → toggle Cloud + yourfriend.online for the models you want
5. yourfriend.online → the model selector shows only those, grouped by source
```

In the app's selector each model carries a source badge:

```
qwen2.5:0.5b    Local · This PC · requires PC online
granite-3-8b    IBM watsonx.ai · key kept local · requires PC online
granite-3-8b    IBM watsonx.ai · cloud direct          (if key in cloud vault)
```

## Implementation status

| Piece | State |
|---|---|
| `model_access.py` + `/admin/model-access/*` | **Implemented & tested** — the new Access primitive |
| `cloud_manifest()` filters by `visible_cloud` + per-app allow-lists | **Implemented & tested** |
| watsonx.ai as a first-class source (catalog + `extra_fields`) | **Implemented** (cloud-side adapter already exists) |
| Source removal cascades to access records | **Implemented & tested** |
| Sources tab (cards, peers) | **Shipped** (External Sources Hub, sidebar → Sources) |
| Models & Access tab UI | **Shipped** — per-model grid: This PC · LAN (soon) · Cloud · allowed apps · Routing |
| "Source mode" picker removed; old page → Local Runtimes | **Shipped** — Enable toggles are the source of truth |
| Per-app allow-lists in the UI | **Shipped inline** — editable chips per model in Models & Access; a dedicated Apps tab remains planned |
| Cloud honouring per-app `allowed_apps`, vault `cloud_direct` execution | **Planned** (cloud-side) |
| LAN visibility / workspace enforcement | **Forward-looking flags** — persisted, not yet served |

Nothing above fakes enforcement: flags that aren't yet honoured by a serving
path are documented as forward-looking, and secrets are never published in the
manifest.
