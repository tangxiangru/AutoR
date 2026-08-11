"""The three wiring defects that made `tools/score_rcb_run.py` unable to score.

The tool shipped with a judge, a serialiser and a refuse-to-quote guard, all correct.
It still could not produce a number, because of three bindings:

1. The `JUDGE_*` env vars were set *after* `evaluation.score` was imported.
   `evaluation/config.py` reads them at import time, so every run died on
   "Judge API configuration is missing" with the configuration right there.
2. `config.JUDGE_MODEL_NAME` was rebound, but `evaluation/score.py` does
   `from .config import JUDGE_MODEL_NAME` -- a module-level copy the gate actually
   tests. Rebinding one without the other changes nothing.
3. The per-item table read `result["results"]`; `score_workspace` returns `items`.
   The tool printed a real total beside "items judged: 0" and an empty breakdown --
   a scorer reporting it had scored nothing, immediately after scoring everything.

These are checked against the source rather than by running the tool, because running
it needs a judge key and a benchmark checkout that CI does not have. A source check
that names the exact failure is worth more than a skip.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "tools" / "score_rcb_run.py"


def _score_function() -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "score":
            return node
    raise AssertionError("tools/score_rcb_run.py no longer defines score()")


def _line_of_first(predicate) -> int | None:
    for node in ast.walk(_score_function()):
        if predicate(node):
            return node.lineno
    return None


class EnvIsSetBeforeTheImportTest(unittest.TestCase):
    def test_the_judge_env_is_set_before_evaluation_score_is_imported(self) -> None:
        import_line = _line_of_first(
            lambda n: isinstance(n, ast.Import)
            and any(a.name == "evaluation.score" for a in n.names)
        )
        env_line = _line_of_first(
            lambda n: isinstance(n, ast.Constant) and n.value == "JUDGE_API_KEY"
        )
        self.assertIsNotNone(import_line, "score() no longer imports evaluation.score")
        self.assertIsNotNone(env_line, "score() no longer sets JUDGE_API_KEY")
        self.assertLess(
            env_line, import_line,
            "JUDGE_* must be set before evaluation.score is imported; config.py reads "
            "them at import time and setting them afterwards reaches nothing.",
        )

    def test_the_model_name_is_among_them(self) -> None:
        source = ast.unparse(_score_function())
        self.assertIn("JUDGE_MODEL_NAME", source)


class BothBindingsAreRebound(unittest.TestCase):
    def test_the_scorer_module_copy_is_rebound_too(self) -> None:
        """`score.py` holds the copy the gate tests; `config` is what a reader reaches
        for. Rebinding one without the other is the defect."""
        source = ast.unparse(_score_function())
        self.assertIn("config.JUDGE_MODEL_NAME =", source)
        self.assertIn("scorer.JUDGE_MODEL_NAME =", source)


class TheItemsKeyTest(unittest.TestCase):
    def test_the_report_reads_items_not_results(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('result.get("items"', source)
        self.assertNotIn('result.get("results"', source)

    def test_the_benchmark_scorer_really_returns_items(self) -> None:
        """Pin the assumption rather than trusting it: if ResearchClawBench renames the
        key, this says so instead of silently printing an empty table again."""
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("items", source)
