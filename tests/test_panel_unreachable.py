"""A panel that could not be convened is not a panel that found nothing.

Both distinctions in this file were found by running AutoR against a live backend rather than
by reading the code. Vertex had exhausted the quota for the reviewer's base model while the
run's own operator was on a different, healthy one, so every deliberation voice failed while
the stage itself sailed on. The ledger then reported:

    "1 crux(es) escalated at 4 calls; no working answer was offered to compare against."

That sentence is false. The agent's ``working_answer`` was a 1,000-character answer; what was
missing was the *panel*. Reading only the summary would have sent someone to tighten the
escalation prompt, fixing a problem that did not exist while the outage went unnoticed.

The captured payload is checked in verbatim as a fixture. A fixture invented after the fact
would only encode what I already believed the failure looked like.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.deliberation import Position, Resolution, CruxRequest, _summary
from src.ideation_panel import _pool_verdict

FIXTURE = Path(__file__).parent / "fixtures" / "deliberation_all_voices_unreachable.json"


def _position(voice: str, *, failed: bool, answer: str = "") -> Position:
    return Position(
        voice=voice,
        title=voice.title(),
        backend="claude",
        model="sonnet",
        answer=answer,
        failed=failed,
    )


class RealCapturedOutageTest(unittest.TestCase):
    """The exact ledger entry the live run produced."""

    def setUp(self) -> None:
        self.entry = json.loads(FIXTURE.read_text())

    def test_the_captured_entry_really_is_a_total_outage(self) -> None:
        # Guards the fixture itself: if someone regenerates it from a healthy run the
        # tests below would pass for the wrong reason.
        self.assertTrue(self.entry["positions"])
        self.assertTrue(all(p["failed"] for p in self.entry["positions"]))
        self.assertTrue(self.entry["request"]["working_answer"].strip())

    def test_summary_does_not_blame_the_agent_for_the_backend(self) -> None:
        verdict = _summary([self.entry])["verdict"]
        self.assertNotIn("no working answer was offered", verdict)

    def test_summary_names_the_outage(self) -> None:
        summary = _summary([self.entry])
        self.assertEqual(summary["never_deliberated"], 1)
        self.assertIn("every voice's backend failed", summary["verdict"])

    def test_summary_refuses_to_read_as_evidence_about_deliberation(self) -> None:
        # The whole point of the ledger is to say whether stopping to think paid off.
        # On a run where it never happened, it has to decline to answer.
        verdict = _summary([self.entry])["verdict"]
        self.assertIn("it was never tried", verdict)


class ResolutionVerdictTest(unittest.TestCase):
    def _resolution(self, positions: list[Position], **kw) -> Resolution:
        return Resolution(
            request=CruxRequest(question="q" * 40, working_answer="my current best answer"),
            positions=positions,
            voice_calls=len(positions),
            **kw,
        )

    def test_all_voices_failed_says_the_panel_never_sat(self) -> None:
        res = self._resolution([_position(v, failed=True) for v in ("a", "b", "c")])
        self.assertTrue(res.all_voices_unreachable)
        self.assertEqual(res.unreachable, 3)
        self.assertIn("No voice could be reached", res.verdict())

    def test_partial_outage_is_reported_but_not_as_a_dead_panel(self) -> None:
        res = self._resolution(
            [_position("a", failed=True), _position("b", failed=False, answer="use top-k")]
        )
        self.assertFalse(res.all_voices_unreachable)
        self.assertIn("1 of 2 voice(s) could not be reached", res.verdict())

    def test_a_reachable_panel_that_answered_nothing_is_unchanged(self) -> None:
        # The pre-existing sentence has to survive. A panel that sat, spoke, and produced
        # no usable answer is a real outcome and must not be relabelled as an outage.
        res = self._resolution([_position("a", failed=False), _position("b", failed=False)])
        self.assertEqual(res.unreachable, 0)
        self.assertEqual(
            res.verdict(), "The deliberation produced no answer; the stage keeps its own."
        )

    def test_no_positions_at_all_is_not_an_outage(self) -> None:
        # A crux that was never dispatched has no positions. Claiming every voice failed
        # would invent an outage out of an empty list.
        res = self._resolution([])
        self.assertFalse(res.all_voices_unreachable)

    def test_unreachable_count_reaches_the_serialized_record(self) -> None:
        res = self._resolution([_position("a", failed=True), _position("b", failed=True)])
        self.assertEqual(res.to_dict()["unreachable"], 2)


class MixedLedgerTest(unittest.TestCase):
    def _entry(self, *, failed: bool, changed: bool | None) -> dict:
        return {
            "positions": [{"failed": failed}, {"failed": failed}],
            "voice_calls": 2,
            "changed_the_answer": changed,
        }

    def test_one_outage_among_several_is_subtracted_not_averaged(self) -> None:
        verdict = _summary(
            [self._entry(failed=True, changed=None), self._entry(failed=False, changed=True)]
        )["verdict"]
        self.assertIn("1 never reached a panel", verdict)
        self.assertIn("1 are the only ones this run can speak to", verdict)

    def test_one_failed_voice_does_not_write_off_a_panel_that_sat(self) -> None:
        # The asymmetry that matters: *every* voice failing means no panel; *a* voice
        # failing means a smaller panel that still deliberated. Counting the second as
        # an outage would subtract a real result from the evidence.
        entry = {
            "positions": [{"failed": True}, {"failed": False}, {"failed": False}],
            "voice_calls": 3,
            "changed_the_answer": True,
        }
        summary = _summary([entry])
        self.assertEqual(summary["never_deliberated"], 0)
        self.assertIn("the panel changed the answer on 1", summary["verdict"])

    def test_a_healthy_ledger_keeps_its_original_verdict(self) -> None:
        verdict = _summary([self._entry(failed=False, changed=False)])["verdict"]
        self.assertIn("confirmed the agent's own answer every time", verdict)

    def test_the_genuine_missing_working_answer_case_still_reports_itself(self) -> None:
        # The sentence being defended against a false positive is still needed for the
        # case it was written for: voices reached, no baseline to compare against.
        verdict = _summary([self._entry(failed=False, changed=None)])["verdict"]
        self.assertIn("no working answer was offered", verdict)

    def test_an_entry_with_no_positions_key_is_not_an_outage(self) -> None:
        verdict = _summary([{"voice_calls": 2, "changed_the_answer": None}])["verdict"]
        self.assertIn("no working answer was offered", verdict)


class IdeationPoolVerdictTest(unittest.TestCase):
    def test_every_proposer_unreachable_says_the_panel_never_sat(self) -> None:
        verdict = _pool_verdict(distinct=0, added=0, calls=4, unreachable=4, seated=4)
        self.assertIn("No proposer could be reached", verdict)
        self.assertIn("it was never tried", verdict)

    def test_an_empty_pool_from_reachable_proposers_keeps_its_sentence(self) -> None:
        verdict = _pool_verdict(distinct=0, added=0, calls=4, unreachable=0, seated=4)
        self.assertEqual(
            verdict, "No candidate hypotheses survived; the stage proceeds without a pool."
        )

    def test_a_partial_outage_with_survivors_is_not_a_dead_panel(self) -> None:
        verdict = _pool_verdict(distinct=3, added=2, calls=4, unreachable=1, seated=4)
        self.assertNotIn("never sat", verdict)
        self.assertIn("2 of 3 distinct hypotheses", verdict)

    def test_a_partial_outage_with_an_empty_pool_still_names_the_failures(self) -> None:
        verdict = _pool_verdict(distinct=0, added=0, calls=4, unreachable=2, seated=4)
        self.assertIn("No candidate hypotheses survived", verdict)
        self.assertIn("2 of 4 proposer(s) could not be reached", verdict)

    def test_unknown_seat_count_does_not_swallow_a_real_outage(self) -> None:
        # Older records predate the seated count. An outage must not be silently
        # downgraded just because the denominator is missing.
        verdict = _pool_verdict(distinct=0, added=0, calls=4, unreachable=3, seated=0)
        self.assertIn("No proposer could be reached", verdict)


if __name__ == "__main__":
    unittest.main()
