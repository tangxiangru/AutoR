"""The terminal result event restates the reply; capturing it twice is not capturing more.

Written against a measured defect rather than a suspicion. The Claude CLI's stream emits the
turn's text as assistant events and then emits a terminal result event whose payload is the
same reply again. ``extract_stream_text_fragments`` harvests strings under a key set that
includes both ``text`` and ``result``, so every caller that keeps the whole reply got two
copies of it.

Stage-shaped callers never saw this. They parse a delimited section out of the text, and a
second copy of the section changes nothing they read -- which is why all forty
ResearchClawBench reports on this box are clean and why nothing caught it for as long as the
seam has existed. The callers that keep the reply are the two FrontierScience answer producers
and ResearchClawBench's report synthesizer.

What it cost, measured on the sixty-task FrontierScience trial: **fifty-five of the control
arm's sixty answers carried the answer twice** -- forty an exact byte-for-byte halving, fifteen
more asymmetric because the reply arrived in several streamed blocks -- against **none** of the
pipeline arm's, because only the control arm keeps the reply. Forty-two of the forty-three
paired tasks were affected. Re-judging eleven of them cut back to a single copy moved the score
by **-0.307 points on average** (sd 0.606, five of eleven negative and one positive), so the
duplication flattered the arm that had it by about the size of the effect the trial existed to
measure.

The three tests below are the three things that have to stay true: the reply is captured once,
the result event is still the reply when nothing else produced one, and a caller that keeps the
whole stream gets each of the turn's own blocks exactly once even when there are several.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
import sys

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.operator import ClaudeOperator  # noqa: E402
from src.utils import extract_stream_text_fragments  # noqa: E402


ANSWER = "## Part 1\n\nThe coefficient is 1.8 and the mechanism is the second one.\n"


def compose(operator: ClaudeOperator, *, turn: list[str], terminal: list[str]) -> str:
    """The composer as the streaming loop calls it, with nothing else in play."""
    return operator._compose_stdout_text(  # noqa: SLF001
        extracted_fragments=turn,
        terminal_fragments=terminal,
        non_json_lines=[],
        raw_lines=[],
    )


class TheReplyIsCapturedOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.operator = ClaudeOperator(model="sonnet", fake_mode=True)

    def test_the_terminal_event_does_not_add_a_second_copy(self) -> None:
        """The defect itself: assistant text plus a result event restating it is one reply."""
        composed = compose(self.operator, turn=[ANSWER], terminal=[ANSWER])
        self.assertEqual(composed, ANSWER.strip())
        self.assertEqual(composed.count("The coefficient is 1.8"), 1)

    def test_a_multi_block_reply_keeps_every_block_and_still_drops_the_restatement(self) -> None:
        """The asymmetric fifteen: several assistant blocks, then the whole reply again.

        The exact-halving detector missed these, which is why the first count of the defect
        said forty and the real one is fifty-five.
        """
        blocks = ["## Part 1\n\nFirst.", "## Part 2\n\nSecond.", "## Part 3\n\nThird."]
        composed = compose(self.operator, turn=blocks, terminal=["\n".join(blocks)])
        for block in blocks:
            self.assertEqual(composed.count(block.split("\n\n")[1]), 1, block)

    def test_the_result_event_is_still_the_reply_when_nothing_else_produced_one(self) -> None:
        """The case the harvest was there for. A fallback, not a contribution."""
        self.assertEqual(compose(self.operator, turn=[], terminal=[ANSWER]), ANSWER.strip())

    def test_a_turn_that_said_nothing_composes_to_nothing(self) -> None:
        self.assertEqual(compose(self.operator, turn=[], terminal=[]), "")


class TheExtractorStillSeesBothTests(unittest.TestCase):
    """The control: the fix is in the composer, so the extractor must be unchanged.

    Moving the rule into `extract_stream_text_fragments` by dropping the `result` key would
    have been the smaller diff and the wrong one -- the key is how a turn that emits nothing
    else is read at all, and the extractor cannot see which event it was handed.
    """

    def test_the_extractor_still_reads_a_result_payload(self) -> None:
        self.assertIn(ANSWER.strip(), extract_stream_text_fragments({"type": "result", "result": ANSWER}))

    def test_the_extractor_still_reads_an_assistant_payload(self) -> None:
        payload = {"type": "assistant", "message": {"content": [{"type": "text", "text": ANSWER}]}}
        self.assertIn(ANSWER.strip(), extract_stream_text_fragments(payload))


class TheComposerStillCarriesTheOtherTwoSourcesTests(unittest.TestCase):
    """Non-JSON output and the raw fallback are untouched by this change."""

    def setUp(self) -> None:
        self.operator = ClaudeOperator(model="sonnet", fake_mode=True)

    def test_non_json_output_is_appended_after_the_reply(self) -> None:
        composed = self.operator._compose_stdout_text(  # noqa: SLF001
            extracted_fragments=[ANSWER], terminal_fragments=[ANSWER],
            non_json_lines=["a warning on stderr's twin"], raw_lines=[],
        )
        self.assertIn(ANSWER.strip(), composed)
        self.assertIn("a warning on stderr's twin", composed)
        self.assertEqual(composed.count("The coefficient is 1.8"), 1)

    def test_the_raw_lines_are_used_only_when_there_is_nothing_else(self) -> None:
        self.assertEqual(
            self.operator._compose_stdout_text(  # noqa: SLF001
                extracted_fragments=[], terminal_fragments=[], non_json_lines=[],
                raw_lines=["{not json at all}"],
            ),
            "{not json at all}",
        )
        # And not when there is.
        composed = self.operator._compose_stdout_text(  # noqa: SLF001
            extracted_fragments=[], terminal_fragments=[ANSWER], non_json_lines=[],
            raw_lines=["{not json at all}"],
        )
        self.assertEqual(composed, ANSWER.strip())


if __name__ == "__main__":
    unittest.main()
