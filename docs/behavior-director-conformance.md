# Behavior Director bridge conformance — findings

**Batch B18.** Tests only. Nothing in this batch changed bridge behaviour, and nothing in it
was licensed to: where a transform is lossy, it is documented here and filed as a finding
with a proposed additive fix and its own batch.

Run: `pytest tests/conformance` (130 tests).

## What is being protected

The 3D avatar client now depends on two channels surviving the chat path, and both are
**invisible to the user**. That is what makes them dangerous to break: nothing renders
differently, the avatar simply stops moving, and it can ship.

| Channel | Shape | Consumer |
|---|---|---|
| Emote tags (spec v1.1 §6.8) | `[[emote:<name> <intensity>]]` | `src/behavior/adapters/LLMTagAdapter.js` |
| Motion blocks | ` ```motion ` fenced JSON | `src/xr/MotionBlockParser.js` |

Plus one request-direction dependency: §6.8's contract is **appended to the persona system
prompt**, so a bridge that trims the prompt silently removes the instruction that produces
the tags in the first place.

## Result

| Claim | Verdict |
|---|---|
| Emote tags survive the response path | ✅ every fixture, every shape |
| Motion blocks survive the response path | ✅ every fixture, including untagged fences |
| A reply carrying both keeps both | ✅ |
| System prompt is not truncated | ✅ no cap on this path at any length tested (100 KB) |
| Re-chunking cannot break reassembly | ✅ — the chat path is unary; there is no chunk boundary to move |
| Byte-exact | ⚠️ **no** — three documented transforms, none of which breaks either channel |

**13 of 14 fixtures round-trip byte-exact.** The fourteenth changes because of a deliberate
`[show:…]` strip, and both channels survive it.

## Headroom

§6.8's contract is **347 bytes**. `_message_to_wire` and `_content_to_text` impose no length
limit — a 100 KB system prompt arrives at the upstream runtime whole — so the headroom is
the upstream model's context window minus the persona, and is not something this repository
constrains. `HomePilotConnector.chat` forwards `messages` untouched.

347 bytes against a persona prompt measured in kilobytes is not a meaningful cost. **No
action.**

## Findings

All three live in `_normalize_content` (`src/ollabridge/api/main.py`), all three predate the
Behavior Director, and **none of them breaks tag or block parsing**. They are filed because
"byte-exact" is what B18 was asked to verify, and the honest answer is that this function is
not — so the next person to widen it should find this page rather than an outage.

### F1 · Leading and trailing whitespace is stripped — *low, no action proposed*

```
'[[emote:happy]] hi\n'  →  '[[emote:happy]] hi'
```

`.strip()` at the end of the transform. Harmless for both channels: the client's tag parser
tidies trailing whitespace itself and a fence does not care what follows it.

### F2 · Three or more consecutive newlines collapse to two — *low, watch*

```
'a\n\n\n\n\nb'  →  'a\n\nb'
```

Applies **inside** a fenced block as well as outside it:

```
'```motion\n{"commands":[\n\n\n\n\n{"type":"nod"}\n]}\n```'
  → '```motion\n{"commands":[\n\n{"type":"nod"}\n]}\n```'
```

Safe today, because the fence regex is `[\s\S]*?` and JSON is whitespace-insensitive. It
would **not** be safe for a future channel that used blank lines as a delimiter, and it is a
content transform applied inside a region the bridge does not understand.

*Proposed additive fix, should a channel ever need it:* run the collapse only outside fenced
regions. Ten lines, no behaviour change for any existing traffic. **Its own batch** — this
one may not touch bridge behaviour.

### F3 · A reply that is valid JSON with a `text` key is unwrapped — *medium, escalated*

```
'{"type":"final","text":"…"}'      →  '…'      (intended: a known HomePilot artifact)
'{"text": "the field you asked about"}'  →  'the field you asked about'   (not intended)
```

The unwrap is keyed on **shape**, not on a marker. A persona that legitimately answers with a
JSON object containing a `text` key — a tool result, a schema example, a code answer — has
that object silently replaced by one of its fields, and the caller cannot tell.

This is the sharpest of the three and the only one worth calling a defect. It is also
pre-existing, unrelated to the Director, and squarely out of scope for a tests-only batch.
Two things limit it: it needs the whole reply to parse as JSON (prose that merely *starts*
with a brace is untouched, verified), and whatever it keeps it keeps whole — a tag inside the
`text` field survives.

*Proposed additive fix:* require the artifact's own marker before unwrapping — the observed
shape is `{"type":"final", …}`, so gating on `parsed.get("type") == "final"` removes the
false positive and keeps the intended behaviour. Roughly a one-line change plus a test.
**Its own batch, and its own review.**

## OllaBridge Cloud

The hosted gateway (`ollabridge-cloud`, `tests/conformance/`, 133 tests) applies **no content
transform at all** — `result.content` reaches the response body unchanged, and a test asserts
the route's source contains no `re.sub`, `.strip()`, `.replace(` or `normalize`.

So the two bridges behave differently on F1–F3. That difference is now pinned on both sides,
which makes it deliberate rather than drift: an avatar routed through the cloud gets
byte-exact replies, and one routed locally gets replies with the three transforms above.

## Streaming

Neither bridge streams the chat path. Both build one response body from one upstream reply,
so there is no chunk boundary for either to move — the "must not re-chunk in a way that
breaks tag reassembly" requirement is met structurally rather than by a heuristic.

Both suites assert `StreamingResponse` does not appear on the path, so **adding a streaming
chat path will fail these tests** — which is the point. The client's parser already survives
a tag split one byte at a time (B4), so what a streaming bridge would have to guarantee is
only that concatenating its chunks reproduces the reply exactly. Extend these suites before
trusting a streaming path with tags.
