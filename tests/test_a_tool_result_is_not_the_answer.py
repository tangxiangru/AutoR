"""A directory listing the model ran for itself is not part of its answer.

`extract_stream_text_fragments` harvests every string under `text`, `content`, `message`,
`delta`, `summary` or `result`, wherever it sits in the event. That is the right rule for a
caller that parses a delimited section out of the whole text -- every stage, and the sibling
benchmark's report path -- and the wrong one for the one seam that keeps a *reply*, because a
`tool_result` block is text under `content` too.

Measured on the sixty-task FrontierScience trial. The `direct` arm is the caller that keeps
the reply, and **six of its twenty-eight answers began with a directory listing**, the whole
answer still sitting underneath: one of them ran to 62,491 characters and ended in a complete
chemistry conclusion. Three of sixty answers on the previous trial had the same shape and were
scored normally, so the behaviour is not new. What is new is that a content-refusal clause now
reads the top of the file, so all six were refused -- and because only the arm that keeps a
reply can produce that shape, the refusals fell entirely on one arm of a paired comparison.

The answer was never the problem. The capture was.

The fix is additive and the first test class is what makes that checkable: `stdout_text` is
composed exactly as before, so nothing that reads it changes, and the assistant's own text
rides out beside it for the one caller that wants it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.operator import ClaudeOperator, _assistant_text_blocks  # noqa: E402
from src.utils import extract_stream_text_fragments  # noqa: E402

ANSWER = "## Part 1\n\nThe rate-determining step is the second one, and here is why."
LISTING = "total 0\ndrwx------  3 user user 0 Aug 19 05:11 .autor\n-rw-------  1 user user 0 logs.txt"

ASSISTANT = {"type": "assistant", "message": {"content": [{"type": "text", "text": ANSWER}]}}
TOOL_USE = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]}}
TOOL_RESULT = {"type": "user", "message": {"content": [
    {"type": "tool_result", "content": LISTING}]}}
RESULT_EVENT = {"type": "result", "result": ANSWER, "subtype": "success"}

# Two events that exist only to isolate the two checks from each other. Without them a
# mutation loosening either one survives, because every other fixture here fails both: the
# ordinary tool result is a `user` event carrying a `tool_result` block, so the event-type
# check alone rejects it and the block-type check is never asked.
# Carries a `text` key on purpose. A tool result normally puts its payload under `content`,
# which the `text` lookup misses anyway, so a fixture in that shape cannot tell the block
# filter from the lookup -- widening the filter to admit `tool_result` survives it. This is
# the adversarial shape: block type and key both present, so only the filter can refuse it.
TOOL_RESULT_INSIDE_AN_ASSISTANT_EVENT = {"type": "assistant", "message": {"content": [
    {"type": "tool_result", "text": LISTING, "content": LISTING}]}}
TEXT_INSIDE_A_NON_ASSISTANT_EVENT = {"type": "user", "message": {"content": [
    {"type": "text", "text": LISTING}]}}


class WhatTheAssistantSaidTests(unittest.TestCase):
    def test_a_text_block_is_the_assistants_own_words(self) -> None:
        self.assertEqual(_assistant_text_blocks(ASSISTANT), [ANSWER])

    def test_a_tool_result_is_not(self) -> None:
        """The defect, at its source. The listing is text under `content` and it is not a reply."""
        self.assertEqual(_assistant_text_blocks(TOOL_RESULT), [])

    def test_a_tool_call_is_not(self) -> None:
        self.assertEqual(_assistant_text_blocks(TOOL_USE), [])

    def test_the_block_type_is_checked_and_not_only_the_event_type(self) -> None:
        """A `tool_result` block inside an assistant event. Isolates the inner check.

        The ordinary tool result arrives as a `user` event, so the outer check rejects it and
        the inner one is never exercised; a mutation widening the block filter to admit
        `tool_result` survived every other test in this file.
        """
        self.assertEqual(_assistant_text_blocks(TOOL_RESULT_INSIDE_AN_ASSISTANT_EVENT), [])

    def test_the_event_type_is_checked_and_not_only_the_block_type(self) -> None:
        """A `text` block inside a non-assistant event. Isolates the outer check.

        The mirror of the case above, and it failed nothing before this test existed:
        dropping the event-type filter entirely left the file green.
        """
        self.assertEqual(_assistant_text_blocks(TEXT_INSIDE_A_NON_ASSISTANT_EVENT), [])

    def test_the_terminal_restatement_is_not(self) -> None:
        """It is the same words twice; the composer already treats it as a fallback."""
        self.assertEqual(_assistant_text_blocks(RESULT_EVENT), [])

    def test_several_blocks_in_one_message_keep_their_order(self) -> None:
        payload = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "first"},
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "text", "text": "second"},
        ]}}
        self.assertEqual(_assistant_text_blocks(payload), ["first", "second"])

    def test_a_malformed_event_is_not_an_exception(self) -> None:
        for payload in (None, [], "assistant", {"type": "assistant"},
                        {"type": "assistant", "message": None},
                        {"type": "assistant", "message": {"content": None}},
                        {"type": "assistant", "message": {"content": [None, 7, "x"]}}):
            self.assertEqual(_assistant_text_blocks(payload), [], repr(payload))

    def test_an_empty_text_block_contributes_nothing(self) -> None:
        payload = {"type": "assistant", "message": {"content": [{"type": "text", "text": "   "}]}}
        self.assertEqual(_assistant_text_blocks(payload), [])


class TheWholeStreamIsUnchangedTests(unittest.TestCase):
    """The control on the whole change: every other caller must see exactly what it saw.

    Without this the fix could have been made by narrowing
    `extract_stream_text_fragments`, which would have silently changed what every stage
    reads. The test is here to make that difference a failure rather than a preference.
    """

    def test_the_shared_extractor_still_reads_a_tool_result(self) -> None:
        self.assertIn(LISTING, extract_stream_text_fragments(TOOL_RESULT))

    def test_the_shared_extractor_still_reads_a_result_payload(self) -> None:
        self.assertIn(ANSWER, extract_stream_text_fragments(RESULT_EVENT))

    def test_the_composer_still_puts_the_listing_in_the_whole_stream_text(self) -> None:
        operator = ClaudeOperator(model="sonnet", fake_mode=True)
        composed = operator._compose_stdout_text(  # noqa: SLF001
            extracted_fragments=[LISTING, ANSWER], terminal_fragments=[ANSWER],
            non_json_lines=[], raw_lines=[],
        )
        self.assertIn(LISTING, composed)
        self.assertIn(ANSWER, composed)


class TheReplyTheFrontEndKeepsTests(unittest.TestCase):
    """`_OperatorCall.invoke` prefers the assistant's text and falls back to the stream.

    The fallback is not politeness. `CodexOperator` reaches the same seam and does not label
    its events, so a reader that required the field would hand that backend an empty answer
    and score it as a refusal.
    """

    def setUp(self) -> None:
        from src.frontierscience import _OperatorCall

        self.calls: list[dict] = []
        outer = self

        class Recorder:
            fake_mode = False

            def _prepare_invocation(self, prompt_path, session, *, paths, resume):
                return ["claude"], Path("/tmp"), None

            def _run_streaming_command(self, **kwargs):
                outer.calls.append(kwargs)
                return 0, outer.stdout, "", None, outer.meta

        class Call(_OperatorCall):
            def invoke_here(self, paths):
                return self.invoke(paths=paths, prompt="p", label="l", attempt=1)

        self.Call = Call
        self.operator = Recorder()

    def _run(self, stdout: str, meta: dict) -> str:
        import tempfile

        from src.utils import build_run_paths

        self.stdout, self.meta = stdout, meta
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp))
            paths.prompt_cache_dir.mkdir(parents=True, exist_ok=True)
            return self.Call(self.operator).invoke_here(paths)[1]

    def test_the_assistant_text_wins_over_the_whole_stream(self) -> None:
        """The defect end to end: the listing is in the stream and not in the answer."""
        reply = self._run(f"{LISTING}\n\n{ANSWER}", {"assistant_text": ANSWER})
        self.assertEqual(reply, ANSWER)
        self.assertNotIn("drwx", reply)

    def test_a_reader_that_offers_nothing_falls_back_to_the_whole_stream(self) -> None:
        self.assertEqual(self._run(ANSWER, {}), ANSWER)
        self.assertEqual(self._run(ANSWER, {"assistant_text": ""}), ANSWER)
        self.assertEqual(self._run(ANSWER, {"assistant_text": "   "}), ANSWER)

    def test_a_missing_meta_is_not_an_exception(self) -> None:
        self.assertEqual(self._run(ANSWER, None), ANSWER)


if __name__ == "__main__":
    unittest.main()
