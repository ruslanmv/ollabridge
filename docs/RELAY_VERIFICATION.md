# Verifying the Cloud Relay End to End

The relay lets clients call `https://<your-cloud>/v1/...` and have the
request answered by a model running on your own machine, over an
outbound-only WebSocket. This page shows how to **prove** that path works —
without sending real traffic from a second machine — using the
`ollabridge doctor` suite.

Implementation references: `src/ollabridge/doctor/checks.py` (cloud/relay
checks), `src/ollabridge/doctor/e2e.py` (end-to-end probe), and the wire
protocol in the cloud repo at `ollabridge-cloud/docs/PROTOCOL.md`.

---

## 1. Prerequisites

1. **Paired with the cloud:** `ollabridge login` completed
   (credentials at `~/.ollabridge/cloud_device.json`).
2. **Gateway running** with at least one local model:
   `ollabridge start` (the in-process bridge connects the relay and
   registers your models).
3. Optional, for cloud-side verification: a **cloud API key** exported as
   `OLLABRIDGE_CLOUD_API_KEY` (an `ob_*` key minted in the cloud dashboard).
   Without it the cloud-side steps are reported as SKIP, not FAIL.

`ollabridge doctor` with no subcommand runs every applicable section
(local, cloud, relay when paired, providers, security). The subcommands below
isolate the relay path.

## 2. `ollabridge doctor cloud` — credentials and posture

Checks, in order:

- Cloud credentials found (`~/.ollabridge/cloud_device.json`, device id)
- Cloud API reachable (`/health`, falling back to `/`)
- Device paired (device id → cloud URL)
- Sync enabled (WARN if disabled, with the `ollabridge sync enable` hint)
- Prompt logging off (WARN if you enabled it)

```
$ ollabridge doctor cloud
Cloud
  ✅ Cloud credentials found   device dev_a1b2c3
  ✅ Cloud API reachable       https://api.ollabridge.com
  ✅ Device paired             dev_a1b2c3 → https://api.ollabridge.com
  ✅ Sync enabled              metadata sync is on
  ✅ Prompt logging            disabled (default)
```

If you are not paired, the section fails with `Run:  ollabridge login` and
notes that cloud is optional — local mode works without it.

## 3. `ollabridge doctor relay` — the WebSocket path

`ollabridge doctor relay [--timeout 10] [--json]` opens its own probe
connection and verifies each step of the relay protocol:

1. **WSS connect** to `wss://<cloud-host>/relay/connect` with
   `Authorization: Bearer <device_token>`.
2. **Hello / registration** — sends the `hello` frame with the local model
   list and `["chat", "models"]` capabilities; per protocol the cloud updates
   the device's metadata.
3. **Model list sent** — the count of local models registered (WARN if
   Ollama reports zero models).
4. **App-level ping/pong** — sends `{"type":"ping"}` and waits for
   `{"type":"pong"}` (the heartbeat that keeps `last_seen` fresh
   server-side). A miss is a WARN, because WS-protocol keepalive still
   applies.
5. **Reconnect test** — opens a second session to prove re-connection is
   accepted (the production bridge reconnects with 2/4/8/16/30 s backoff).
6. **Cloud-side model comparison (optional)** — with
   `OLLABRIDGE_CLOUD_API_KEY` set, fetches the cloud's `/v1/models` and
   verifies your local models are visible through the relay. Without the
   key this step is SKIP.

```
$ ollabridge doctor relay
Relay
  ✅ Cloud credentials                       device dev_a1b2c3
  ✅ WSS connection established              wss://api.ollabridge.com/relay/connect
  ✅ Device registered                       hello accepted
  ✅ Model list sent                         3 models
  ✅ Ping/pong                               app-level heartbeat OK
  ✅ Reconnect test                          second connection accepted
  ⏭  Cloud /v1/models includes local models  set OLLABRIDGE_CLOUD_API_KEY to verify the cloud-side model list
```

With the cloud key:

```
$ export OLLABRIDGE_CLOUD_API_KEY=ob_...
$ ollabridge doctor relay
  ...
  ✅ Cloud /v1/models includes local models  3/3 visible
```

## 4. `ollabridge doctor e2e` — a real request through the full path

`ollabridge doctor e2e [--port 11435] [--model <id>] [--timeout 120] [--json]`
sends one fixed, non-sensitive prompt (`"Reply with the single word: pong"`)
along each path:

- **Local path (always):** client → local gateway → local model. Requires a
  local API key (the one printed by `ollabridge start` or `API_KEYS`).
- **Cloud path (optional):** client → cloud → relay → this device → model →
  back. Requires pairing **and** `OLLABRIDGE_CLOUD_API_KEY`; otherwise SKIP.

It reports a latency breakdown: total cloud round-trip, estimated **relay
overhead** (cloud total minus local total for the same model and prompt), and
model time.

```
$ ollabridge doctor e2e
End-to-end
  ✅ Test model available          llama3.1:8b
  ✅ Local request path            842 ms (client → local gateway → llama3.1:8b), tokens in/out: 14/3
  ✅ Cloud relay path              total 1170 ms, est. relay overhead 328 ms, model 842 ms
                                   (route: client → cloud → relay → dev_a1b2c3 → llama3.1:8b), tokens in/out: 14/3
  ✅ Prompt logging during test    disabled (default)
  note: Fallback was not exercised by this probe (single fixed route).
```

## 5. `--json` for automation

Every doctor command accepts `--json` and exits non-zero when any check
fails, so the suite drops into CI/monitoring directly:

```bash
ollabridge doctor relay --json | jq '.sections[] | .results[] | {name, status}'
ollabridge doctor e2e --json   # exit code 1 on failure
```

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cloud credentials: Cloud credentials not found.` | Never paired, or `cloud_device.json` deleted | `ollabridge login` |
| `WSS connection established: credentials rejected (expired or revoked token)` (close code 4401/401) | Device token expired or revoked in the dashboard | Re-pair: `ollabridge login` |
| `Cloud API reachable: FAIL` | Cloud down, wrong URL, firewall blocking outbound 443 | Check network; confirm `--cloud` / `OLLABRIDGE_CLOUD_URL`; try again |
| e2e cloud path: `Device offline` (`DEVICE_OFFLINE`) | Gateway not running, so no relay connection registered | `ollabridge start`, then `ollabridge doctor relay` |
| e2e cloud path: model not found / 404 | Model not registered with the cloud (gateway restarted, model pulled after connect) | Keep the gateway online; the bridge re-registers models periodically; re-check |
| `Model list sent: no local models detected to register` | Ollama has no models | `ollama pull llama3.1` |
| e2e cloud path: HTTP 401/403 | `OLLABRIDGE_CLOUD_API_KEY` invalid or revoked | Mint a new `ob_*` key in the cloud dashboard |
| Cloud path SKIP | `OLLABRIDGE_CLOUD_API_KEY` not set | Export a cloud API key; SKIP is expected, not an error |
| Streaming responses arrive all at once via the relay | Known limitation: the cloud protocol defines `delta`/`done` streaming frames, but the local bridge currently answers every relay request with a single `res` frame — streaming over the relay is **buffered** | Tracked as a cross-repo compatibility gap (see `docs/AUDIT_ENTERPRISE_READINESS.md` §6 and the roadmap); local `/v1` streaming is unaffected |

## 7. What "verified" means

When `doctor cloud`, `doctor relay`, and `doctor e2e` are all green, you have
proven, with no second machine involved:

- your device token is valid and the cloud accepts your WSS handshake;
- your models are registered and (with a cloud key) visible at the cloud's
  `/v1/models`;
- heartbeats and reconnection work;
- a real OpenAI-style request travels client → cloud → relay → your device →
  model and back, with measured relay overhead.

Day-to-day visibility after that: `ollabridge traces list` shows, per
request, whether the cloud relay was involved (`relay` column) — with no
prompt content ever stored.
