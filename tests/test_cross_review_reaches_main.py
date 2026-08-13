"""The cross-model veto has to be reachable from the interactive CLI, and unreachable
from a fake run.

`--cross-review` was declared and parsed in `main.py` and read by no line in it: the only
production caller of `resolve_cross_reviewer` was `rcb_agent.py`, so the veto was live on
the benchmark path alone and every interactive run silently had a single-opinion approval
gate. `tests/test_cli_flags_are_read.py` carried both flags as a written-down exemption.

Wiring them is half the change. The other half is a refusal, because the two flags
interact badly with the one path CI walks end to end. `--cross-review` defaults to `auto`,
which seats a live `GeminiCrossReviewer` whenever `resolve_backend` finds a usable project
— and it accepts `ANTHROPIC_VERTEX_PROJECT_ID`, which a Claude Code host already exports.
`tests/test_fake_pipeline_end_to_end.py` runs `main.py --fake-operator --full-auto` twice,
eight approved stages each. Wired naively, that is a real Gemini call per approval on a
machine that was supposed to make none, and a live model holding a veto over a scripted
draft — a random red in `test_every_stage_is_approved_and_none_is_skipped`.

So the guard is tested in three places, because it has to hold in three: the front end
must not construct the auditor, every `ResearchManager` construction in `main.py` must
pass the argument at all, and the manager must refuse the pairing for callers that build
it directly.
"""

from __future__ import annotations

import ast
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as autor_main
from src.cross_reviewer import GeminiCrossReviewer
from src.manager import ResearchManager
from src.terminal_ui import TerminalUI
from src.web_search import SearchBackend


REPO_ROOT = Path(__file__).resolve().parent.parent

BACKEND = SearchBackend(kind="vertex", model="gemini-x", project="p", location="global")


class _Stop(BaseException):
    """Abort main() at the manager construction; running the pipeline is not the point."""


class MainSeatsTheCrossReviewerTest(unittest.TestCase):
    """Drive the real `main()` and read the argument the manager was handed."""

    def _construct(self, extra: list[str], *, backend: SearchBackend | None = BACKEND) -> dict:
        captured: dict = {}

        def record(**kwargs):
            captured.update(kwargs)
            raise _Stop

        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "main.py",
                "--goal", "cross-review wiring",
                "--full-auto",
                "--web-search", "native",
                "--runs-dir", str(Path(tmp) / "runs"),
                "--archive", str(Path(tmp) / "archive"),
                *extra,
            ]
            with patch("main.ResearchManager", side_effect=record), \
                 patch("src.cross_reviewer.resolve_backend", return_value=backend), \
                 patch("src.terminal_ui.TerminalUI.show_banner"), \
                 patch("src.terminal_ui.TerminalUI.show_status"), \
                 patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    try:
                        autor_main.main()
                    except _Stop:
                        pass

        self.assertIn("cross_reviewer", captured, "main() built a manager without the argument")
        return captured

    def test_a_live_run_hands_the_manager_a_cross_reviewer(self) -> None:
        captured = self._construct([])
        self.assertIsInstance(captured["cross_reviewer"], GeminiCrossReviewer)

    def test_the_model_flag_reaches_the_reviewer_it_names(self) -> None:
        """Wiring only the mode would leave `--cross-review-model` parsed and dropped."""
        captured = self._construct(["--cross-review-model", "gemini-not-the-default"])
        self.assertEqual(captured["cross_reviewer"].requested_model, "gemini-not-the-default")

    def test_off_means_off(self) -> None:
        self.assertIsNone(self._construct(["--cross-review", "off"])["cross_reviewer"])

    def test_auto_stays_silent_where_no_backend_is_configured(self) -> None:
        self.assertIsNone(self._construct([], backend=None)["cross_reviewer"])

    def test_gemini_seats_one_even_without_a_backend(self) -> None:
        """`gemini` is an explicit request, so it reports `unavailable` rather than
        vanishing: an audit that could not run must not be mistaken for one that passed."""
        captured = self._construct(["--cross-review", "gemini"], backend=None)
        self.assertIsInstance(captured["cross_reviewer"], GeminiCrossReviewer)


class _Args:
    """The three attributes `create_cross_reviewer` reads, and nothing else."""

    def __init__(self, *, fake_operator: bool, cross_review: str, cross_review_model=None) -> None:
        self.fake_operator = fake_operator
        self.cross_review = cross_review
        self.cross_review_model = cross_review_model


class AFakeRunNeverConstructsAnAuditorTest(unittest.TestCase):
    """`--fake-operator` must not reach `resolve_cross_reviewer` at all.

    Not "the reviewer it builds is never called" — never built, so the credential probe
    and every downstream call are refused before the cost is spent.
    """

    def _construct(self, extra: list[str]) -> tuple[dict, object]:
        captured: dict = {}

        def record(**kwargs):
            captured.update(kwargs)
            raise _Stop

        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "main.py",
                "--goal", "fake run",
                "--full-auto",
                "--fake-operator",
                "--web-search", "native",
                "--runs-dir", str(Path(tmp) / "runs"),
                "--archive", str(Path(tmp) / "archive"),
                *extra,
            ]
            with patch("main.ResearchManager", side_effect=record), \
                 patch("main.resolve_cross_reviewer") as resolver, \
                 patch("src.cross_reviewer.resolve_backend", return_value=BACKEND), \
                 patch("src.terminal_ui.TerminalUI.show_banner"), \
                 patch("src.terminal_ui.TerminalUI.show_status"), \
                 patch.object(sys, "argv", argv):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    try:
                        autor_main.main()
                    except _Stop:
                        pass

        self.assertIn("cross_reviewer", captured, "main() built a manager without the argument")
        return captured, resolver

    def test_the_resolver_is_never_reached_under_a_fake_operator(self) -> None:
        captured, resolver = self._construct([])
        resolver.assert_not_called()
        self.assertIsNone(captured["cross_reviewer"])

    def test_an_explicit_gemini_request_is_refused_too(self) -> None:
        """The default is not what makes this safe; the fake operator is."""
        captured, resolver = self._construct(["--cross-review", "gemini"])
        resolver.assert_not_called()
        self.assertIsNone(captured["cross_reviewer"])

    def test_the_run_says_out_loud_that_the_audit_is_off(self) -> None:
        """A gate that silently is not there is the failure this repo keeps finding."""
        said: list[str] = []
        ui = TerminalUI(output_stream=io.StringIO(), interactive=False)
        with patch.object(TerminalUI, "show_status", lambda self, text, level="info": said.append(text)):
            reviewer = autor_main.create_cross_reviewer(
                _Args(fake_operator=True, cross_review="auto"), ui=ui
            )
        self.assertIsNone(reviewer)
        self.assertTrue(
            any("Cross-model review is off" in line for line in said),
            f"nothing announced the disabled audit: {said}",
        )

    def test_it_does_not_announce_a_gate_the_user_already_turned_off(self) -> None:
        said: list[str] = []
        ui = TerminalUI(output_stream=io.StringIO(), interactive=False)
        with patch.object(TerminalUI, "show_status", lambda self, text, level="info": said.append(text)):
            autor_main.create_cross_reviewer(
                _Args(fake_operator=True, cross_review="off"), ui=ui
            )
        self.assertEqual(said, [])


class EveryManagerConstructionIsWiredTest(unittest.TestCase):
    """`main.py` builds a manager twice — the fresh run and `--resume-run`.

    Wiring one and not the other is the exact shape of divergence this repo has already
    paid for between its two front ends, and it would be invisible: a resumed run would
    just quietly have a single-opinion gate. Read off the syntax tree rather than a
    regex, so a reformatted call site still counts.
    """

    def _constructions(self) -> list[ast.Call]:
        tree = ast.parse((REPO_ROOT / "main.py").read_text(encoding="utf-8"))
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ResearchManager"
        ]

    def test_both_of_them_pass_a_cross_reviewer(self) -> None:
        calls = self._constructions()
        self.assertGreaterEqual(len(calls), 2, "the scan lost sight of main.py's manager constructions")
        for call in calls:
            with self.subTest(line=call.lineno):
                self.assertIn(
                    "cross_reviewer",
                    {kw.arg for kw in call.keywords},
                    f"main.py line {call.lineno} builds a manager with no cross_reviewer argument",
                )

    def test_they_all_go_through_the_guarded_factory(self) -> None:
        """Calling `resolve_cross_reviewer` directly at a call site would skip the fake
        refusal, which lives in `create_cross_reviewer` and nowhere else in this file."""
        for call in self._constructions():
            keyword = next(kw for kw in call.keywords if kw.arg == "cross_reviewer")
            with self.subTest(line=call.lineno):
                self.assertIsInstance(keyword.value, ast.Call)
                self.assertEqual(keyword.value.func.id, "create_cross_reviewer")


class _FakeOperator:
    model = "fake"
    backend_name = "claude"
    fake_mode = True


class _LiveOperator:
    model = "opus"
    backend_name = "claude"


class TheManagerRefusesTheAuditorBehindAFakeOperatorTest(unittest.TestCase):
    """The backstop, held where every caller passes: `ResearchManager.__init__`.

    `rcb_agent.py` builds its auditor unconditionally, and a test or a tool can build a
    manager without going through either front end. The refusal sits beside the one that
    zeroes evolution rounds for the same reason and on the same evidence: a fake operator
    emits the same scripted draft whatever it is asked, so there is nothing to audit.
    """

    def _manager(self, operator, reviewer) -> ResearchManager:
        with tempfile.TemporaryDirectory() as tmp:
            return ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=Path(tmp),
                operator=operator,
                ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
                cross_reviewer=reviewer,
            )

    def test_a_fake_operator_drops_the_auditor(self) -> None:
        manager = self._manager(_FakeOperator(), GeminiCrossReviewer())
        self.assertIsNone(manager.cross_reviewer)

    def test_a_real_operator_keeps_it(self) -> None:
        """Guards against the refusal being written as an unconditional drop."""
        reviewer = GeminiCrossReviewer()
        self.assertIs(self._manager(_LiveOperator(), reviewer).cross_reviewer, reviewer)

    def test_an_operator_that_does_not_declare_fake_mode_keeps_it(self) -> None:
        """`OperatorProtocol` does not require the attribute; absence is not fakeness."""

        class _Bare:
            model = "x"
            backend_name = "claude"

        reviewer = GeminiCrossReviewer()
        self.assertIs(self._manager(_Bare(), reviewer).cross_reviewer, reviewer)

    def test_a_live_veto_cannot_send_a_scripted_stage_back(self) -> None:
        """The consequence, not just the attribute: this is the random red."""
        from src.approval_agent import ReviewDecision
        from src.cross_reviewer import CrossVerdict
        from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

        reviewer = GeminiCrossReviewer()
        reviewer.audit = lambda **kwargs: CrossVerdict(  # type: ignore[assignment]
            agrees=False, reason="x" * 80, model="gemini-x"
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run_0001")
            ensure_run_layout(paths)
            write_text(paths.user_input, "goal")
            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=paths.run_root.parent,
                operator=_FakeOperator(),
                ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
                cross_reviewer=reviewer,
            )
            self.assertIsNone(
                manager._apply_cross_review(
                    paths=paths,
                    stage=STAGES[0],
                    attempt_no=1,
                    decision=ReviewDecision(choice="5", decision_token="t", reason="approved"),
                    stage_markdown="# Stage 01: Literature Survey\n",
                )
            )


if __name__ == "__main__":
    unittest.main()
