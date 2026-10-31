# OllaBridge — Logging & Console Output Design

## Objective

Make the gateway's console output read like **one product**: a short startup
story, a quiet idle state, exactly one informative line per routed request,
and failures that say what broke, where, and what to do. The same engine must
produce coloured, aligned output on a developer's terminal, plain text under
systemd/journald, and JSON lines for containers and log shippers — with
request correlation, per-component levels, and redaction that is actually
installed.

This document analyses what the console shows today, sets the target output,
and specifies the architecture, configuration surface and rollout plan.

Scope: the Python gateway (`ollabridge start`), the node agent
(`ollabridge-node`), the MCP server, and the Docker entry point. The React
dashboard gets a later "Activity" feed built on the same records (Phase 3).

## Status

| Phase | State |
|---|---|
| 1. Foundation | **Done.** `core/logsetup/` package, `--log-level` / `--log-format`, `OLLABRIDGE_LOG_*`, all four entry points, session header, lifespan with a shutdown line, `tests/test_logsetup.py`. |
| 2. Signal | **Partly done.** Request line (`api/request_log.py`), quiet successful reads, 4xx repeat suppression with reasons, router attempts at DEBUG, catalog sync on change only (and its counter fixed), `-v` / `make start VERBOSE=1`, `tests/test_access_log.py`. **Open:** startup collapse (provider summary line, SecretStore warning once, paths to DEBUG), the Ready-gated banner, the Makefile banner, `xdg-open` noise. |
| 3. Enterprise sinks and UX | Not started. |

Decisions made while building Phase 2 so far, from a real 14-minute log with
Open WebUI attached (53 lines, 3 of them about the one chat request):

- **Quiet by method, not by path list.** Successful GET, HEAD and OPTIONS are
  DEBUG; every dashboard poll is a GET, so no path list needs maintaining.
  This includes `/v1/models`, which §3.2 had kept loud: clients refresh it
  every minute.
- **Client errors are logged once per client and reason.** The first 4xx for
  a (client, method, path, status, reason) is WARN; repeats are DEBUG with a
  count reported every 10 minutes while they continue. Not-found is keyed per
  client only, so a scanner is one warning. The auth check supplies the
  reason ("no API key sent", "API key not accepted", the local-trust hint).
- **One component, `http`, for request lines.** `--log-level http=debug`
  shows every request; uvicorn's own access lines are dropped while the app's
  middleware is active.
- **Facts reach the line through a context dict** (`core/logsetup/request_facts.py`):
  the auth check, the provider router and the chat handler call `note()`.
  The request id is read from the `X-Request-ID` response header.
- **The catalog counter was wrong, not just loud.** Each sync copied a fresh
  `is_top_recommended=False` onto stored rows, so every unchanged run
  "promoted" the top models again. That is fixed; the sync now logs INFO only
  for added, removed, promoted or dropped models.

Decisions made while building Phase 1, which the sections below reflect:

- **Ready line.** It comes from uvicorn's "Uvicorn running on …" record,
  rewritten by the uvicorn bridge, not from the lifespan hook. The lifespan
  runs before the socket is bound, so a busy port would print "Ready" and then
  fail. Under `--reload` or several workers the parent binds the socket and
  the line reads "Listening, starting worker processes".
- **Access log.** uvicorn's access log stayed on in Phase 1, re-rendered as
  `http  GET /health 200  client=…` with WARN for 4xx and ERROR for 5xx. The
  Phase 2 request middleware now replaces it; the re-rendering remains for a
  bare ASGI app without that middleware.
- **Request correlation already works.** The existing request-id middleware
  binds `request_id` into the log context, so every line written during a
  request carries `req=…`. Phase 2 moves this into the pure-ASGI middleware.
- **Redaction lives in the formatters.** Scrubbing the final rendered text
  covers non-string arguments such as exception objects, which a filter on
  `record.msg` and `record.args` misses.
- **Header placement.** `ollabridge start` prints the header itself. A bare
  `uvicorn ollabridge.api.main:app` prints it from the lifespan, so importing
  the module in a script prints nothing.
- **Docker.** The image keeps its uvicorn `CMD` and gets the same output via
  `OLLABRIDGE_LOG_*`. Its default is `auto`, which is `plain` off a terminal;
  set `OLLABRIDGE_LOG_FORMAT=json` to ship logs.

---

## 1. What the console shows today

The `make start` transcript is annotated below. Line counts are from a real
run with no requests sent.

| # | What appears | Lines | Root cause | Where |
|---|---|---|---|---|
| 1 | Makefile banner ("OllaBridge — AI Pipeline Builder…", URLs) | 14 | Makefile prints its own banner with `echo` | `Makefile` `start:` target |
| 2 | Yellow bind-all warning | 3 | Printed via Rich `console.print`, before the server exists | `cli/main.py:334` |
| 3 | Rich panel **"✅ OllaBridge is Online"** | 28 | Printed **before** `uvicorn.run()`; the server is not online yet and may fail to bind. Join token printed twice; key in clear text; the node command wraps | `cli/main.py:_dashboard` |
| 4 | `INFO:     Started server process [35191]` ×4 | 4 | uvicorn's own log config: a second format on the same stream | `uvicorn.run(log_level=…)` with default `log_config` |
| 5 | `SecretStore: OLLA_SECRET is not set — …` **×7** | 7 | `SecretStore()` is constructed once per provider inside `_byok_key → get_secret → _store()`; every instance warns | `provider_ops.py:_store`, `secret_store.py:88` |
| 6 | `Registered provider: …` ×6 + `No API key found for provider …` ×5 | 11 | Per-item INFO where one summary line would do | `registry.py:42`, `provider_seeder.py:87` |
| 7 | `Loaded 7 providers from /mnt/c/…/providers.seed.yaml`, `Loaded 24 aliases from …`, `Provider system initialized…`, `Provider addon initialized…` | 4 | Four summaries of the same event; absolute paths at INFO | `provider_loader.py`, `provider_seeder.py:149`, `api/main.py:802` |
| 8 | `HF catalog snapshot not found … starting empty` | 1 | A normal first-run state logged like a problem | `hf_catalog/snapshot.py` |
| 9 | Local catalog: `loaded…`, `scheduler started…`, `initialised…` | 3 | Three lines for one subsystem | `local_catalog/*` |
| 10 | 17 lines of `/usr/bin/xdg-open: 882: firefox: not found` | 17 | `webbrowser.open()` under WSL with no Linux browser; the child's stderr is inherited | `cli/main.py:_open_browser_when_ready` |
| 11 | `local catalog sync node=local fetched=3 upserted=3 promoted=3 …` **every 60 s, forever** | ∞ | Periodic job logs at INFO even when nothing changed; "upserted=3" counts rows touched, not rows changed | `sync_service.py:153` |
| 12 | **Nothing** when a chat request is served | 0 | No request-level log line exists. The `request_id` is minted and echoed in `X-Request-ID` but never logged. Telemetry goes to three sinks (SQLite `RequestLog`, `traces.db`, in-memory `flow_events`) and none of them reaches the console | `api/main.py:1029-1500` |

Four visual languages share one stream: Makefile `echo`, Rich panels, uvicorn's
`INFO:     ` prefix, and the app's `%(asctime)s %(levelname)-8s %(name)s:`.
Logger names are full dotted paths up to 55 characters
(`ollabridge.addons.providers.services.provider_loader`), so the message
starts past column 80.

Structural gaps found while reading the code:

- **Redaction is not installed.** `core/redact.py` ships a `RedactionFilter`
  and `docs/DEPLOYMENT_HARDENING.md` says it is attached, but nothing calls
  `install_redaction_filter()`. A provider error body containing a key would
  be logged verbatim today.
- **One level for everything.** `--log-level` sets uvicorn and the app
  together. The CLI default is `warning` (silences the app) while the Makefile
  passes `info`. There is no per-component control.
- **Access log would flood.** The dashboard polls ten endpoints every
  1.5–30 s. With `info` and uvicorn's access log on, an open dashboard emits
  roughly 40 `GET /admin/flow-metrics 200 OK` lines per minute. The paste does
  not show it only because the browser never opened.
- **No machine-readable output, no file sink.** Nothing for Docker, Loki,
  Datadog or Splunk. `paths.audit_log_file()` is declared and never written.
- **Only one entry point configures logging.** `start` calls
  `configure_logging`; `ollabridge-node`, `ollabridge-mcp` and the Docker
  `CMD` (bare uvicorn) rely on `ensure_logging_configured()` in `create_app`,
  which never touches uvicorn's loggers. The node agent has no setup at all.
- **Timestamps are naive local time** with no offset, so logs from a WSL box
  and a cloud host cannot be lined up.
- **`@app.on_event("startup")`** is deprecated in Starlette; the lifespan hook
  that replaces it is also where a clean "Ready" line belongs.

---

## 2. Design principles

1. **One line per fact.** A request is one line. Startup is one line per
   subsystem plus one "Ready". A periodic job logs when its outcome changes,
   not when it runs.
2. **The message carries the decision, the tail carries the data.** Prose
   first ("Registered 6 providers, 5 without API key"), then dimmed
   `key=value` pairs. Humans read the left, tools parse the right.
3. **Quiet by default, loud on change.** Idle gateway: zero lines per minute.
   State transitions (runtime down/up, node joined/left, cloud
   connected/reconnecting) are INFO/WARN; repeats are DEBUG with a periodic
   reminder (the pattern `core/reachability.py` already implements).
4. **Same records, three renderings.** `pretty` (TTY), `plain` (pipes,
   journald), `json` (containers). Never a fourth path to stderr: Rich panels
   are reserved for interactive CLI commands and the ready banner.
5. **Correlation is free.** Every line emitted while a request is in flight
   carries its `request_id` automatically via `contextvars`, so a provider
   failover warning and the final request line are joinable without the
   developer passing ids around.
6. **Secrets never reach a handler.** Redaction runs on the handler, so it
   covers uvicorn and third-party records too. Keys and tokens are shown only
   by the CLI banner, never via `logging`.

---

## 3. Target output

### 3.1 Startup (pretty, TTY)

```text
── OllaBridge 0.1.9 · 2026-10-29 · pid 35191 · level info · format pretty ──────────────────
08:36:33.412  INFO   gateway    Starting  host=0.0.0.0:11435 auth=local-trust workers=1 model=deepseek-r1
08:36:33.498  INFO   providers  Catalog loaded: 7 providers, 24 aliases
08:36:33.512  WARN   secrets    OLLA_SECRET not set: provider tokens stored in plaintext (mode 0600). Set OLLA_SECRET in production.
08:36:33.540  INFO   providers  Registered 6 providers, 5 without API key (gemini-free groq-free openrouter-free huggingface-free deepseek-cheap). Add keys in the dashboard or via GEMINI_API_KEY, GROQ_API_KEY, …
08:36:33.551  INFO   catalog    Local catalog: 1 node, 3 models  sync=60s
08:36:33.580  INFO   gateway    Ready in 0.9s  http://localhost:11435  dashboard=/ui  health=/health
```

Then the CLI prints the Rich **Gateway Ready** panel — only now, because
`/health` has answered 200 — and opens the browser. Six log lines replace
twenty-seven, and nothing claims to be online before it is.

Column layout: `HH:MM:SS.mmm` (12) · level (5) · component (10) · message ·
dimmed `key=value` tail. The date appears once in the session header and
again whenever it rolls over at midnight. The header also tells an operator
reading a pasted log which version and which log level produced it.

### 3.2 Requests

```text
08:41:02.337  INFO   request    POST /v1/chat/completions 200  req=a1b2c3d4 model=deepseek-r1 route=ollama/local tokens=412→88 1.84s client=127.0.0.1
08:41:07.915  WARN   router     groq-free quota exhausted, failing over to openrouter-free  req=9f8e7d6c model=groq/llama-3.3-70b 0.31s
08:41:08.502  INFO   request    POST /v1/chat/completions 200  req=9f8e7d6c model=groq/llama-3.3-70b route=openrouter-free fallback=1 tokens=1203→356 0.59s
08:45:10.004  ERROR  request    POST /v1/chat/completions 502  req=0a1b2c3d model=llama3 route=ollama/local upstream_unreachable url=http://localhost:11434 0.02s
08:45:10.006  WARN   runtime    Ollama not reachable at http://localhost:11434 (connection refused). Further failures at DEBUG, reminder every 5m.
08:47:19.220  WARN   request    POST /v1/chat/completions 401  req=77e1aa90 client=192.168.1.42 invalid_api_key
```

Rules:

- Exactly **one `request` line per request**, emitted by middleware after the
  response status is known, enriched with whatever the handler recorded
  (`model`, `route`, `tokens`, `fallback`, `error_code`).
- Level from status: 2xx/3xx → INFO, 4xx → WARN, 5xx → ERROR.
- `tokens=in→out` uses the upstream's counts when present, else the existing
  estimate (marked `~412→88`).
- **Quiet paths** (`/health`, `/ui/*`, `/admin/flow-metrics`, other dashboard
  polls) log at DEBUG. Configurable; errors on quiet paths are still WARN/ERROR.
- Per-attempt routing detail ("Routing to X score=0.93") moves to DEBUG. The
  outcome of a failover stays WARN on the `router` component, and now carries
  `req=` for free.
- `req=` shows the first 8 hex characters of `request_id`; `ollabridge traces
  show a1b2c3d4` already accepts a prefix, so the console and the trace store
  are joinable.

### 3.3 Steady state, nodes and cloud

```text
08:50:00.101  INFO   catalog    Sync node=local: 4 models (+1 qwen2.5-coder:7b) 0.4s
09:02:14.770  INFO   relay      Node joined  node=laptop-ruslan models=3 capacity=2 client=10.0.0.12
09:31:45.003  WARN   relay      Node left  node=laptop-ruslan reason=connection_closed streams_closed=1
09:40:00.000  INFO   cloud      Connected to OllaBridge Cloud  url=wss://… models_published=6
09:41:12.515  WARN   cloud      Connection dropped, reconnecting in 4s  attempt=2 error=ConnectionResetError
```

The 60-second catalog sync logs **only when the model set changed**, naming
the delta. Unchanged runs are DEBUG. Unreachable runtime follows the
reachability pattern (first failure WARN, then DEBUG, reminder, recovery INFO).

### 3.4 Shutdown

```text
10:12:03.330  INFO   gateway    Shutting down  reason=SIGINT uptime=1h35m requests=142 errors=3
```

### 3.5 Plain (non-TTY, journald, `make start | tee`)

Same columns, no ANSI, full ISO-8601 timestamp with offset:

```text
2026-10-29T08:41:02.337+01:00 INFO  request    POST /v1/chat/completions 200  req=a1b2c3d4 model=deepseek-r1 route=ollama/local tokens=412→88 1.84s client=127.0.0.1
```

### 3.6 JSON (containers, shippers)

One object per line, UTC, flat keys, stable names (dictionary in Appendix A):

```json
{"ts":"2026-10-29T07:41:02.337Z","level":"info","component":"request","logger":"ollabridge.api.requests","msg":"POST /v1/chat/completions 200","request_id":"req_a1b2c3d4e5f6…","method":"POST","path":"/v1/chat/completions","status":200,"latency_ms":1840,"client":"127.0.0.1","model":"deepseek-r1","resolved_model":"deepseek-r1","route":"ollama/local","provider":null,"device":"local","fallback":false,"tokens_in":412,"tokens_out":88,"tokens_estimated":false,"pid":35191,"version":"0.1.9"}
```

Exceptions add `exc_type`, `exc_message`, `stack` (string). Nothing from the
prompt or the response body is ever a field.

---

## 4. Architecture

Keep the stdlib `logging` module — 56 modules already use `getLogger`,
uvicorn and every dependency emit stdlib records regardless — and build the
missing pieces around it. `core/logsetup.py` becomes a package with the same
public names, so existing imports keep working.

```text
src/ollabridge/core/logsetup/
├── __init__.py      configure_logging(), ensure_logging_configured(), get_config()   (public API, unchanged names)
├── config.py        LogConfig dataclass; resolve(cli_args, env) with precedence; export_to_env() for uvicorn children
├── formatters.py    PrettyFormatter, PlainFormatter, JsonFormatter — one record model, three renderers
├── components.py    logger-name → component short name map (Appendix B); stable, documented
├── context.py       ContextVar-backed LogContext; bind()/update()/clear(); ContextFilter copies fields onto records
├── filters.py       ContextFilter, LevelFilter (per-component thresholds), OnceFilter (log a key once); RateLimitFilter later
├── handlers.py      Phase 3: RotatingFileHandler (json, 0600), RingBufferHandler (for /admin/logs)
├── uvicorn_logs.py  takeover: route uvicorn's loggers through our handler; chatter to DEBUG; "running on" → Ready; access lines re-rendered
├── _text.py         durations, short request ids, key=value value quoting
└── tracebacks.py    pretty-mode exception rendering (rich.traceback, frames from starlette/anyio/uvicorn suppressed, max 8 frames)

Redaction runs inside the formatters on the rendered text (see Status).

src/ollabridge/api/request_log.py   pure-ASGI RequestLogMiddleware + RequestContext (the per-request telemetry object)
```

Data flow:

```text
 handler code                middleware                     logsetup
 ─────────────               ──────────────────             ──────────────────────────────────
 ctx = request_ctx(request)  on http.request:                 record ──► ContextFilter (adds request_id, job, node)
 ctx.model = …                 bind(request_id, client,…)            ──► RedactionFilter (handler-level)
 ctx.route = "ollama/local"    t0 = monotonic()                      ──► Formatter (pretty | plain | json)
 ctx.tokens_in/out = …       on http.response.start:                 ──► stderr        (always)
 ctx.error_code = …            status captured                       ──► rotating file (OLLABRIDGE_LOG_FILE)
                             on body complete:                       ──► ring buffer   (dashboard Activity, Phase 3)
                               emit one "request" record
                               fan out: TraceStore, RequestLog, flow_events
```

Why not structlog or loguru: both would wrap the same stdlib records to reach
uvicorn and third parties, the migration touches 56 modules for no new
capability, and the three things we need (JSON renderer, context injection,
pretty renderer) are about 300 lines here. Why not `rich.logging.RichHandler`:
its fixed layout (time | level | message | `file:line`) is not the column
layout above, it soft-wraps long key=value tails, and it is markedly slower
per record. Rich is still used for colour/terminal detection (honours
`NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`) and for pretty tracebacks.

### 4.1 Uvicorn takeover

`uvicorn.run(..., log_config=None, access_log=False)`. With `log_config=None`
uvicorn adds no handlers; its `uvicorn` and `uvicorn.error` loggers propagate
to root and render as component `server`. Their startup chatter ("Started
server process", "Waiting for application startup", "Application startup
complete", "Uvicorn running on") is mapped to DEBUG by a filter; the lifespan
hook emits our single `Ready` line instead. Access logging is replaced by the
`request` middleware, which knows the model and route; uvicorn's never can.

For `--reload` and `--workers > 1`, uvicorn re-imports the app in child
processes that never ran the CLI. The CLI therefore **resolves the config and
exports it to `OLLABRIDGE_LOG_*` environment variables before `uvicorn.run`**;
`ensure_logging_configured()` in `create_app()` reads the same variables, so
every process renders identically. The Docker `CMD` gets the same treatment
for free, and should switch to `ollabridge start --no-open` so Docker and
local share one path (see §9).

### 4.2 Request context

`RequestContext` is a small mutable dataclass stored on `request.state` and
in a `ContextVar` for the duration of the request:

```python
@dataclass
class RequestContext:
    request_id: str
    method: str
    path: str
    client: str | None
    started: float
    model: str | None = None
    resolved_model: str | None = None
    route: str | None = None          # "ollama/local" | "relay/<node>" | "direct/<node>" | "homepilot" | "<provider_id>"
    provider: str | None = None
    device: str | None = None
    fallback: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_estimated: bool = True
    error_code: str | None = None     # "upstream_unreachable", "rate_limited", "invalid_api_key", …
    status: int | None = None
```

Handlers fill it as they learn things (today they fill three different
ad-hoc call sites). At completion the middleware emits the `request` record
and fans out to the trace store, the SQLite request log and the flow-metrics
deque — one truth, one place. This also removes ~60 duplicated lines from the
success and error branches of `chat_completions`.

The middleware is **pure ASGI** (wraps `send` to capture
`http.response.start`), not `BaseHTTPMiddleware`, so it adds no buffering and
is safe for streaming responses when they arrive.

---

## 5. Configuration surface

| Setting | Env | CLI (`ollabridge start`) | Default | Notes |
|---|---|---|---|---|
| Level | `OLLABRIDGE_LOG_LEVEL` | `--log-level` | `info` | `LOG_LEVEL` still read as a deprecated alias. CLI default changes from `warning` to `info` so the app is not silent by default. |
| Per-component levels | `OLLABRIDGE_LOG_LEVELS` | `--log-level catalog=debug` (repeatable) | — | Comma list; accepts component names or full logger names: `catalog=debug,server=info,httpx=warning` |
| Format | `OLLABRIDGE_LOG_FORMAT` | `--log-format` | `auto` | `auto` → `pretty` when stderr is a TTY and `NO_COLOR` is unset, else `plain`. `json` for containers. |
| File sink | `OLLABRIDGE_LOG_FILE` | `--log-file [path]` | off | Always JSON, rotating 20 MiB × 5, mode 0600. Bare `--log-file` → `~/.ollabridge/logs/gateway.jsonl`. |
| Quiet paths | `OLLABRIDGE_LOG_QUIET_PATHS` | — | `/health,/ui,/admin/flow-metrics,/admin/cloud/status,/admin/connection-info,/admin/settings,/admin/source-health,/consumer-nodes` | The dashboard's polling set. Logged at DEBUG unless status ≥ 400. `/v1/models` stays loud: clients call it too. |
| Request log | `OLLABRIDGE_LOG_REQUESTS` | `--no-request-log` | on | Turns the `request` component off entirely (telemetry sinks unaffected) |
| Colour | `NO_COLOR`, `FORCE_COLOR` | — | — | Standard semantics |
| Timezone | `OLLABRIDGE_LOG_UTC` | — | off (local + offset) | JSON is always UTC |

Precedence: CLI flag → `OLLABRIDGE_*` env → `.env` → default. The resolved
config is printed in the session header so a pasted log is self-describing.

`ollabridge doctor` gains a **Logging** section: effective level and format,
redaction active, file sink path and permissions, uvicorn access log off.

---

## 6. Startup lifecycle

1. **Makefile** prints nothing but a one-line hint (`Starting OllaBridge on
   :11435 — Ctrl+C to stop`). The CLI owns the banner; two banners is one too
   many.
2. **CLI** resolves config, exports `OLLABRIDGE_LOG_*`, configures logging,
   emits `Starting` with the resolved bind/auth/model, and starts the existing
   readiness thread. **The Rich panel moves into that thread**, printed when
   `/health` returns 200, immediately followed by the browser open. The panel
   shrinks: dashboard URL, API base, key, auth mode, model, one join-token
   block (not two), the node command on its own line, and
   `Logs: --log-level debug · --log-format json · ollabridge doctor`.
3. **Lifespan** (replacing `@app.on_event`) runs subsystem init and emits one
   INFO per subsystem plus `Ready in Ns`. Subsystem detail moves to DEBUG:
   catalog file paths, per-provider registration, per-alias counts, HF
   snapshot absence.
4. **SecretStore** becomes a per-process singleton (`functools.lru_cache` on
   `provider_ops._store`, and the seeder receives the store once). The
   `OLLA_SECRET` warning is also wrapped in `OnceFilter` as defence in depth,
   so a future second constructor cannot bring the spam back.
5. **Browser open**: run `webbrowser.open()` with the child's stdout/stderr
   redirected to `DEVNULL`; under WSL prefer `wslview`, then
   `powershell.exe Start-Process`, and fall back to a single dim line
   `Open http://localhost:11435/ui in your browser` when nothing works.

Before/after line count for the pasted run: **≈ 95 lines → 6 log lines + one
panel**, and the panel is true when it prints.

---

## 7. Steady state

- **Catalog sync** returns a `changed` flag and a delta (added/removed/
  promoted/demoted ids). INFO only when `changed`, naming the delta. The
  per-run line is DEBUG. Today's `upserted=3 promoted=3` counts rows touched,
  which is why every run looks like a change.
- **Reachability** already does the right thing (first failure WARN,
  reminders, recovery INFO); the `runtime` component name and `req=` context
  are the only additions.
- **Relay** gains `Node joined` / `Node left` INFO/WARN lines in
  `hub.attach`/`hub.detach` (there are none today), with `node=`, model count,
  capacity and a `reason=`.
- **Cloud bridge** keeps its state-transition lines; `Cloud request … op=…`
  per-request INFO moves to the `request` middleware pattern (it is a request).
- **Scheduler and background tasks** bind `job=<name>` in the context so a
  traceback from a background task names its job.

---

## 8. Security and privacy

- `RedactionFilter` is installed **on every handler** (stderr, file, ring
  buffer), so it scrubs records from uvicorn and libraries, not only ours. The
  JSON formatter also runs `redact_text` over string field values and
  `redact_mapping` over `extra` dicts.
- The API key, pairing code and join token are printed by the CLI panel only.
  They never pass through `logging`, so they can never land in a file sink or
  the dashboard feed.
- File sink is created with mode 0600 and lives under `~/.ollabridge/logs/`;
  `doctor` checks the permission like it does for `secrets.enc`.
- Prompt and completion content are never fields. `prompt_logging` stays a
  separate, opt-in trace flag as documented in `docs/PRIVACY.md`.
- Tracebacks in pretty mode never show locals (`show_locals=False`).

---

## 9. Entry points

| Entry | Today | Target |
|---|---|---|
| `ollabridge start` | `configure_logging(level)` + uvicorn default config | Full resolve/export/configure; uvicorn takeover |
| bare `uvicorn ollabridge.api.main:app` (Dockerfile) | `ensure_logging_configured()` without uvicorn takeover | Same env-driven configure incl. takeover, header from the lifespan. `CMD` unchanged; `OLLABRIDGE_LOG_FORMAT=json` when shipping |
| `ollabridge-node join` | none (agent logs fall to last-resort handler: no timestamps, INFO dropped) | `configure_logging()` with `node=<id>` bound in context |
| `ollabridge-mcp` | none | `configure_logging()`; **stderr only** (stdout is the MCP transport) |
| tests | `caplog` | unchanged; `configure_logging` stays idempotent and `caplog` keeps working because our handler is on root |

---

## 10. Rollout

### Phase 1 — Foundation (≈ 2 days)

- `core/logsetup/` package: config, formatters (pretty/plain/json), components
  map, context filter, redaction + once filters, uvicorn takeover, tracebacks.
- Env/CLI surface from §5; CLI exports config to env before `uvicorn.run`.
- All four entry points configured.
- Session header; `Ready` line from a lifespan hook (migrate off `on_event`).
- Tests: formatter snapshots (frozen time, colour off), JSON parses with the
  Appendix A keys, redaction of a `uvicorn.error` record, idempotence, env
  precedence.

Acceptance: `make start` shows one format; `OLLABRIDGE_LOG_FORMAT=json` yields
valid JSON lines; a key-shaped string logged by any logger is scrubbed.

### Phase 2 — Signal (≈ 2 days)

- `RequestLogMiddleware` + `RequestContext`; `chat_completions` and
  `embeddings` fill the context; fan-out to trace store / request log / flow
  events moves into the middleware. Quiet paths.
- Startup collapse: provider summary line, catalog summary, paths to DEBUG,
  SecretStore singleton, HF snapshot to DEBUG.
- Catalog sync on-change; provider router per-attempt lines to DEBUG; relay
  join/leave lines.
- Ready-gated banner in the readiness thread; Makefile banner removed;
  `xdg-open` noise fixed.

Acceptance: idle gateway with dashboard open emits zero INFO lines per minute;
one chat request emits exactly one `request` line with `model`, `route`,
`tokens`, latency; the pasted startup becomes ≤ 8 log lines plus the panel.

### Phase 3 — Enterprise sinks and UX (≈ 3 days)

- Rotating JSON file sink; `doctor` Logging section.
- `ollabridge logs` command: `--follow`, `--since 10m`, `--component request`,
  `--level warn`, `--json`, reading the file sink (or the ring buffer over
  `/admin/logs` when the gateway is running without a file).
- `RingBufferHandler` (last 2 000 records) + `GET /admin/logs` +
  `GET /admin/logs/stream` (SSE) → dashboard **Activity** panel with level and
  component filters, click-through from a `request` line to the trace.
- Docs: `CONFIGURATION.md` (env table), `DEPLOYMENT_HARDENING.md` (fix the
  redaction claim, add shipping guidance), `CLI.md`.

---

## 11. Testing strategy

| Test | Asserts |
|---|---|
| `test_pretty_layout` | fixed columns with frozen time and `NO_COLOR`; snapshot |
| `test_json_schema` | every record parses; required keys present; `ts` ends in `Z` |
| `test_redaction_on_foreign_logger` | `logging.getLogger("uvicorn.error").error("key sk-ant-…")` → `[REDACTED]` on stderr and file |
| `test_configure_idempotent` | two calls → one handler; level adjusted |
| `test_env_precedence` | CLI beats env beats `.env` beats default |
| `test_uvicorn_children_inherit` | `export_to_env()` round-trips through `LogConfig.from_env()` |
| `test_one_request_line` | `TestClient` POST → exactly one `request` record with `model`, `route`, `status`, `latency_ms` |
| `test_quiet_paths` | `GET /health` → DEBUG only; `GET /health` 500 → ERROR |
| `test_secret_store_warns_once` | seven `SecretStore()` → one WARN |
| `test_catalog_sync_silent_when_unchanged` | extends `test_local_catalog_unreachable.py`: unchanged run → no INFO |
| `test_no_prompt_fields` | a `request` record never contains `messages`, `content`, `prompt` keys |

---

## 12. Risks and mitigations

- **Behaviour change for anyone parsing today's format.** Nobody can be,
  there is no stable format today; still, `plain` keeps `level` and logger
  tokens parsable and the change is called out in the release notes.
- **Pure-ASGI middleware ordering.** It must be the outermost middleware to
  time the whole request and see the final status; add it last in
  `create_app()` (Starlette applies middleware in reverse order of addition).
- **Rich colour detection in odd terminals** (Windows ConHost, CI). `auto`
  falls back to `plain` whenever `Console.is_terminal` is false; `FORCE_COLOR`
  overrides.
- **Per-request cost.** One formatted record and one dict fan-out per request,
  microseconds against LLM latencies of seconds.
- **Context leakage across requests.** `ContextVar` is per-task; the
  middleware resets the token in `finally`.

---

## 13. Found in passing (not logging, worth a ticket each)

- `docker-compose.yml` sets `OLLBR_HOST`, `OLLBR_PORT`, `OLLBR_OLLAMA_BASE_URL`,
  `OLLBR_AUTH_REQUIRED`; `Settings` has no `env_prefix` and nothing reads
  them. The Dockerfile also exposes `11343` while everything else uses `11435`.
- The "Online" panel prints before the bind; a busy port today shows a green
  panel followed by a uvicorn error.
- `paths.audit_log_file()` is declared and never written; either implement
  the audit trail (Phase 3 could route `admin` component records there) or
  drop it from `paths.py`'s docstring.

---

## Appendix A — JSON field dictionary

| Field | Type | Present | Meaning |
|---|---|---|---|
| `ts` | string | always | ISO-8601 UTC, milliseconds, `Z` |
| `level` | string | always | `debug` `info` `warning` `error` `critical` |
| `component` | string | always | short name (Appendix B) |
| `logger` | string | always | full logger name |
| `msg` | string | always | rendered message, redacted |
| `pid` | int | always | process id |
| `version` | string | always | OllaBridge version |
| `request_id` | string | in-request | full `req_…` id (also in `X-Request-ID`) |
| `method`, `path`, `status`, `latency_ms`, `client` | — | `request` | HTTP facts |
| `model`, `resolved_model` | string | `request` | requested vs served model id |
| `route` | string | `request` | `ollama/<node>` · `relay/<node>` · `direct/<node>` · `homepilot` · `<provider_id>` |
| `provider`, `device` | string | `request` | as in the trace store |
| `fallback` | bool | `request` | a provider failed and another served |
| `tokens_in`, `tokens_out`, `tokens_estimated` | int, int, bool | `request` | upstream counts or estimate |
| `error_code` | string | errors | `upstream_unreachable` `rate_limited` `invalid_api_key` `tools_unsupported` `model_not_found` `provider_error` `internal` |
| `job` | string | background | `catalog-sync` `cloud-bridge` `hf-catalog-sync` |
| `node_id` | string | relay/node | node identifier |
| `exc_type`, `exc_message`, `stack` | string | exceptions | redacted |

## Appendix B — Component map

| Logger prefix | Component |
|---|---|
| `ollabridge.api.requests` | `request` |
| `ollabridge.api.relay` | `relay` |
| `ollabridge.api.*`, `ollabridge` | `gateway` |
| `ollabridge.addons.providers.router` | `router` |
| `ollabridge.addons.providers.secret_store` | `secrets` |
| `ollabridge.addons.providers.hf_catalog.*` | `hfcatalog` |
| `ollabridge.addons.providers.*` | `providers` |
| `ollabridge.addons.local_catalog.*` | `catalog` |
| `ollabridge.core.reachability`, `ollabridge.providers.ollama_client` | `runtime` |
| `ollabridge.cloud.*` | `cloud` |
| `ollabridge.node.*` | `node` |
| `ollabridge.tracing`, `ollabridge.db` | `store` |
| `uvicorn`, `uvicorn.error` | `server` |
| `httpx`, `httpcore`, `websockets`, `watchfiles`, `asyncio`, `multipart` | package name; floored at WARNING unless a rule names them |
| other `ollabridge.*` modules | last dotted segment, max 10 chars |
| other third-party loggers | package name (first segment), max 10 chars |

The full, current map is `_PREFIXES` in `core/logsetup/components.py`.
