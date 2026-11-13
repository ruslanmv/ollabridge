# OllaBridge — Endpoint Diagnosis

`ollabridge diagnose` measures **one endpoint** — a chat model (OpenAI-
compatible) or an MCP server over Streamable HTTP — and says how hard it can
be driven: its lower limits (the fastest it can answer), its upper limits
(the concurrency where more calls stop helping, its request limit), and the
settings that follow, for OllaBridge and for the client.

It is additive: a new command and a new package (`src/ollabridge/diagnose/`).
No existing behaviour changes, and nothing runs unless the command is invoked.

## Why

Two failures from the same week, both of the kind "too many calls":

**An MCP edge refused tool calls with HTTP 429.** The edge allowed 60 HTTP
requests a minute per key. The client opened a new MCP session for every
tool call, so one call cost four requests (`initialize`,
`notifications/initialized`, the call, end of session): 15 calls in a minute
were enough. The replay ran 15 tickets in parallel, made 28 calls in 2.5
minutes, and the client did not retry the 429. The tool call had succeeded
on the server; its result never reached the agent.

**A chat model timed out four times in a row.** The client allowed 60 s per
HTTP try and retried three times; the response step for a large prompt took
longer than 60 s every time, so one LLM call became 8 minutes of retries
followed by an escalation.

Both come down to numbers nobody had measured: requests per call, the
endpoint's limit, how long a large answer takes, how many calls can run in
parallel. The diagnosis measures them.

## Safety first

The diagnosis is meant to run against shared, production-like endpoints, so
the defaults are cautious and every risky step is opt-in:

| Guard | Default |
|---|---|
| Request budget (hard cap on HTTP requests) | 60 (chat), 40 (MCP); 200 with `--find-limit` |
| Time budget | 300 s (chat), 180 s (MCP) |
| Probe content | the one-word prompt `doctor e2e` uses; `max_tokens` 16 (128 for the one speed probe) |
| MCP methods | `initialize`, `ping` (or `tools/list` when the server has no `ping`), `tools/list`; no tool runs unless `--tool` names one |
| Early stop | the first rate-limit answer, an error rate of 20 %, or throughput falling below 80 % of the best level so far |
| Unusable endpoint | one request: a 401/404/429 on the first call ends the run |
| Reaching the limit on purpose | only with `--find-limit`, after a confirmation (it uses up the key's allowance for about a minute, for everyone sharing the key) |
| Writing a setting | only with `--apply <provider>`, after a confirmation; one provider's entry, nothing else |
| Secrets | API keys come from environment variables (`--api-key-env`, `--header NAME=ENVVAR`), never the command line; they are redacted from every message and never written to the report |
| Preview | `--plan` prints the levels and the maximum number of requests, and sends nothing |

## What it measures

### Chat endpoint

```bash
ollabridge diagnose chat --model <model>                                  # through this OllaBridge
ollabridge diagnose chat --base-url https://host/v1 --model <model> --api-key-env MY_KEY
```

1. **Baseline:** three single requests. The first is on a cold connection;
   the difference to the others is the connection setup, which every call
   that does not reuse a connection pays again.
2. **Speed:** one streamed answer of up to 128 tokens: time to first token
   and tokens per second. An endpoint that buffers the whole answer is
   noted (time to first token is then the whole answer time).
3. **Prompt sizes** (`--prompt-tokens 2000,8000,24000`): one request per
   size, to see how the answer time grows with the input. With
   `--client-timeout 60 --output-tokens 800` each size is checked against
   the caller's limit, projecting a long answer from the measured speed.
4. **Concurrency sweep** (`-c 1,2,4,8`): a few requests per level, each
   level at least two rounds. Ends at the first sign of a limit.
5. **Limit** (`--find-limit`): sends until the first refusal, stops, then
   waits the `Retry-After` it was given (or tries every 15 s) to time the
   recovery.

### MCP endpoint

```bash
ollabridge diagnose mcp --url https://host/mcp --api-key-env MCP_KEY
ollabridge diagnose mcp --url https://host/mcp --api-key-env MCP_KEY \
  --assume-limit 60 --call-seconds 11 --calls-per-task 18 --task-seconds 150
```

The handshake, three pings on one session, `tools/list`, and **one call with
a session of its own**, which counts what such a call costs at the edge (4
requests, or 3 for a server that issues no session id). Then the sweep, and
`--find-limit` as for chat. The session is always ended, whatever happens.
`--tool <name> --args '{...}'` times a real tool call; only name a tool that
reads.

### Where the limit comes from

In order of preference:

1. `--assume-limit N`: the number the endpoint's owner gave you.
2. **Response headers**, without ever reaching the limit: IETF
   `RateLimit-*` / `RateLimit-Policy` (both drafts), OpenAI-style
   `x-ratelimit-*-requests`, and the older `x-ratelimit-*`.
3. **Observed:** the requests the endpoint accepted in the 60 s before its
   first refusal. The real limit is that or a little higher, and lower for
   you when other clients share the key.

Refusals are recognised as HTTP 429, or a 400/403/503 whose body says "rate
limit" (an Open WebUI server answers HTTP 400 `{"detail": "Rate limit
exceeded..."}`). The report says which, whether `Retry-After` was sent, and
how long the endpoint took to accept a request again.

## How the recommendations are made

| Recommendation | Rule |
|---|---|
| Best concurrency | The lowest level within 10 % of the peak throughput, among levels where every request succeeded. Above it, more parallel calls buy latency, not answers. |
| Requests a minute | 80 % of the known limit. With no known limit no pace is invented; the concurrency cap alone bounds the load. |
| On a rate limit | Wait and retry. Cooldown: the endpoint's `Retry-After`, else the measured recovery time, else 15 s. |
| Max wait in OllaBridge | The caller's timeout per try, less the slowest answer and 5 s, so OllaBridge answers with a 429 and a `Retry-After` before the caller gives up. |
| Caller timeout per try | 1.5 × the slowest answer measured or projected, at least 30 s. A caller that gives up first and retries adds load to an endpoint that is already slow. |
| MCP tool calls a minute | `0.8 × limit ÷ requests per call`, for a session per call and for a kept session. |
| MCP parallel calls | Tool calls a minute × seconds per call ÷ 60, capped at the highest concurrency the sweep measured clean. |
| MCP parallel tasks | Tool calls a minute ÷ (calls per task × 60 ÷ task seconds). |

Worked example, the MCP edge above (60 a minute, 11 s per call, 18 calls in
a 150 s ticket):

| | Session per call | Kept session |
|---|---|---|
| HTTP requests per call | 4 | 1 |
| Tool calls a minute (at the limit) | 15 | 60 |
| Tool calls a minute (planned, 80 %) | 12 | 48 |
| Parallel tool calls | 2 | 8 |
| Parallel tickets | 1 | 6 |

Fifteen parallel tickets needed about 108 tool calls a minute: 432 requests
with a session per call, 108 with kept sessions. Raising the edge to 300 a
minute is enough for 8 tickets with a session per call, or 33 with kept
sessions (`--assume-limit 300` prints these).

## Applying the result

```bash
ollabridge diagnose chat --model openwebui/<model> --client-timeout 60 --apply openwebui
```

`--apply <provider id>` saves the recommended Settings → Rate limits entry
for that provider (the id the dashboard lists, e.g. `openwebui` or
`byok-<name>`): through the running gateway when it is up (applies at once,
no restart), else in `runtime_settings.json`. The report prints the value
before and after; every other provider and the inbound limit are left as
they are.

## Auditing the current settings

```bash
ollabridge diagnose settings
```

Reads Settings → Rate limits from the running gateway (or the saved file when
it is not running) and flags, for many calls at once:

- a provider **in use** that fails fast on a rate limit: a burst over its
  limit is a 429 for every caller at once, with no queue and no retry;
- a provider that retries but has no pace or concurrency cap;
- an inbound limit that a parallel run from one client would hit;
- the timeouts a caller must outlast.

It exits with status 1 when it has a warning, so it can gate a CI job.

## Notes for heavy runs through OllaBridge

- **Keep `--workers 1`** when provider limits are set: the pacing state is
  per process, so N workers allow N times the configured rate and
  concurrency.
- A caller's timeout per try must cover **OllaBridge's max wait plus the
  answer time**; the report prints that sum as "callers wait at least".
- Retry 429 and 503 after the `Retry-After` the answer carries. OllaBridge
  sends one on its own refusals (rate limit, offline network).

## Output

Text by default; `--json` prints the full report, `--save report.json`
keeps a copy. The JSON has `target`, `safety` (requests used, budget, why it
stopped), `baseline`, `prompt_sizes`, `levels`, `rate_limit`, `limits`
(`lower`, `upper`) and `recommendations`.

## Tests

`tests/test_diagnose.py` drives fake chat and MCP endpoints (an
`httpx.MockTransport` with a real sliding-window limit and a capacity) and
pins: header parsing, the sweep stopping at the knee and at the first
refusal, the hard request budget, one request against an unusable endpoint,
`--plan` and a declined `--find-limit` sending nothing, the MCP request
count per call and the session always being ended, no tool without
`--tool`, the worked example above, the settings audit, and `--apply`
changing one provider only.
