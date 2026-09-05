# The avatar bridge — one link, three transports

How **yourfriend.online** reaches a HomePilot, and why the user configures none of it.

This page is the whole workflow across three repositories. It is written for whoever has to
change it next, so it says what each piece is for and what it would break to remove.

---

## The user's side of it

One link. The same one they made to get models.

```
Settings ▸ Provider ▸ OllaBridge     ← base URL + pairing code
Settings ▸ Behavior Engine ▸ Enable  ← one checkbox
```

Then a status line, and nothing else:

```
HomePilot connected through OllaBridge — directives, curiosity, vision, panels, meetings.
```

There is no HomePilot address to type, no second token, and no toggle pairing the two. The
controls that used to ask for those still exist, behind **Advanced**, for the case where
somebody is not using OllaBridge at all.

---

## Why not just let the browser connect to HomePilot

It was built that way first, and it does not work anywhere the app is actually served.

| | What happens |
|---|---|
| Page on `https://yourfriend.online` | An HTTPS page may not open `ws://localhost:8000`. Mixed content, blocked, and the console error does not say so plainly |
| Page on a hosted build | `localhost` is the machine serving the page, not the user's PC |
| Credential | HomePilot's handshake wants a token. The avatar had no field to hold one, sent `""`, and HomePilot's verifier is a presence check — so the direct path was refused every time |

All three are solved by the same move: the socket goes to the bridge the user already talks
to, and the bridge is the thing running next to HomePilot.

---

## The three transports

Same client code in every case. The avatar sends the same frames and never learns which
transport carried them — that is the point.

### 1. Chat — already carrying most of it

```
avatar ──POST /v1/chat/completions──▶ OllaBridge ──▶ HomePilot persona
                                   ◀── x_directives, x_attachments, x_homepilot
```

`X-Client-Type: vr-chatbot` puts HomePilot in enriched mode, and every reply carries pose,
emotion and media directives. This needs no socket and no configuration, and it is why a
bridge too old to relay the session still leaves the avatar animated by her persona.

### 2. Session, local — a straight proxy

```
browser ──ws──▶ OllaBridge /v1/avatar/session ──ws──▶ HomePilot /avatar/session
```

The proxy reads exactly one frame, the `hello`, because that is where the token is. It
validates the browser's OllaBridge credential, swaps in HomePilot's key, and pumps everything
after that verbatim in both directions.

The swap is the feature, not an implementation detail: HomePilot's key never reaches the
browser, and the browser never needed a field to hold one.

### 3. Session, Cloud — one hop further

```
browser ──wss──▶ Cloud ──relay link──▶ your node ──ws──▶ HomePilot
```

The Cloud cannot reach your HomePilot; that is what the relay link is for. The session takes
the same path inference already takes, using two frames added for it:

| Direction | Frame | Answered? |
|---|---|---|
| Cloud → node | `req` | yes, with `res` |
| Cloud → node | **`sig`** | no |
| node → Cloud | `res` | — |
| node → Cloud | **`ev`** | no |

`sig` is not a `req` with its response ignored — a `req` allocates a future something must
resolve, and a session sends thousands of frames. `ev` is not a `res`, because it answers
nothing. It exists because HomePilot **starts turns of its own**, and request/response has
nowhere to put an unprompted message.

---

## Discovery, and what "too old" means

```
GET {ollabridge}/health
→ { "homepilot_enabled": true,
    "avatar": { "session": "/v1/avatar/session", "features": [...] } }
```

**Absence means no.** Every OllaBridge released before this feature omits the `avatar` block,
and the avatar reads that as "this bridge cannot relay the session". No handshake, no minimum
version, and nothing to upgrade to keep working.

That state is deliberately not an error. Transport 1 is unaffected, so she still gestures and
still shows media; what she loses is speaking first. Saying that is more useful than a flat
failure.

The block is also absent when HomePilot is enabled but the relay would not actually run — a
missing `websockets` install, say. Advertising a relay that then refuses every socket turns a
graceful degrade into a broken feature.

| `source` reported by the client | Meaning | Fix |
|---|---|---|
| `bridge` | Connected through OllaBridge | — |
| `manual` | A URL is typed under Advanced; it wins | — |
| `no-bridge` | No OllaBridge linked | Link one under Settings ▸ Provider |
| `no-homepilot` | Bridge linked, HomePilot off | Enable HomePilot in OllaBridge ▸ Local Runtimes |
| `bridge-too-old` | Bridge sees HomePilot, cannot relay | Upgrade OllaBridge |
| `bridge-unreachable` | No answer in 4 s | Check the bridge is running |
| `off` | Automatic discovery disabled | Clear `nexus_bd_session_auto` |

---

## Setting it up

**HomePilot** — one variable, and the channel mounts:

```bash
AVATAR_ENABLED=true make start
# look for: [avatar_director] enabled — session channel mounted at /avatar/session
```

**OllaBridge, local** — enable HomePilot under Local Runtimes. That is the whole setup; the
relay reads the same base URL and API key the connector uses.

**OllaBridge Cloud** — additionally set `HOMEPILOT_BASE_URL` where the node agent runs. It
advertises `avatar` in its hello, and the Cloud picks it for sessions. A node that does not
advertise it is never chosen.

**The avatar** — link OllaBridge, enable the Behavior Director, reload.

---

## Where the code is

| Repository | File | What it does |
|---|---|---|
| 3D-Avatar-Chatbot | `src/behavior/adapters/BridgeDiscovery.js` | Asks `/health`; reports, never acts |
| 3D-Avatar-Chatbot | `src/behavior/boot.js` | Chooses manual over bridge over off |
| OllaBridge | `src/ollabridge/api/avatar_session.py` | The proxy, and the credential swap |
| OllaBridge | `src/ollabridge/api/relay.py` | `sig`/`ev` frames and stream fan-out |
| OllaBridge | `src/ollabridge/node/avatar_link.py` | The node half, one session per stream |
| HomePilot | `backend/app/avatar_director/session.py` | `/avatar/session`, unchanged by this work |

---

## Things that will bite whoever changes this

**The proxy must stay a pipe.** It reads one frame and knows one message type. Every other
type, version bump and future field belongs to HomePilot and the client. A test asserts the
proxy names none of them, because an opinion here becomes a second implementation of one
protocol, drifting from the first.

**One authorisation, at one place.** The bridge decides who may connect, using its own
credentials. The node forwards the hello it was given rather than minting one. Two judgements
would mean two answers to one question.

**A vanished node must wake its streams.** Otherwise the browser holds a socket whose far end
is gone and shows a connected avatar that will never move again, until its own timeout minutes
later. `None` on the queue is the end-of-stream marker.

**Streams are per-session, not per-node.** One node may carry several browsers. Fan-out to all
of them would put one person's conversation in front of another.


## Meeting frames (HomePilot MS8)

HomePilot's MeetingSense records a meeting over this session rather than over a socket of its
own, because a hosted page cannot open one to `ws://localhost`. Three client types and one
server type ride the pipe:

```
client → server   meeting_start · meeting_audio · meeting_stop
server → client   meeting        (carrying a MeetingSense frame verbatim)
```

**OllaBridge does not know what any of those are, and must not learn.** It reads one frame —
the `hello`, because that is where the token is — swaps the credential, and pumps everything
after it verbatim in both directions. A test asserts the proxy source contains no meeting
vocabulary at all, because the moment it does there are two implementations of one protocol
and they start to drift.

### Why the tests compare bytes rather than objects

A proxy that round-tripped each frame through `json.loads`/`json.dumps` would pass a
compare-the-dictionaries test while reordering keys, dropping whitespace, and — the one that
would actually bite — re-encoding the base64 audio chunk it had no business touching. So the
fixtures are deliberately non-canonical JSON, and the assertion is string equality.

That distinction is not theoretical: the first version of the audio fixture happened to be
byte-for-byte what `json.dumps` produces by default, so a mutant that re-serialised every
relayed frame passed the whole suite. The fixtures now carry spacing `json.dumps` cannot
reproduce.

The same holds on the **cloud path**, where HomePilot is on the operator's machine and this
process cannot reach it. Frames ride the existing `sig`/`ev` relay with the raw frame *as the
payload string* — `avatar_send` forwards a `str` untouched and only serialises a `dict` — which
is precisely what keeps the byte guarantee true on the path that is harder to watch.

`/health` advertises `meetings` in the avatar feature list. That is a promise OllaBridge can
make honestly: it relays them because it relays everything. Whether the HomePilot behind the
bridge will *accept* a meeting is a different question, and HomePilot answers it itself with
`remote_ok` on `/v1/meetingsense/status`.
