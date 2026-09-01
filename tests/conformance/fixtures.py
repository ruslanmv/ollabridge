"""What a persona reply looks like once the Behavior Director is on (batch B18).

These are the shapes the 3D avatar client now depends on surviving the bridge. They are
copied here rather than imported so this suite has no dependency on the client repository —
a conformance test that only runs when someone has checked out two repos is a test nobody
runs.

The contract they encode:

* ``[[emote:<name> <intensity>]]`` — spec v1.1 §6.8. Appended to the persona's system
  prompt; the client parses them out of the stream, plays a gesture and hides the tag.
* ```` ```motion ```` fenced JSON — the existing motion-block channel (`MotionBlockParser`),
  which predates the Director and must keep working alongside it.

Both are **invisible to the user** and therefore easy to break without anybody noticing for
a release: nothing renders differently, she just stops moving.
"""

from __future__ import annotations

#: §6.8's tag, in every shape a model actually emits it.
EMOTE_REPLIES = [
    "[[emote:happy 0.8]] Good to see you.",
    "Well [[emote:thinking]] that depends on what you mean.",
    "Oh! [[emote:surprised 1.0]] I did not expect that. [[emote:celebrate 0.9]] Congratulations.",
    "[[emote:wave]]",
    "That is a lot to carry. [[emote:console 0.7]]",
    # Whitespace inside the tag: the client's regex tolerates it, so the bridge must not
    # "helpfully" normalise it either — a tag rewritten into a shape the parser misses is
    # worse than one dropped, because the text still shows and nothing moves.
    "[[ emote : nod_along 0.5 ]] Mm.",
]

#: The motion-block channel, including the untagged fence smaller models emit.
MOTION_REPLIES = [
    'Let me come closer.\n\n```motion\n{"commands":[{"type":"approach","target":"user"}],"priority":"normal"}\n```',
    'Sure.\n```motion\n{\n  "commands": [\n    {"type": "look_at", "target": "user"},\n    {"type": "wave"}\n  ],\n  "priority": "high"\n}\n```\nDone.',
    '``` {"commands":[{"type":"nod"}],"priority":"low"} ```',
]

#: Both channels in one reply, which is the normal case once B4 is on.
MIXED_REPLIES = [
    '[[emote:happy 0.9]] On my way.\n\n```motion\n{"commands":[{"type":"approach","target":"user"}],"priority":"normal"}\n```',
    'Right then.\n\n```motion\n{"commands":[{"type":"stand"}],"priority":"normal"}\n```\n\n[[emote:agree 0.6]] Ready.',
]

#: Replies that are *adjacent* to something the bridge strips, and must not be caught by it.
ADJACENT_REPLIES = [
    # A `[show:...]` tag really is stripped by the bridge — deliberately. An emote tag next
    # to one must come through untouched.
    "[show:Sunset] [[emote:happy 0.8]] Look at that.",
    # Square brackets that are not tags at all.
    "The array is [1, 2, 3]. [[emote:thinking]] Does that help?",
    # A reply that begins with a brace, which the bridge tries to JSON-unwrap.
    '{"not":"a wrapper"} [[emote:surprised]] odd, but valid prose.',
]

ALL_REPLIES = EMOTE_REPLIES + MOTION_REPLIES + MIXED_REPLIES + ADJACENT_REPLIES

#: §6.8's contract, verbatim, as the client appends it to the persona system prompt. Its
#: length is what B18 measures headroom against.
TAG_CONTRACT = """When emotionally relevant, append at most one tag per sentence, max 3 per
reply: [[emote:<name> <intensity 0..1>]]
Allowed names: happy, sad, angry, surprised, thinking, celebrate, dance,
wave, flirt, tease, shy, agree, disagree, idle, point, lean_in, nod_along,
console. Never invent names. Tags are invisible to the user and stripped
before TTS."""


def system_prompt_with_contract(persona: str = "") -> str:
    """A persona prompt with §6.8 appended, as the client sends it."""
    base = persona or (
        "You are Kira, a warm and curious companion. You remember what the user tells you "
        "and you are never sycophantic. Keep replies short unless asked for detail."
    )
    return f"{base}\n\n{TAG_CONTRACT}"


def chunk(text: str, size: int) -> list[str]:
    """Split a reply into fixed-size pieces, as a streaming transport would.

    Size 1 is the interesting case: every tag is then split across chunk boundaries, which
    is precisely what the client's streaming parser has to survive and therefore what a
    re-chunking bridge must not make impossible.
    """
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
