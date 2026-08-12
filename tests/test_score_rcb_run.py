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
import json
import sys
import tempfile
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

    def test_the_reference_judge_actually_passes_both_budgets(self) -> None:
        """The two tests above hold the constants, and held nothing else.

        `JUDGE_TIME_LIMIT` was read by no code at all, and `JUDGE_MAX_TOKENS` only by
        `VertexJudge` -- so on the default `--judge reference` path the call went out
        with the client's own defaults, and the pair of assertions above stayed green.
        A test that asserts a constant's value does not know whether anything reads it;
        this one captures the kwargs the client is actually handed.
        """
        sent: dict = {}

        class _Responses:
            def create(self, **kwargs):
                sent.update(kwargs)
                raise RuntimeError("stop after capturing the call")

        judge = self.tool.ReferenceJudge.__new__(self.tool.ReferenceJudge)
        judge.model = "gpt-5.1"
        judge.calls = 0
        judge.failures = []
        judge._client = type("_C", (), {"responses": _Responses()})()

        judge("score this", max_try=1)

        self.assertEqual(sent.get("max_output_tokens"), self.tool.JUDGE_MAX_TOKENS)
        self.assertEqual(sent.get("timeout"), self.tool.JUDGE_TIME_LIMIT)

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


class RefusalRuleTest(unittest.TestCase):
    """A zero has to be distinguishable from a failure to score, at every count.

    The guard that existed covered a judge that failed. It did not cover a judge that
    was never asked: an empty or short checklist gives ``total_score: 0``,
    ``judge_failures: []`` and exit 0 — the same 19.5-against-37.0 shape, one clause
    short of the guard already here.
    """

    def setUp(self) -> None:
        self.tool = _load()

    def full(self, **overrides) -> dict:
        base = {
            "items": [{"score": 40}, {"score": 50}],
            "checklist_items_expected": 2,
            "judge_failures": [],
            "total_score": 44.0,
        }
        base.update(overrides)
        return base

    def test_a_fully_judged_run_is_not_refused(self) -> None:
        self.assertEqual(self.tool.refusal_reasons(self.full()), [])

    def test_an_empty_checklist_is_refused(self) -> None:
        reasons = self.tool.refusal_reasons(
            self.full(items=[], checklist_items_expected=0, total_score=0)
        )
        self.assertEqual(len(reasons), 1)
        self.assertIn("zero over nothing", reasons[0])

    def test_a_short_item_vector_is_refused(self) -> None:
        """Nothing anywhere cross-checked `items` against the checklist on disk."""
        reasons = self.tool.refusal_reasons(self.full(checklist_items_expected=5))
        self.assertEqual(len(reasons), 1)
        self.assertIn("checklist of 5", reasons[0])

    def test_a_judge_failure_is_still_refused(self) -> None:
        reasons = self.tool.refusal_reasons(self.full(judge_failures=["timeout"]))
        self.assertIn("timeout", reasons[0])

    def test_the_refusal_is_raised_by_score_and_not_only_printed_by_main(self) -> None:
        """A guarantee that lives in `main` is a printing policy, not a property.

        Anything doing `from score_rcb_run import score` used to get back a dict whose
        `total_score` already had the failed calls folded in as zeros, with no exception
        and no flag.
        """
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn("raise ScoringRefused", body)
        self.assertIn("refusal_reasons(result)", body)


class SelfDescriptionTest(unittest.TestCase):
    """Three keys without which an `--out` file cannot be read a week later."""

    def test_the_output_records_which_images_the_judge_was_shown(self) -> None:
        """60.6% of the benchmark's weight is image criteria and every one of them sees
        the same first five of one list — and `IMAGE_EXTENSIONS` is a `set`, so which
        five changes between interpreters. Nothing recorded them."""
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn('result["images_shown"]', body)
        self.assertIn("_find_generated_images", body)

    def test_the_output_records_how_many_images_there_were_to_choose_from(self) -> None:
        """Five of five and five of twelve are not the same evidence.

        The judge sees the first five of one list against every image criterion, so an
        arm that emitted twelve figures was scored on an arbitrary five of them. Without
        the denominator the score file cannot say which of those two things happened, and
        the paired trial attributes the whole image stratum to figure quality.
        """
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn('result["images_available"]', body)

    def test_the_output_records_the_benchmark_revision(self) -> None:
        """Item identity is a property of the checkout; the output records only task_id."""
        self.assertIn('result["bench_revision"]', TOOL.read_text(encoding="utf-8"))

    def test_the_output_records_what_the_item_count_should_have_been(self) -> None:
        self.assertIn('result["checklist_items_expected"]', TOOL.read_text(encoding="utf-8"))


class AgainstTheRealScorerTest(unittest.TestCase):
    """The wiring, driven through ResearchClawBench's own `score_workspace`.

    Skipped without a benchmark checkout, which is why every rule above is also held by
    a test that needs neither. What this adds is that the rule is actually *reached*:
    the refusal, the self-description and the exit code all sit on the far side of an
    import that the unit tests do not perform.
    """

    def setUp(self) -> None:
        import shutil

        bench_source = Path("/home/robtang_google_com/RCB")
        if not (bench_source / "evaluation" / "score.py").exists():
            self.skipTest("no ResearchClawBench checkout")
        try:
            import structai  # noqa: F401
        except ImportError:
            self.skipTest("structai is not installed")

        self.tool = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # A copy, because `PROJECT_ROOT` is derived from the package's own location, so
        # copying `evaluation/` gives the real scorer over a task tree we control.
        self.bench = self.root / "bench"
        self.bench.mkdir()
        shutil.copytree(bench_source / "evaluation", self.bench / "evaluation")
        for stale in ("evaluation", "evaluation.score", "evaluation.config", "evaluation.utils"):
            sys.modules.pop(stale, None)
        self.addCleanup(
            lambda: [sys.modules.pop(name, None) for name in list(sys.modules)
                     if name.startswith("evaluation")]
        )
        self.addCleanup(lambda: sys.path.remove(str(self.bench))
                        if str(self.bench) in sys.path else None)

    def _workspace(self, task: str, checklist: list) -> Path:
        study = self.bench / "tasks" / task / "target_study"
        study.mkdir(parents=True)
        (study / "checklist.json").write_text(json.dumps(checklist), encoding="utf-8")
        workspace = self.root / f"{task}_20260101_000000"
        (workspace / "report").mkdir(parents=True)
        (workspace / "report" / "report.md").write_text("# report\n\nbody\n", encoding="utf-8")
        (workspace / "_meta.json").write_text(
            json.dumps({"run_id": workspace.name, "task_id": task}), encoding="utf-8"
        )
        return workspace

    class _Judge:
        model = "stub-judge"

        def __init__(self) -> None:
            self.calls = 0
            self.failures: list[str] = []

        def __call__(self, prompt, image_paths=None, return_example=None, max_try=2, **_):
            self.calls += 1
            return {"score": 40, "reasoning": "stub"}

    def test_an_empty_checklist_exits_one_and_writes_no_result_file(self) -> None:
        """Before this it exited 0, printed `TOTAL: 0.0`, and wrote the file."""
        workspace = self._workspace("Empty_000", [])
        out = self.root / "out.json"
        argv = [
            "score_rcb_run.py", "--workspace", str(workspace), "--bench", str(self.bench),
            "--judge", "vertex", "--project-id", "x", "--out", str(out),
        ]
        self.tool.VertexJudge = lambda **_: self._Judge()
        old = sys.argv
        sys.argv = argv
        try:
            code = self.tool.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 1)
        self.assertFalse(out.exists(), "a refused total was still written to disk")

    def test_a_fully_judged_run_scores_and_describes_itself(self) -> None:
        workspace = self._workspace(
            "Full_000",
            [
                {"content": "a", "type": "text", "weight": 0.6},
                {"content": "b", "type": "text", "weight": 0.4},
            ],
        )
        result = self.tool.score(workspace, self.bench, judge=self._Judge())
        self.assertEqual(result["total_score"], 40)
        self.assertEqual(result["checklist_items_expected"], 2)
        self.assertIn("images_shown", result)
        self.assertIn("bench_revision", result)

    def test_the_result_is_written_into_a_directory_that_does_not_exist_yet(self) -> None:
        """`--out` is handed in by the paired-trial driver, and nothing creates its parent.

        `tools/rcb_trial.py::score_path` builds `<state_dir>/scores/<...>.json` and passes
        it straight through; the directory only ever appeared by accident of the dry
        run's fake judge, which writes through a helper that creates it. So every test
        was green while the real judge path could not write a single result: the scorer
        judged every item, printed the total, and died on `FileNotFoundError` — which the
        driver reads as "scoring failed", retries `replicates` x 2 times per run, and
        finally publishes `pairs: 0` with no diagnosis after four days of opus runs.
        """
        workspace = self._workspace("Full_001", [{"content": "a", "type": "text", "weight": 1.0}])
        out = self.root / "state" / "scores" / "Full_001.abc1234.a1.final.r0.json"
        self.assertFalse(out.parent.exists())
        self.tool.VertexJudge = lambda **_: self._Judge()
        old = sys.argv
        sys.argv = [
            "score_rcb_run.py", "--workspace", str(workspace), "--bench", str(self.bench),
            "--judge", "vertex", "--project-id", "x", "--out", str(out),
        ]
        try:
            code = self.tool.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 0)
        self.assertTrue(out.exists(), "the judge's whole bill, and nowhere to put it")
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["total_score"], 40)
        # Replaced, never truncated: a kill during the write leaves a file that
        # `final_pass` skips forever because it exists and that the report cannot parse.
        self.assertEqual(list(out.parent.glob("*.tmp*")), [])

    def test_score_raises_rather_than_returning_a_poisoned_total(self) -> None:
        """The programmatic hole. `main` refused; `score` handed back the zero."""
        workspace = self._workspace("Short_000", [{"content": "a", "type": "text", "weight": 1.0}])
        judge = self._Judge()
        judge.failures.append("deliberate")

        with self.assertRaises(self.tool.ScoringRefused) as caught:
            self.tool.score(workspace, self.bench, judge=judge)
        # The result is carried on the exception, so a caller can still show the table.
        self.assertIn("total_score", caught.exception.result)
        self.assertIn("deliberate", caught.exception.reasons[0])


if __name__ == "__main__":
    unittest.main()


class NoSecretInTheRepositoryTest(unittest.TestCase):
    """The judge key must never be committable.

    A key pasted into a tool, a docstring or a test fixture is the ordinary way
    this leaks — the file itself lives outside any repository, so the risk is
    not the file, it is a copy of its contents ending up in one.
    """

    def test_the_tool_contains_no_key_shaped_literal(self) -> None:
        import re

        text = TOOL.read_text(encoding="utf-8")
        # A long opaque token assigned to something, or an OpenAI-style key.
        suspicious = re.findall(r"""(?:sk-[A-Za-z0-9_\-]{16,})""", text)
        self.assertEqual(suspicious, [], "a key-shaped literal is in the tool")

    def test_no_tracked_file_holds_a_key_shaped_literal(self) -> None:
        import re
        import subprocess

        listing = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        )
        if listing.returncode != 0:  # pragma: no cover - not a git checkout
            self.skipTest("not a git checkout")

        pattern = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
        offenders = []
        for name in listing.stdout.split():
            path = REPO_ROOT / name
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if pattern.search(body):
                offenders.append(name)
        self.assertEqual(offenders, [], f"key-shaped literal in tracked files: {offenders}")

    def test_the_key_file_default_is_outside_any_repository(self) -> None:
        """A default inside the tree is one `git add -A` away from a leak."""
        tool = _load()
        default = tool.DEFAULT_KEY_FILE.resolve()
        self.assertFalse(
            str(default).startswith(str(REPO_ROOT.resolve()) + "/"),
            f"the default key file {default} sits inside the repository",
        )

    def test_the_cli_refuses_to_take_a_key_as_an_argument(self) -> None:
        """A key on the command line lands in shell history and the process table."""
        text = TOOL.read_text(encoding="utf-8")
        self.assertNotIn('"--api-key"', text)
        self.assertNotIn("'--api-key'", text)
        self.assertIn("--key-file", text)

    def test_errors_are_redacted_before_they_are_printed(self) -> None:
        tool = _load()
        # Assembled rather than written out: a literal here would be found by
        # the repository scan above, which is the point of that scan.
        fake = "sk-" + ("abcdefghijkl" + "mnopqrstuvwxyz" + "012345")
        leaked = f"AuthError: request failed with Bearer {fake}"
        self.assertNotIn("mnopqrstuvwxyz", tool._redact(leaked))
        self.assertIn("<redacted>", tool._redact(leaked))


class ReferenceJudgeTest(unittest.TestCase):
    """gpt-5.1 is what the benchmark scores with; anything else is not comparable."""

    def setUp(self) -> None:
        self.tool = _load()

    def test_the_reference_judge_is_the_default(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn('default="reference"', text)
        self.assertEqual(self.tool.REFERENCE_JUDGE_MODEL, "gpt-5.1")

    def test_a_missing_key_file_says_what_to_do_rather_than_crashing(self) -> None:
        from pathlib import Path

        with self.assertRaises(SystemExit) as caught:
            self.tool.read_api_key(Path("/nonexistent/api.txt"))
        message = str(caught.exception)
        self.assertIn("--judge vertex", message)
        self.assertIn("Do not pass a key on the command line", message)

    def test_the_key_reader_tolerates_the_shapes_a_file_arrives_in(self) -> None:
        import tempfile
        from pathlib import Path

        for raw in ("token-value", "KEY=token-value", '"token-value"', "  token-value\n"):
            with self.subTest(shape=raw):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "api.txt"
                    path.write_text(raw, encoding="utf-8")
                    self.assertEqual(self.tool.read_api_key(path), "token-value")

    def test_the_endpoint_is_not_treated_as_a_secret(self) -> None:
        """An endpoint in source is fine; a key is not. Keep them distinguishable."""
        self.assertTrue(self.tool.REFERENCE_JUDGE_ENDPOINT.startswith("https://"))


class DrawAggregationTest(unittest.TestCase):
    """The judge is stochastic and a one-draw total does not say so.

    Eight draws over one unchanged artifact set -- same workspace, same report, same
    figures -- spanned 8.5 points (41.4 to 49.9, sd 3.4), and the heaviest checklist
    item alone spanned 23. That is enough to make a single-task before/after below
    about eight points meaningless, and I nearly reported one: 46.0 against 42.8, where
    46.0 sits at the 3/8 percentile of the *unchanged* artifact's own distribution.

    So the tests worth having here are not about the mean. They are about the tool
    refusing to imply a precision it has not got.
    """

    def setUp(self) -> None:
        self.tool = _load()

    @staticmethod
    def _drawn(total: float, scores: list[float]) -> dict:
        return {
            "total_score": total,
            "judge_model": "gpt-5.1",
            "judge_calls": len(scores),
            "judge_failures": [],
            "items": [{"type": "text", "weight": 0.5, "content": f"c{i}", "score": s}
                      for i, s in enumerate(scores)],
        }

    def test_the_mean_is_over_every_draw(self) -> None:
        merged = self.tool.aggregate_draws(
            [self._drawn(40.0, [40, 40]), self._drawn(50.0, [60, 40])]
        )
        self.assertEqual(merged["total_score"], 45.0)
        self.assertEqual(merged["total_scores"], [40.0, 50.0])
        self.assertEqual(merged["draws"], 2)
        self.assertEqual(merged["items"][0]["score"], 50.0)
        self.assertEqual(merged["items"][0]["scores"], [40.0, 60.0])

    def test_one_draw_reports_its_dispersion_as_unmeasured_not_as_zero(self) -> None:
        """The whole point. A zero here reads as "the judge is deterministic".

        It would be inferred from the one sample size that cannot show it, and it is
        the direction that flatters: a fabricated +/-0.0 makes any delta look
        significant. `rcb_trial` refuses the same shape one layer up.
        """
        merged = self.tool.aggregate_draws([self._drawn(40.0, [40, 40])])

        self.assertIsNone(merged["total_spread"])
        self.assertIsNone(merged["items"][0]["spread"])
        self.assertIn("unmeasured", self.tool.format_spread(merged["total_spread"], 1))
        self.assertNotIn("0.0", self.tool.format_spread(merged["total_spread"], 1))

    def test_the_spread_is_reported_once_there_is_one(self) -> None:
        merged = self.tool.aggregate_draws(
            [self._drawn(41.4, [40]), self._drawn(49.9, [60]), self._drawn(45.5, [50])]
        )
        self.assertAlmostEqual(merged["total_spread"], 8.5, places=6)
        self.assertIn("8.5", self.tool.format_spread(merged["total_spread"], 3))
        self.assertIn("3 draws", self.tool.format_spread(merged["total_spread"], 3))

    def test_judge_calls_accumulate_across_draws(self) -> None:
        """Cost is per draw, and a reader comparing two totals needs to see that."""
        merged = self.tool.aggregate_draws(
            [self._drawn(40.0, [40, 40]), self._drawn(50.0, [60, 40])]
        )
        self.assertEqual(merged["judge_calls"], 4)

    def test_the_draw_count_travels_with_the_total(self) -> None:
        """A total whose sampling is unstated cannot be compared with another one.

        Same argument as the judge model, which this tool already prints for the same
        reason -- and the two are the same failure at different scales.
        """
        text = TOOL.read_text(encoding="utf-8")
        self.assertIn("TOTAL (judge {result['judge_model']}, {draw_count} draw", text)

    def test_the_default_is_one_draw_so_behaviour_is_unchanged(self) -> None:
        merged = self.tool.aggregate_draws([self._drawn(42.8, [42.8])])
        self.assertEqual(merged["draws"], 1)
        self.assertEqual(merged["total_score"], 42.8)

    def test_aggregating_nothing_raises_rather_than_reporting_zero(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.aggregate_draws([])
