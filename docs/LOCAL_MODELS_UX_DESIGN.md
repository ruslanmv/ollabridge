# OllaBridge Local — Models Page UX Design

## Objective

Give the local OllaBridge gateway a dedicated, full-page **Local Model Fleet**
experience that mirrors the cloud's Hugging Face Models page in spirit, but is
adapted to what the local user actually controls: a single trusted machine
that can **discover, pull, test, pin, enable, and share** models with the
cloud bridge.

The local data is **node + runtime + model triples**, not provider-pair rows:
the user owns one (sometimes two) runtimes and a handful of model files on
disk. Disk space, hardware fit, and the privacy boundary between local and
cloud are first-class. The page should make these visible at a glance and
let the user act without leaving it.

The current `frontend/src/pages/models/ModelsPage.tsx` is a flat list grouped
by Ollama vs HomePilot. This design replaces it with a richer surface backed
by the new `/local/models/*` and `/local/cloud/manifest` endpoints.

---

## Recommended UX pattern

Use a **dedicated page**, not a modal.

Primary route (already mounted by the SPA shell):

```text
/ui/#models
```

Entry points:

- Sidebar `Models` icon (already present).
- Dashboard hero shortcut: "Manage local models".
- Cloud page link when bridge is connected: "Model manifest shared with cloud".

Use modals only for focused actions:

- Pull model (with live progress)
- Manual add row (planned pulls, pinning, manual_id mapping)
- Test result detail (when the toast isn't enough)
- View raw `/api/show` metadata
- Confirm "Remove from disk" / delete manual row
- "Disconnect cloud sharing" confirm

Do **not** put the full catalog in a modal. Disk, ranking, capabilities, and
pull progress need a full page.

---

## Page layout

```
┌───────────────────────────────────────────────────────────────────────┐
│ Header / command bar                                                  │
│ ┌──────────────────────────┐ ┌────────────────────────────────────┐  │
│ │ KPI tiles  (4 cards)     │ │ Sync banner / pull tracker         │  │
│ └──────────────────────────┘ └────────────────────────────────────┘  │
│                                                                       │
│ Top 3 Recommended shelf       (only when catalog has runs)            │
│                                                                       │
│ Hardware fit + cloud share panel   (collapsible side card)            │
│                                                                       │
│ Filter chips + search + sort                                          │
│ Bulk action drawer (appears on selection)                             │
│                                                                       │
│ Catalog table  (Ollama node 01)                                       │
│ Catalog table  (Ollama node 02)    multiple nodes scroll separately   │
│                                                                       │
│ Pull-from-library gallery   (curated quick-adds when catalog empty)   │
│                                                                       │
│ Modals (manual add, test detail, pull progress, raw metadata)         │
└───────────────────────────────────────────────────────────────────────┘
```

### 1. Header / command bar

```
Local Model Fleet
Discover, pull, and share the models on this machine.

Runtime: ollama  →  http://localhost:11434  (reachable)
Last sync: 11:42:08            Cloud bridge: connected · 3 shared

  [ Sync now ]   [ Pull model ]   [ Add manual ]   [ Probe enabled ]
```

Use a single primary button — **Pull model** when no/few models exist,
**Sync now** when a populated catalog needs a refresh.

Right side shows:

- runtime reachable / unreachable dot
- cloud bridge state (Disconnected / Pairing / Connected — N shared)
- last sync timestamp (relative)

If runtime is unreachable, show banner instead of buttons:

```
Ollama is not responding on http://localhost:11434.
[ Open Settings ]  [ Retry ]
```

### 2. KPI tiles

```
┌──────────────────┬──────────────────┬──────────────────┬──────────────────┐
│ Installed        │ Enabled          │ Top 3 ready      │ Disk used        │
│   8              │   3              │   3              │   42.6 GB        │
│ models discovered│ available for    │ auto-selected by │ across the node  │
│                  │ routing          │ score            │                  │
└──────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

`Disk used` is unique to local — show a small progress bar relative to free
space (queried via `/local/runtime/info` once we wire that). Click → modal
breakdown by model.

### 3. Active pull tracker

When `/local/models/pulls/active` returns ≥1 entry, render a sticky strip
under the header:

```
Pulling 2 models
  ✓  qwen2.5:14b      890 MB / 8.9 GB   10%  · 18s
     llama3.2:3b      pulling layers…   0%   · queued
  [ Cancel all ]
```

Each row is its own progress bar with cancel button. This is the
local-side equivalent of the cloud's sync banner: never block the page,
always show what's happening.

### 4. Top 3 Recommended shelf

The local catalog auto-enables 3 (configurable). Render them as cards above
the long-tail table:

```
#1  Qwen 2.5 14B          qwen · 14b · q4_K_M
    score 0.83   latency 220ms   tools yes   sweet-spot size
    [ enabled ]  [ test ]  [ pin ]  [ share with cloud ✓ ]

#2  Llama 3.1 8B Instruct  llama · 8b · q4_0
    score 0.76   latency 180ms   tools yes
    [ enabled ]  [ test ]  [ pin ]  [ share with cloud ✓ ]

#3  Mistral 7B Instruct    mistral · 7b · q4_K_M
    score 0.72   latency 240ms
    [ enabled ]  [ test ]  [ pin ]  [ share with cloud ✓ ]
```

Three is small enough to fit on one row at typical desktop widths. Per-card
controls:

- toggle Enabled
- run health probe (1-token)
- pin to top
- toggle "share with cloud" — flips whether this model appears in the
  heartbeat manifest

A primary CTA below: `Enable recommended top 3` (when one or more are
currently disabled).

### 5. Hardware fit + cloud share side panel

Collapsible panel pinned to the right at desktop widths:

```
Hardware fit
  Total disk    480 GB
  Free disk     128 GB
  Sweet spot    4 B – 12 B parameters  on your GPU
  Suggestion    qwen2.5:7b, mistral:7b are good fits

Cloud sharing
  Bridge        connected (paired 3d ago)
  Shared        3 of 8 models                 [ Manage sharing ]
  Manifest      manifest current (1 min ago)
  Privacy       expose_models_to_cloud = on
```

On narrow screens this becomes a section above the table.

### 6. Smart filter chips

```
[ All ]  [ Enabled ]  [ Top 3 ]  [ Tools ]  [ Vision ]  [ Embeddings ]
[ Pinned ]  [ Manual ]  [ Pulling ]  [ Broken ]  [ Removed ]
```

Plus a family multi-select:

```
Family:  ◧ llama  ◧ qwen  □ gemma  □ mistral  □ deepseek  □ other
```

Search input (existing):

```
Search:  qwen 14b
```

Sort dropdown:

```
Sort:  Best score | Smallest | Largest | Fastest | Recently pulled
```

All filters are client-side — server returns the full node catalog and
the React state filters/sorts it.

### 7. Bulk action drawer

Appears when ≥1 row is checked:

```
3 selected   [ Enable ]  [ Disable ]  [ Pin ]  [ Test ]  [ Share to cloud ]  [ Remove from disk ]
```

`Remove from disk` and `Delete manual row` need confirm modals.

### 8. Catalog table (per node)

Each node renders its own table to keep the `node_id:model` distinction
visible. Multi-node setups (workstation + homelab box) get a tab strip:

```
[ Ollama on local-node-01  (8) ]   [ Ollama on local-homelab  (4) ]
```

Columns:

```
Select  Rank  Model  Family  Size  Quant  Context  Caps  Latency  Disk  Status  Share  Actions
```

Row example:

```
☐  #1  qwen2.5:14b   qwen 14b  q4_K_M  32k   ⚙🛠   220ms   8.9 GB  ✓ verified  ☁ on   [ … ]
```

Row hover reveals an action overflow menu:

```
Test
View metadata
Copy router ID   →   local-node-01:qwen2.5:14b
Use in alias →  copies an alias snippet
Pin / Unpin
Share to cloud / Stop sharing
Remove from disk
```

Stale/removed rows are dimmed; the row is kept (so the user can re-pull from
the catalog history).

### 9. Pull-from-library gallery

When catalog is empty or the user opens the "Pull model" CTA, show a curated
gallery instead of a blank picker:

```
┌──────────────────┬──────────────────┬──────────────────┐
│ Qwen 2.5 7B      │ Llama 3.1 8B     │ Mistral 7B       │
│ qwen2.5:7b       │ llama3.1:8b      │ mistral:7b       │
│ 4.4 GB           │ 4.7 GB           │ 4.1 GB           │
│ general · tools  │ general · tools  │ general          │
│ [ Pull ]         │ [ Pull ]         │ [ Pull ]         │
└──────────────────┴──────────────────┴──────────────────┘
┌──────────────────┬──────────────────┬──────────────────┐
│ Llama 3.2 3B     │ Phi-3.5 Mini     │ Nomic Embed Text │
│ llama3.2:3b      │ phi3.5:3.8b      │ nomic-embed-text │
│ 2.0 GB           │ 2.3 GB           │ 274 MB           │
│ fastest · tiny   │ small · efficient│ embeddings       │
│ [ Pull ]         │ [ Pull ]         │ [ Pull ]         │
└──────────────────┴──────────────────┴──────────────────┘

[ Pull custom tag ]
```

Card states:

- `Pull` — not installed
- `Installed` — green pill, primary action becomes `Enable`
- `Pulling 31%` — inline progress
- `Pulling failed` — red pill + Retry

The gallery is hard-coded in the frontend (a small `RECOMMENDED_TAGS`
constant). Industry-best-practice picks at design time so the empty state
is never silent.

### 10. Manual add modal

Same fields as the cloud's manual add, adapted for local context:

```
Add a local model
  Node                local-node-01 (ollama)        select if >1
  Model tag           qwen2.5:14b
  Display name        Qwen 2.5 14B Chat            optional
  Capabilities        ☑ chat  ☐ tools  ☐ vision  ☐ embeddings
  After save          ☑ Pin    ☑ Enable immediately
                      ☑ Run health test
                      ☑ Pull now if not installed
  [ Cancel ]   [ Add and pull ]
```

If "Pull now" is checked we kick `POST /local/models/pull` and open the
pull-progress modal inline.

### 11. Pull-progress modal

When the user clicks Pull (from gallery, manual add, or a row action):

```
Pulling qwen2.5:14b
  Stage      downloading layers
  Progress   ▓▓▓▓▓░░░░░░░░░░░░░░░  31%
  Bytes      2.7 GB / 8.9 GB
  Speed      54 MB/s
  Last log   pulling 26f8eaef9d57: 2.7 GB / 8.9 GB

  [ Cancel pull ]   [ Hide — keep running ]
```

Hide keeps the pull running in the background tracker (section 3). The
modal closes itself on completion and switches to a success toast plus a
"Test now" / "Enable" follow-up.

### 12. Test model modal

Quick path uses a toast — `qwen2.5:14b OK — 220 ms`. The modal opens when
the user wants details:

```
Testing qwen2.5:14b
  Prompt:  Reply with OK.

  Result
    status   verified
    latency  220ms
    output   OK

  [ Close ]  [ Open metadata ]  [ Re-run ]
```

If broken:

```
  status   broken
  error    http_500 — ollama serve crashed mid-stream
  [ Open Ollama log ]   [ Retry ]
```

### 13. Cloud-sharing controls

The big difference vs cloud HF: the user owns these models, so they decide
what cloud Admin sees.

Per row toggle:

```
Share with cloud
   on   model included in next /local/cloud/manifest heartbeat
   off  hidden from cloud Admin entirely
```

Top-level toggle in the side panel:

```
Expose models to cloud
   on (default)
   off (privacy mode — disables sharing for all models at once)
```

A small "manifest updated" indicator pulses near the cloud-status chip when
the bridge sends a new hello frame.

---

## Visual hierarchy

Order from top:

1. Command bar with single primary CTA based on state.
2. KPI tiles + sync/pull banner side by side on desktop.
3. Top 3 recommendation shelf.
4. Hardware fit + cloud share panel.
5. Filter chips + search + sort.
6. Catalog table per node.
7. Pull library gallery.
8. Manual modal / test modal / pull modal.

Avoid showing 50 rows of metadata first. The operator's main question is:
"Which models should I be running, and is anything pulling right now?"

---

## UX states

### Ollama not reachable

```
Ollama is not responding.
Set the runtime base URL on the Settings page or start the service.

[ Settings ]   [ Retry ]
```

KPIs grey out. Catalog shows last known rows dimmed.

### Empty catalog (Ollama running, no models)

```
No models installed yet
Start with the recommended set or pull a custom tag.

[ Pull recommended top 3 ]   [ Pull custom ]   [ Add manually ]
```

`Pull recommended top 3` queues three pulls into the tracker.

### Syncing

Non-blocking banner under the header:

```
Refreshing catalog…   reading /api/tags and /api/show
```

Existing rows stay visible.

### Pulls running

Sticky strip per pull with progress bar and cancel button (section 3).

### One or more rows broken

Status pill `broken`, tooltip shows the last error. The row's
`Test` button gets a primary tint to nudge a retry.

### Cloud bridge disconnected

Side panel switches to:

```
Cloud sharing
  Bridge        disconnected
  [ Pair with cloud → /pairing ]
```

### Cloud sharing off (privacy mode)

Per-row share toggles are disabled with tooltip:

```
Cloud sharing is off. Enable it in the side panel to share individual models.
```

---

## Integration with other pages

### Sidebar

`Models` icon already exists. Show a badge when:

- pulls are in flight → animated dot
- broken models > 0 → amber dot
- catalog completely empty → no badge (use the page itself to onboard)

### Dashboard

Add a "Models" widget summarising:

```
8 installed · 3 enabled · 3 shared to cloud
```

Click → `/models`.

### Cloud page

Add a "Manifest preview" section showing the same payload the bridge would
ship right now, with a link back to the Models page when the user wants to
toggle individual rows.

### Settings page

Keep low-level toggles (`local_runtime_enabled`, `runtime_base_url`,
`expose_models_to_cloud`, `allow_remote_inference`) here; the Models page
mirrors them via small toggle widgets but Settings stays canonical.

---

## API contract used by this page

All endpoints are already on the backend (`addons/local_catalog/routes.py`):

```text
GET  /local/runtime/info
GET  /local/models?node_id=&enabled=&top=&family=&limit=
GET  /local/models/top?node_id=&limit=
GET  /local/models/pulls/active
POST /local/models/sync                     → fire-and-forget
POST /local/models/manual                   → add row
POST /local/models/{router_id}/enable
POST /local/models/{router_id}/pin
POST /local/models/{router_id}/test
POST /local/models/pull
GET  /local/models/pull/{external_id}
DELETE /local/models/{router_id}
GET  /local/cloud/manifest
```

Frontend additions (new file):

```text
frontend/src/lib/localApi.ts
  - typed wrappers around /local/* endpoints

frontend/src/lib/localHooks.ts
  - useLocalRuntimeInfo()
  - useLocalModels(nodeId)
  - useLocalTopModels(nodeId, limit)
  - useActivePulls()          // refetch every 1s while non-empty
  - useStartPull()            // mutation
  - useEnableModel()          // mutation
  - useTestModel()            // mutation with toast hooks
  - usePinModel()             // mutation
  - useManualAdd()            // mutation
  - useCloudManifest()        // for the "Manifest preview" widget
```

All hooks built on TanStack Query so the existing patterns stay consistent
with `lib/hooks.ts`.

---

## Component decomposition

```
ModelsPage/
├─ ModelsPage.tsx              orchestrator + layout
├─ CommandBar.tsx              title, KPI summary, primary CTA
├─ KpiTiles.tsx                4 tiles (installed/enabled/top/disk)
├─ ActivePullsBanner.tsx       sticky strip while pulls exist
├─ TopRecommendedShelf.tsx     3 hero cards
├─ HardwareFitPanel.tsx        side panel
├─ CloudSharePanel.tsx         side panel
├─ FilterBar.tsx               chips + family + search + sort
├─ BulkActionsDrawer.tsx       appears on selection
├─ NodeTable.tsx               table per node_id
│   └─ RowActions.tsx          inline + overflow menu
├─ PullGallery.tsx             curated quick-add cards
├─ ManualAddModal.tsx
├─ PullProgressModal.tsx
├─ TestResultModal.tsx
└─ RawMetadataModal.tsx
```

Each component owns its data via the relevant TanStack hook; the page
itself only holds UI state (selected rows, open modal, current filter).

---

## Success criteria

The UX is successful when an operator can:

1. Land on `/models` from the sidebar.
2. See in 1 second how many models are installed, enabled, top-recommended,
   and how much disk they're using.
3. See any in-flight pulls without scrolling.
4. Read the top 3 cards and tell which model to use right now.
5. Enable / disable a model with one click and a toast.
6. Pull `qwen2.5:14b` from the gallery without typing the tag and watch
   progress in a non-blocking modal.
7. Test any model and see latency + status in under three seconds.
8. Add an arbitrary tag manually and have it queued for pull.
9. Toggle whether a specific model is exposed to the cloud heartbeat.
10. Switch privacy mode off globally with one toggle.
11. Recover gracefully when Ollama is down (clear empty state, no spinners
    forever).

If any of these takes more than two clicks, the design isn't there yet.
