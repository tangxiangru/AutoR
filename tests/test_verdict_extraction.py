"""The reviewing backend is an agent, so its stdout is a transcript, not an object.

This is the defect that ended 12 of 40 ResearchClawBench runs. On Material_002 the reviewer
inspected the artifacts, wrote "well past the bar for a literature survey", and emitted a
verdict object as its final message. AutoR read the transcript, found no object it could
parse, recorded

    choice: 6
    decision_token: abort
    reason: Automated reviewer did not return valid JSON. AutoR stopped instead of approving blindly.

and ended the run -- discarding `stages/01_literature_survey.tmp.md`, 18,976 bytes that had
passed both gates with a rubric score of 1.0. The refusal itself is right; the premise was
wrong. The verdict was in the output.
"""

from __future__ import annotations

import unittest

from src.approval_agent import AutomatedReviewer, extract_json_payload


VERDICT = (
    '{"decision":"approve","reason":"ledger integrity holds","feedback":"",'
    '"carry_forward":[{"obligation":"settle experiment 3","target_stage":"03_study_design"}],'
    '"discharged":[]}'
)

#: The literal opening of the transcript AutoR recorded for Material_002.
NARRATION = (
    "I'll inspect the actual artifacts before judging.\n"
    "total 2408\n"
    "drwxrwxr-x  9 robtang_google_com robtang_google_com    4096 Aug  6 14:53 .\n"
    "-rw-rw-r--  1 robtang_google_com robtang_google_com     584 Aug  6 14:48 artifact_index.json\n\n"
)

#: A data file the reviewer read and echoed. This is what defeats the greedy brace branch:
#: `(\{.*\})` spans from this object's first brace to the verdict's last one.
QUOTED_DATA = '{"claims": [{"id": "C09", "source_ids": []}, {"id": "C10", "source_ids": ["S16"]}]}\n'


class VerdictInATranscriptTest(unittest.TestCase):
    def _decision(self, raw: str) -> str | None:
        payload = extract_json_payload(raw, verdict_key="decision")
        return None if payload is None else payload.get("decision")

    def test_a_bare_object_still_works(self) -> None:
        self.assertEqual(self._decision(VERDICT), "approve")

    def test_narration_and_tool_output_before_the_verdict(self) -> None:
        self.assertEqual(self._decision(NARRATION + VERDICT), "approve")

    def test_material_002_the_transcript_also_quoted_a_json_file(self) -> None:
        """The greedy `(\\{.*\\})` branch spans both objects and parses as neither."""
        raw = NARRATION + "Let me read claims.json.\n" + QUOTED_DATA + "Now the verdict.\n" + VERDICT
        self.assertEqual(self._decision(raw), "approve")

    def test_a_sentence_after_the_verdict_does_not_hide_it(self) -> None:
        self.assertEqual(self._decision(VERDICT + "\n\nHappy to expand on any of this."), "approve")

    def test_a_fenced_data_block_does_not_outrank_the_real_verdict(self) -> None:
        """The fence branch returns the *first* fenced object, which here is a data file."""
        raw = "Here is what I read:\n```json\n" + QUOTED_DATA + "```\n" + VERDICT
        self.assertEqual(self._decision(raw), "approve")

    def test_a_fenced_verdict_is_still_found(self) -> None:
        self.assertEqual(self._decision("Verdict:\n```json\n" + VERDICT + "\n```"), "approve")

    def test_the_last_verdict_wins_when_the_backend_changes_its_mind(self) -> None:
        raw = '{"decision":"revise","reason":"first pass"}\nOn reflection:\n' + VERDICT
        self.assertEqual(self._decision(raw), "approve")

    def test_nested_objects_inside_the_verdict_survive(self) -> None:
        payload = extract_json_payload(NARRATION + VERDICT, verdict_key="decision")
        assert payload is not None
        self.assertEqual(payload["carry_forward"][0]["target_stage"], "03_study_design")

    def test_an_unbalanced_quote_earlier_in_the_transcript_does_not_desynchronise(self) -> None:
        """Tool output is arbitrary text; a stray quote must not swallow the verdict."""
        raw = NARRATION + 'sed: -e expression #1, char 3: unterminated `s\' command\n' + VERDICT
        self.assertEqual(self._decision(raw), "approve")

    def test_a_verdict_split_by_a_blank_line_in_the_middle_is_still_one_object(self) -> None:
        raw = NARRATION + '{"decision":"approve",\n\n  "reason":"fine"}'
        self.assertEqual(self._decision(raw), "approve")


class TheRefusalIsPreservedTest(unittest.TestCase):
    """Reading a verdict that is there must not become approving one that is not."""

    def test_a_transcript_with_no_verdict_is_still_refused(self) -> None:
        self.assertIsNone(extract_json_payload(NARRATION + QUOTED_DATA, verdict_key="decision"))

    def test_an_empty_response_is_refused(self) -> None:
        self.assertIsNone(extract_json_payload("", verdict_key="decision"))
        self.assertIsNone(extract_json_payload("   \n  ", verdict_key="decision"))

    def test_prose_that_merely_says_approve_is_not_a_verdict(self) -> None:
        """The object is the contract. An agent musing about approval has not voted."""
        self.assertIsNone(
            extract_json_payload("I would approve this stage. decision: approve", verdict_key="decision")
        )

    def test_an_object_without_the_key_does_not_masquerade_as_one(self) -> None:
        self.assertIsNone(extract_json_payload('{"verdict":"approve"}', verdict_key="decision"))

    def test_truncated_json_is_refused(self) -> None:
        self.assertIsNone(extract_json_payload(NARRATION + VERDICT[:-20], verdict_key="decision"))


class RouterSharesTheFunctionTest(unittest.TestCase):
    """Two callers want different objects out of the same kind of transcript."""

    def test_a_routing_move_is_found_by_its_own_key(self) -> None:
        raw = 'I looked at the graph.\n{"nodes":[1,2]}\nMy move:\n{"target":"03_study_design","reason":"design first"}'
        payload = extract_json_payload(raw, verdict_key="target")
        assert payload is not None
        self.assertEqual(payload["target"], "03_study_design")

    def test_a_review_verdict_is_not_mistaken_for_a_routing_move(self) -> None:
        self.assertIsNone(extract_json_payload(VERDICT, verdict_key="target"))

    def test_omitting_the_key_keeps_the_original_behaviour(self) -> None:
        """Callers with no identifying key still get the first parseable object."""
        self.assertEqual(extract_json_payload(VERDICT), extract_json_payload(VERDICT, verdict_key="decision"))
        self.assertEqual(extract_json_payload(QUOTED_DATA.strip())["claims"][0]["id"], "C09")


class TheDecisionThatWasLostTest(unittest.TestCase):
    """End to end: the transcript that ended 11 runs now promotes the stage.

    `parse_with_retry` and the unattended send-back already stopped the *abort*, so these
    runs would no longer die outright. They would still burn every attempt on re-asks of a
    verdict that was readable all along, and end auto-skipped. This is the cause, not the
    bleeding: the first parse succeeds and the stage is approved on attempt one.
    """

    def setUp(self) -> None:
        self.reviewer = AutomatedReviewer("claude", model="opus", unattended=True)

    def _decision(self, raw: str):
        return self.reviewer._parse_decision(raw)  # noqa: SLF001

    def test_the_transcript_now_yields_approve_and_promote(self) -> None:
        decision = self._decision(NARRATION + QUOTED_DATA + "Verdict:\n" + VERDICT)
        self.assertEqual(decision.choice, "5")
        self.assertEqual(decision.decision_token, "approve")
        self.assertFalse(self.reviewer._is_unreadable(decision))  # noqa: SLF001

    def test_the_obligations_survive_the_transcript(self) -> None:
        """carry_forward is where most of a review's value lives; it came from the verdict."""
        decision = self._decision(NARRATION + QUOTED_DATA + VERDICT)
        self.assertEqual(decision.carry_forward[0]["target_stage"], "03_study_design")

    def test_a_revise_verdict_in_a_transcript_is_read_as_revise(self) -> None:
        """Three of the twelve runs said revise, not approve. Both were lost the same way."""
        raw = NARRATION + '{"decision":"revise","reason":"ledger has empty source_ids","feedback":"cite the spec"}'
        decision = self._decision(raw)
        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.feedback, "cite the spec")

    def test_a_transcript_with_no_verdict_is_still_unreadable(self) -> None:
        decision = self._decision(NARRATION + QUOTED_DATA)
        self.assertTrue(self.reviewer._is_unreadable(decision))  # noqa: SLF001

    def test_a_quoted_data_file_is_never_read_as_the_verdict(self) -> None:
        """Falling through to some other object would source feedback from a data file."""
        decision = self._decision(NARRATION + QUOTED_DATA)
        self.assertEqual(decision.carry_forward, [])
        self.assertEqual(decision.feedback, "")


class ScanIsBoundedTest(unittest.TestCase):
    def test_a_megabyte_of_braces_before_the_verdict_still_resolves(self) -> None:
        """A long transcript must not turn the search quadratic."""
        noise = '{"row": %d}\n' % 1
        raw = noise * 20000 + VERDICT
        self.assertEqual(
            extract_json_payload(raw, verdict_key="decision").get("decision"), "approve"
        )

    def test_a_verdict_beyond_the_scan_window_is_refused_rather_than_hung(self) -> None:
        """Bounding the window is a real limit, so it is stated rather than assumed."""
        from src.approval_agent import _VERDICT_SCAN_CHARS

        raw = VERDICT + "x" * (_VERDICT_SCAN_CHARS + 1000)
        self.assertIsNone(extract_json_payload(raw, verdict_key="decision"))


if __name__ == "__main__":
    unittest.main()
