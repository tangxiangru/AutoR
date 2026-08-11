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
