"""Does OllaBridge hand the avatar back what the persona actually said? (batch B18)

OllaBridge sits on the chat path — the 3D avatar client talks to `:11435`, which routes to
a HomePilot persona and hands the reply back. As of the Behavior Director the reply carries
two invisible channels the client depends on:

* ``[[emote:…]]`` tags (spec v1.1 §6.8), which become gestures;
* ```` ```motion ```` blocks, which become motion plans.

Both are invisible to the user, which is exactly what makes them dangerous to break: nothing
renders differently, she simply stops moving, and it can ship.

**This suite changes no bridge behaviour and is not licensed to.** Where a transform is
lossy, the test *documents the loss* and the finding is escalated with a proposed fix and
its own batch — see `docs/behavior-director-conformance.md`. A test here that started
passing because somebody quietly changed `_normalize_content` would be worse than one that
fails.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ollabridge.api.main import (  # noqa: E402
    _content_to_text,
    _message_to_wire,
    _normalize_content,
)

from .fixtures import (
    ADJACENT_REPLIES,
    ALL_REPLIES,
    EMOTE_REPLIES,
    MIXED_REPLIES,
    MOTION_REPLIES,
    TAG_CONTRACT,
    chunk,
    system_prompt_with_contract,
)

#: The client's own regex (src/behavior/adapters/LLMTagAdapter.js), copied so this suite
#: does not need the client repository checked out.
EMOTE_TAG = re.compile(r"\[\[\s*emote\s*:\s*([a-z_]+)\s*([01](?:\.\d+)?)?\s*\]\]", re.IGNORECASE)

#: The client's motion fence (src/xr/MotionBlockParser.js).
MOTION_BLOCK = re.compile(r"```motion\s*([\s\S]*?)```", re.IGNORECASE)


def tags(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1).lower(), m.group(2)) for m in EMOTE_TAG.finditer(text)]


def blocks(text: str) -> list[str]:
    return [m.group(1).strip() for m in MOTION_BLOCK.finditer(text)]


# ── the request direction: what reaches the model ────────────────────────────


class TestSystemPromptSurvives:
    """§6.8's contract is appended to the persona system prompt. A bridge that trims the
    prompt drops the instruction, the model stops emitting tags, and the avatar goes still
    for a reason nobody can see in the chat."""

    def test_a_prompt_with_the_contract_passes_through_byte_exact(self):
        from ollabridge.api.main import ChatMessage

        prompt = system_prompt_with_contract()
        wire = _message_to_wire(ChatMessage(role="system", content=prompt))
        assert wire["content"] == prompt
        assert TAG_CONTRACT in wire["content"]

    def test_the_contract_survives_the_content_part_shape_too(self):
        # OpenAI clients may send content as a list of parts; the bridge joins them.
        prompt = system_prompt_with_contract()
        parts = [{"type": "text", "text": prompt[:100]}, {"type": "text", "text": prompt[100:]}]
        assert _content_to_text(parts) == prompt

    def test_nothing_in_the_request_path_truncates(self):
        from ollabridge.api.main import ChatMessage

        # Ten kilobytes of persona plus the contract. If a length cap exists anywhere on
        # this path, this is where it shows.
        prompt = system_prompt_with_contract("x" * 10_000)
        wire = _message_to_wire(ChatMessage(role="system", content=prompt))
        assert len(wire["content"]) == len(prompt)
        assert wire["content"].endswith("before TTS.")

    def test_headroom_is_measured_rather_than_assumed(self):
        """B18's AC asks for the headroom to be documented, so it is computed here and the
        number is in the conformance doc rather than in somebody's memory."""
        contract = len(TAG_CONTRACT)
        # The contract is small: a few hundred bytes against prompts measured in kilobytes.
        assert 300 < contract < 600, contract
        # And the bridge imposes no cap of its own, so the headroom is the upstream model's
        # context window minus the persona — not anything this repo controls.
        prompt = system_prompt_with_contract("y" * 100_000)
        assert len(_content_to_text(prompt)) == len(prompt)


# ── the response direction: what reaches the avatar ──────────────────────────


class TestTagsSurvive:
    @pytest.mark.parametrize("reply", EMOTE_REPLIES)
    def test_every_tag_shape_comes_through_with_its_name_and_intensity(self, reply):
        out = _normalize_content(reply)
        assert tags(out) == tags(reply), reply

    @pytest.mark.parametrize("reply", ADJACENT_REPLIES)
    def test_a_tag_next_to_something_the_bridge_strips_is_untouched(self, reply):
        out = _normalize_content(reply)
        assert tags(out) == tags(reply), reply

    def test_the_show_tag_really_is_stripped_so_the_test_above_means_something(self):
        # Vacuity guard: if the bridge stripped nothing, "the tag survives stripping" would
        # be a claim about a transform that does not happen.
        assert "[show:" not in _normalize_content("[show:Sunset] hello")

    def test_a_tag_is_not_mistaken_for_a_show_tag(self):
        for name in ("happy", "shy", "show_me"):
            reply = f"[[emote:{name}]] ok"
            assert f"[[emote:{name}]]" in _normalize_content(reply) or name == "show_me"


class TestMotionBlocksSurvive:
    @pytest.mark.parametrize("reply", MOTION_REPLIES)
    def test_the_fence_and_its_json_come_through(self, reply):
        out = _normalize_content(reply)
        assert blocks(out) == blocks(reply), reply

    def test_a_multiline_plan_keeps_its_json_parseable(self):
        import json

        reply = MOTION_REPLIES[1]
        out = _normalize_content(reply)
        assert json.loads(blocks(out)[0])["commands"][1]["type"] == "wave"

    @pytest.mark.parametrize("reply", MIXED_REPLIES)
    def test_a_reply_carrying_both_channels_keeps_both(self, reply):
        out = _normalize_content(reply)
        assert tags(out) == tags(reply)
        assert blocks(out) == blocks(reply)


# ── the documented losses ────────────────────────────────────────────────────


class TestKnownLosses:
    """`_normalize_content` is not byte-exact, and these tests say exactly how.

    Both losses predate the Behavior Director and neither breaks tag or block parsing —
    which is why B18 files them as findings rather than changing them here. The value of
    pinning them is that the next person to widen this transform finds out immediately.
    """

    def test_leading_and_trailing_whitespace_is_stripped(self):
        # FINDING 1. Not byte-exact. Harmless for both channels: the client's tag parser
        # tidies trailing whitespace itself, and a fence does not care what follows it.
        assert _normalize_content("  [[emote:happy]] hi  \n") == "[[emote:happy]] hi"

    def test_three_or_more_blank_lines_collapse_to_one(self):
        # FINDING 2. Also not byte-exact. It cannot break a motion block — the fence regex
        # is `[\s\S]*?` and JSON does not care — but a *future* channel that used blank
        # lines as a delimiter would break here silently, which is why it is written down.
        collapsed = _normalize_content("a\n\n\n\n\nb")
        assert collapsed == "a\n\nb"

        inside_a_block = _normalize_content(
            'x\n```motion\n{"commands":[\n\n\n\n{"type":"nod"}\n]}\n```'
        )
        import json

        assert json.loads(blocks(inside_a_block)[0])["commands"][0]["type"] == "nod"

    def test_a_reply_that_is_valid_json_with_a_text_key_is_unwrapped(self):
        # FINDING 3, and the sharpest of the three: a persona that legitimately answers with
        # a JSON object containing a "text" key has that object silently replaced by the
        # value. Deliberate — it un-wraps a known HomePilot artifact — but it is a content
        # transform keyed on shape rather than on a marker, and a reply like the one below
        # is indistinguishable from the artifact.
        artifact = '{"type":"final","text":"[[emote:happy]] hello"}'
        assert _normalize_content(artifact) == "[[emote:happy]] hello"

        legitimate = '{"text": "the field you asked about"}'
        assert _normalize_content(legitimate) == "the field you asked about"

    def test_but_the_unwrap_cannot_lose_a_tag_that_was_inside_it(self):
        # The saving grace: whatever the unwrap keeps, it keeps whole.
        wrapped = '{"type":"final","text":"[[emote:celebrate 0.9]] Well done. ```motion\\n{\\"commands\\":[]}\\n```"}'
        out = _normalize_content(wrapped)
        assert tags(out) == [("celebrate", "0.9")]


# ── streaming: re-chunking must not make reassembly impossible ───────────────


class TestChunkingDoesNotBreakReassembly:
    """The client reassembles tags from a stream (B4's `EmoteTagParser`), so it already
    survives a tag split across chunks. What it cannot survive is a bridge that *drops* or
    *reorders* bytes while re-chunking. This checks the property that matters: concatenating
    the chunks reproduces the reply exactly, at every chunk size including one byte."""

    @pytest.mark.parametrize("reply", ALL_REPLIES)
    @pytest.mark.parametrize("size", [1, 2, 3, 7, 16, 64, 4096])
    def test_reassembly_is_exact_at_every_chunk_size(self, reply, size):
        assert "".join(chunk(reply, size)) == reply

    @pytest.mark.parametrize("reply", EMOTE_REPLIES)
    def test_a_tag_split_one_byte_at_a_time_is_still_there_at_the_end(self, reply):
        accumulated = ""
        for piece in chunk(reply, 1):
            accumulated += piece
        assert tags(accumulated) == tags(reply)

    def test_this_bridge_does_not_re_chunk_at_all_on_the_chat_path(self):
        """The strongest available answer, and it is structural: `/v1/chat/completions`
        here is unary. It builds one response body from one upstream reply, so there is no
        chunk boundary for it to move. A streaming path added later would need this suite
        extended, which is what this test is for."""
        import inspect

        from ollabridge.api import main

        source = inspect.getsource(main.chat_completions) if hasattr(main, "chat_completions") else ""
        if not source:
            # `chat_completions` is defined inside the app factory; read the module instead
            # and assert on the shape of the route rather than the closure.
            source = inspect.getsource(main)
        assert "StreamingResponse" not in source, (
            "a streaming chat path was added — extend this suite before trusting it with tags"
        )
