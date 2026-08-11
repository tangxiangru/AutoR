"""The run's own arguments, routed to the only stage that can publish them.

The material is real: the deliberation payload here is the shape a live run produced, and the
crux is the one it actually raised. What makes it worth routing is where the score is. Every
ResearchClawBench criterion is graded on one of two ladders, and above 50 -- "as good as the
published paper" -- is only reachable on the mechanistic one, whose bands read "more supporting
evidence than the paper", "a more complete logical chain and more rigorous argumentation", and
"insights the paper did not cover". That is a description of ``deliberations.json``.

So the tests here are mostly about the two ways this can go wrong: claiming reasoning that did
not happen, and padding. Both score worse than saying nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.information_flow import CHANNELS
from src.settled_reasoning import (
    MAX_CRUXES,
    MAX_FIELD_CHARS,
    MAX_REJECTED,
    build_block,
    rejected_candidates,
    resolved_cruxes,
)
from src.utils import build_run_paths

QUESTION = (
    "For a three-way comparison of LASSO, ridge and elastic net on selection stability, what "
    "should count as 'variable j was selected' for ridge, which never sets a coefficient to zero?"
)


def _paths(tmp: str):
    paths = build_run_paths(Path(tmp) / "run")
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _write(paths, name: str, payload) -> None:
    (paths.reviews_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _crux(*, answer: str, falsifier: str = "", dissent: str = "", considered=()) -> dict:
    return {
        "request": {"question": QUESTION, "already_considered": list(considered)},
        "answer": answer,
        "falsifier": falsifier,
        "dissent": dissent,
    }


def _cand(idea_id: str, **kw) -> dict:
    base = {
        "idea_id": idea_id,
        "title": f"Hypothesis {idea_id}",
        "statement": f"Statement for {idea_id}, long enough to be a real claim.",
        "proposer": "contrarian",
        "proposer_title": "Contrarian",
        "adopted": False,
        "duplicate_of": None,
    }
    base.update(kw)
    return base


class ResolvedCruxesTest(unittest.TestCase):
    def test_an_answered_crux_is_rendered_with_its_falsifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [
                _crux(answer="Matched-cardinality top-k.", falsifier="Rank agreement flips it.",
                      considered=["Absolute threshold: no interpretable cutoff."]),
            ]})
            block = build_block(paths)
            self.assertIn("Matched-cardinality top-k.", block)
            self.assertIn("Would be overturned by", block)
            self.assertIn("Considered and rejected", block)

    def test_an_unanswered_crux_contributes_nothing(self) -> None:
        # The live run that motivated this had every voice fail, so the answer was empty.
        # Publishing that as an open question the run deliberately left open would be
        # claiming reasoning that never happened.
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [_crux(answer="")]})
            self.assertEqual(resolved_cruxes(paths), [])
            self.assertIsNone(build_block(paths))

    def test_a_whitespace_answer_is_not_an_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [_crux(answer="  \n ")]})
            self.assertEqual(resolved_cruxes(paths), [])

    def test_the_crux_count_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [
                _crux(answer=f"answer {i}") for i in range(MAX_CRUXES + 3)
            ]})
            self.assertEqual(build_block(paths).count("**Question.**"), MAX_CRUXES)

    def test_the_cap_keeps_the_latest_not_the_earliest(self) -> None:
        # Later cruxes were argued with more of the run's evidence in hand.
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [
                _crux(answer=f"answer {i}") for i in range(MAX_CRUXES + 2)
            ]})
            block = build_block(paths)
            self.assertIn(f"answer {MAX_CRUXES + 1}", block)
            self.assertNotIn("answer 0", block)

    def test_a_long_field_is_clipped(self) -> None:
        # Image criteria see only the first 10,000 characters of the report and the judge is
        # told longer is not better. An unbounded transcript costs more than it earns.
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": [_crux(answer="x" * 5000)]})
            self.assertLessEqual(len(resolved_cruxes(paths)[0]["answer"]), MAX_FIELD_CHARS)


class RejectedCandidatesTest(unittest.TestCase):
    def test_an_adopted_candidate_is_not_a_road_not_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [_cand("a", adopted=True)]})
            self.assertEqual(rejected_candidates(paths), [])

    def test_a_duplicate_is_not_a_road_not_taken(self) -> None:
        # A restatement of the adopted hypothesis listed as an alternative would overstate
        # how wide the search actually was.
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [_cand("b", duplicate_of="a")]})
            self.assertEqual(rejected_candidates(paths), [])

    def test_a_rejected_candidate_carries_its_lens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [_cand("c")]})
            block = build_block(paths)
            self.assertIn("Contrarian", block)
            self.assertIn("Hypotheses generated and not pursued", block)

    def test_a_candidate_with_no_statement_is_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [_cand("d", statement="")]})
            self.assertEqual(rejected_candidates(paths), [])

    def test_the_rejected_count_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [
                _cand(str(i)) for i in range(MAX_REJECTED + 4)
            ]})
            self.assertEqual(len(build_block(paths).splitlines()) - 2, MAX_REJECTED)


class NothingToSayTest(unittest.TestCase):
    def test_a_run_that_argued_nothing_sends_nothing(self) -> None:
        # Silence is the correct output. An empty heading in the prompt invites the stage to
        # fill it, and a discussion section about nothing scores below one that is absent.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(build_block(_paths(tmp)))

    def test_a_corrupt_ledger_is_silence_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            (paths.reviews_dir / "deliberations.json").write_text("{not json")
            self.assertIsNone(build_block(paths))

    def test_a_ledger_with_the_wrong_shape_is_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "deliberations.json", {"deliberations": "nope"})
            _write(paths, "idea_pool.json", ["not a dict"])
            self.assertIsNone(build_block(paths))

    def test_one_source_alone_is_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            _write(paths, "idea_pool.json", {"candidates": [_cand("only")]})
            self.assertIsNotNone(build_block(paths))


class ChannelTopologyTest(unittest.TestCase):
    def _channel(self):
        return next(c for c in CHANNELS if c.key == "settled_reasoning")

    def test_only_stage_07_reads_it(self) -> None:
        # Every earlier stage either produced this material or was told the part that bound
        # its own decision. Re-sending it upstream re-opens questions the run closed.
        self.assertEqual(self._channel().consumed_by, frozenset({"07_writing"}))

    def test_the_preface_sends_it_after_the_results(self) -> None:
        # 60.6% of the weight is image criteria, which see only the first 10,000 characters.
        # Material that displaces the headline numbers costs more than it earns.
        self.assertIn("after the results", self._channel().preface)

    def test_the_channel_is_silent_when_the_builder_is(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from src.information_flow import ChannelContext
            from src.utils import resolve_stage

            channel = self._channel()
            context = ChannelContext(paths=_paths(tmp), stage=resolve_stage("07"), attempt_no=1)
            self.assertFalse(channel.build(context))


if __name__ == "__main__":
    unittest.main()
