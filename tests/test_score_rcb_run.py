"""The local scorer must not let a judge failure pass as a score.

ResearchClawBench's scorer records a failed judge call as
``{"score": 0, "reasoning": "Failed to parse scoring response."}`` — identical
in the output to a criterion the report genuinely missed. Scoring one run that
way, two of three items were judge failures: the honest total was 37.0 and the
number on screen was 19.5.

These tests hold the properties that prevent repeating it: the three stock
defaults that cause the failures are not in use, a failed call is counted rather
than swallowed, and a total is refused while any call failed.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "score_rcb_run.py"


def _load():
    spec = importlib.util.spec_from_file_location("score_rcb_run", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TrapDefaultsTest(unittest.TestCase):
    """Each constant exists because a stock default fakes a zero."""

    def setUp(self) -> None:
        self.tool = _load()

    def test_the_token_budget_leaves_room_for_a_reasoning_judge(self) -> None:
        self.assertGreater(self.tool.JUDGE_MAX_TOKENS, 500)

    def test_the_time_limit_fits_a_multimodal_call(self) -> None:
        self.assertGreater(self.tool.JUDGE_TIME_LIMIT, 120)

    def test_scoring_is_serial(self) -> None:
        """Concurrent multimodal calls were the actual cause of most failures."""
        self.assertEqual(self.tool.JUDGE_WORKERS, 1)

    def test_each_constant_says_what_it_is_for(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        for marker in ("max_tokens=500", "time_limit=120", "max_workers=16"):
            self.assertIn(marker, text, f"the stock default {marker} is not named")


class JudgeFailureAccountingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load()

    def _judge(self):
        judge = self.tool.VertexJudge.__new__(self.tool.VertexJudge)
        judge.model = "test-model"
        judge.calls = 0
        judge.failures = []
        return judge

    def test_an_unparseable_body_is_recorded_as_a_failure(self) -> None:
        judge = self._judge()

        class Boom:
            def __getattr__(self, _name):
                raise RuntimeError("vertex is down")

        judge._client = Boom()
        result = judge("prompt", max_try=1)

        self.assertIsNone(result, "a failed call must not return a score")
        self.assertEqual(len(judge.failures), 1)
        self.assertIn("vertex is down", judge.failures[0])

    def test_a_failure_is_not_reported_as_a_zero(self) -> None:
        """The whole point. None is distinguishable; 0 is not."""
        judge = self._judge()

        class Boom:
            def __getattr__(self, _name):
                raise RuntimeError("nope")

        judge._client = Boom()
        self.assertIsNot(judge("p", max_try=1), 0)


class JsonExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load()

    def test_a_bare_object_parses(self) -> None:
        self.assertEqual(
            self.tool._first_json_object('{"score": 42, "reasoning": "ok"}')["score"], 42
        )

    def test_an_object_wrapped_in_prose_parses(self) -> None:
        parsed = self.tool._first_json_object('Here you go:\n{"score": 7}\nDone.')
        self.assertEqual(parsed["score"], 7)

    def test_no_object_yields_none_rather_than_a_guess(self) -> None:
        self.assertIsNone(self.tool._first_json_object("I could not decide."))

    def test_an_empty_body_yields_none(self) -> None:
        """What a thinking model returns when max_tokens runs out."""
        self.assertIsNone(self.tool._first_json_object(""))


class JudgeIsPartOfTheResultTest(unittest.TestCase):
    """A benchmark number quoted without its judge compares to nothing.

    Measured on identical artifacts: Gemini 2.5 Flash 37.0, Claude Opus 20.8.
    """

    def test_the_tool_names_the_judge_in_its_output(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("judge_model", text)
        self.assertIn("TOTAL (judge", text)

    def test_the_spread_between_judges_is_recorded(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("37.0", text)
        self.assertIn("20.8", text)


if __name__ == "__main__":
    unittest.main()
