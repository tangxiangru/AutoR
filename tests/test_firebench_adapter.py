"""The FIRE-Bench adapter, and the four ways this benchmark scores the wrong thing.

Every other benchmark AutoR is wired to reads a file at a known path. FIRE-Bench reads
*the last line of a log*, through an extractor that tries two other patterns first, and
scores the text with a metric that punishes a run for saying more than was asked. Four
failure modes follow from that, none of which produces an error, and each of which has a
class here:

:class:`ExtractorContractTests`
    The evaluator prefers an OpenHands ``final_thought='…', outputs=`` match anywhere in
    the file, then -- if three or more ``[YYYY-MM-DDTHH:MM:SS]`` stamps are present -- the
    text between the third-last and the last of them, and only then the last line. An
    AutoR trajectory is JSON events with ISO timestamps in them, so a run that copied its
    own log through verbatim would be scored on a slice of its progress output. The
    symptom is a plausible paragraph and a plausible score.

:class:`ConclusionRefusalTests` and :class:`ExportTests`
    What may be published, and in what order. The load-bearing one is that a *fallback*
    is never published as the scored line: a run that produced no conclusion has to be
    unscoreable, because a placeholder scores zero and a zero reads like a measurement.

:class:`ExitCodeTests`
    Six clauses, one test each. A single test of the conjunction passes whenever any one
    clause works, which is how a six-part guard rots into a one-part guard with no line
    changing -- the same discipline ``tests/test_fs_adapter.py`` applies to its own.

:class:`DeadlineTests`
    The harness sends SIGKILL at 3600 s. Everything about how the budget is divided is
    here, including the floor that stops a stage being handed thirty seconds.

:class:`GoalContractTests` and :class:`StagingTests`
    What the agent is told, and what it is given. The staging test is the twenty tasks
    that ship no ``data/`` directory -- the shipped ``agents/claude/run.py`` copies it
    unconditionally and raises before it creates its log file, so those twenty produced
    no log at all while the harness printed that they completed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from src import firebench
from src.firebench import (
    FIRE_EXIT_CLAUSES,
    FIRE_FALLBACK_MARKER,
    FIRE_MAX_CONCLUSION_CHARS,
    FIRE_MIN_CONCLUSION_CHARS,
    FIRE_REFUSAL_NO_APPROVED_STAGE,
    REFERENCE_CONCLUSION_CHARS,
    Deadline,
    FireTask,
    append_log,
    build_fire_goal,
    conclusion_content_refusals,
    conclusion_length_refusals,
    conclusion_path_for,
    ensure_fire_workspace,
    export_conclusion,
    fire_exit_code,
    fire_exit_failures,
    fire_workspace_name,
    load_task,
    mirror_run_artifacts,
    open_log,
    preview_task_inputs,
    publish_conclusion_line,
    result_files,
    sanitise_log_body,
    stage_task_inputs,
)
from src.utils import TASK_BEGIN_MARKER, TASK_END_MARKER

#: The evaluator's own two readers, transcribed from
#: ``FIRE-Bench/eval/RAGChecker/utils.py:extract_single_final_thought``. Transcribed
#: rather than imported because the benchmark is not a dependency of this repository --
#: and :meth:`ExtractorContractTests.test_the_transcription_matches_the_checkout` diffs
#: them against the real file whenever a checkout is present, so the copy cannot drift
#: silently.
EVALUATOR_OPENHANDS = re.compile(r"final_thought\s*=\s*(?:'|\")(.+?)(?:'|\"),\s*outputs=", re.DOTALL)
EVALUATOR_CODEX_TIMESTAMP = re.compile(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]")


def evaluator_extract(text: str) -> str | None:
    """The evaluator's three readers, in its order. The oracle this file tests against."""
    matches = EVALUATOR_OPENHANDS.findall(text)
    if matches:
        return matches[-1].encode("utf-8").decode("unicode_escape").strip()
    stamps = list(EVALUATOR_CODEX_TIMESTAMP.finditer(text))
    if len(stamps) >= 3:
        return text[stamps[-3].start(): stamps[-1].start()].strip()
    last_line = text.strip().splitlines()[-1]
    try:
        parsed = json.loads(last_line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "result" in parsed:
        return str(parsed["result"]).strip()
    return None


def bench_checkout() -> Path | None:
    """A real FIRE-Bench checkout, if this box has one. Never required."""
    root = Path(os.environ.get("FIREBENCH_ROOT", Path.home() / "FIRE-Bench")).expanduser()
    return root if (root / "eval" / "RAGChecker" / "utils.py").is_file() else None


class ExtractorContractTests(unittest.TestCase):
    """The last line has to win, against a body that is trying to take the score."""

    def _log(self, body: str, conclusion: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            log = open_log(Path(tmp) / "log.log", agent_id="autor", task_id="t", llm_model="opus")
            append_log(log, body)
            with log.open("a", encoding="utf-8") as handle:
                handle.write("\n" + json.dumps({"result": conclusion}, ensure_ascii=False) + "\n")
            return log.read_text(encoding="utf-8")

    def test_three_iso_timestamps_do_not_steal_the_score(self) -> None:
        body = (
            '{"t": "[2026-08-18T07:30:00] starting"}\n'
            '{"t": "[2026-08-18T07:31:00] running"}\n'
            '{"t": "[2026-08-18T07:32:00] done"}\n'
        )
        text = self._log(body, "Models degrade as depth grows.")
        self.assertEqual(evaluator_extract(text), "Models degrade as depth grows.")

    def test_an_openhands_marker_does_not_steal_the_score(self) -> None:
        body = "some tool output containing final_thought='not the answer', outputs=[] here"
        text = self._log(body, "Models degrade as depth grows.")
        self.assertEqual(evaluator_extract(text), "Models degrade as depth grows.")

    def test_without_the_sanitiser_the_score_is_stolen(self) -> None:
        """The negative control. Without it the two tests above prove nothing.

        A test that only ever sees sanitised input cannot tell a working sanitiser from a
        pattern the evaluator never matched in the first place.
        """
        raw = (
            "header\n[2026-08-18T07:30:00] a\n[2026-08-18T07:31:00] b\n[2026-08-18T07:32:00] c\n"
            + json.dumps({"result": "the real conclusion"})
        )
        self.assertNotEqual(evaluator_extract(raw), "the real conclusion")

    def test_the_sanitiser_changes_no_word_and_no_line_count(self) -> None:
        raw = "[2026-08-18T07:30:00] alpha\nfinal_thought='x', outputs=[]\n"
        cleaned = sanitise_log_body(raw)
        self.assertEqual(len(raw.splitlines()), len(cleaned.splitlines()))
        self.assertEqual(raw.replace("​", ""), cleaned.replace("​", ""))

    def test_the_transcription_matches_the_checkout(self) -> None:
        """The two regexes here are the benchmark's. Diff them when it is on disk."""
        root = bench_checkout()
        if root is None:
            self.skipTest("no FIRE-Bench checkout on this box")
        source = (root / "eval" / "RAGChecker" / "utils.py").read_text(encoding="utf-8")
        self.assertIn(r"final_thought\s*=\s*(?:'|\")(.+?)(?:'|\"),\s*outputs=", source)
        self.assertIn(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]", source)


class ConclusionRefusalTests(unittest.TestCase):
    def test_the_band_brackets_every_reference_conclusion(self) -> None:
        """The floor and the ceiling have to admit what the benchmark itself calls an answer."""
        for length in REFERENCE_CONCLUSION_CHARS:
            self.assertGreaterEqual(length, FIRE_MIN_CONCLUSION_CHARS)
            self.assertLessEqual(length, FIRE_MAX_CONCLUSION_CHARS)

    def test_a_report_is_refused_for_length(self) -> None:
        self.assertIn(
            "length:above_ceiling",
            conclusion_length_refusals("word " * (FIRE_MAX_CONCLUSION_CHARS // 2))[0],
        )

    def test_a_single_word_is_refused_for_length(self) -> None:
        self.assertTrue(any(r.startswith("length:below_floor") for r in conclusion_length_refusals("Yes.")))

    def test_a_plan_is_refused(self) -> None:
        text = "I will design three experiments comparing weak and strong models across depth."
        self.assertIn("content:conclusion_is_a_plan", conclusion_content_refusals(text))

    def test_a_transcript_is_refused(self) -> None:
        text = "assistant: here is what I found about the effect of depth on accuracy in models"
        self.assertIn("content:conclusion_is_a_transcript", conclusion_content_refusals(text))

    def test_a_real_reference_conclusion_is_accepted(self) -> None:
        """The refusals must not fire on what the benchmark itself scores as perfect."""
        text = (
            "Chain-of-thought prompting does not reliably enable large language models to "
            "learn generalizable algorithmic reasoning abilities. It relies on highly "
            "specific, pattern-matching prompts, and performance degrades with increased "
            "problem complexity."
        )
        self.assertEqual(conclusion_length_refusals(text), [])
        self.assertEqual(conclusion_content_refusals(text), [])

    def test_the_word_results_inside_a_sentence_is_not_a_heading(self) -> None:
        """Why this is not FrontierScience's content check.

        That one refuses any text carrying a stage heading, 'Key Results' among them,
        because a FrontierScience answer that carries them is a stage summary. Here the
        deliverable is three sentences of prose and the same rule refuses a good answer.
        """
        text = (
            "Key results held across both model tiers: accuracy fell as the number of "
            "premises grew, and the ordering of premises mattered more than their number."
        )
        self.assertEqual(conclusion_content_refusals(text), [])


class PublishTests(unittest.TestCase):
    def _conclusion(self, source: str, body: str):
        return firebench.FireConclusion(
            path=Path("/dev/null"), source=source, chars=len(body), sha256="x", refusals=()
        )

    def test_a_fallback_is_never_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = open_log(Path(tmp) / "log.log", agent_id="a", task_id="t", llm_model="m")
            written = publish_conclusion_line(
                log, self._conclusion("fallback", "x"), body=FIRE_FALLBACK_MARKER + "\nnothing"
            )
            self.assertFalse(written)
            self.assertIsNone(evaluator_extract(log.read_text(encoding="utf-8")))

    def test_a_later_conclusion_wins_by_being_later(self) -> None:
        """Appending, not rewriting. The crash-safety property, stated as a test.

        A rewrite has a window in which the file holds no result line, and that window is
        exactly when the harness's SIGKILL arrives.
        """
        with tempfile.TemporaryDirectory() as tmp:
            log = open_log(Path(tmp) / "log.log", agent_id="a", task_id="t", llm_model="m")
            publish_conclusion_line(log, self._conclusion("agent", "first"), body="first answer")
            publish_conclusion_line(log, self._conclusion("agent", "second"), body="second answer")
            self.assertEqual(evaluator_extract(log.read_text(encoding="utf-8")), "second answer")


class ExportTests(unittest.TestCase):
    QUESTION = "Does X hold?"
    GOOD = (
        "Prompt formatting changes the measured accuracy of a model substantially, and the "
        "ordering of the effect is not stable across models."
    )

    def _workspace(self, tmp: str) -> Path:
        workspace = Path(tmp) / "ws"
        ensure_fire_workspace(workspace)
        return workspace

    def test_the_agents_own_file_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(tmp)
            conclusion_path_for(workspace).write_text(self.GOOD + "\n", encoding="utf-8")
            result = export_conclusion(workspace=workspace, paths=None, question=self.QUESTION)
            self.assertEqual(result.source, "agent")
            self.assertTrue(result.scoreable)

    def test_a_previous_export_is_not_mistaken_for_the_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(tmp)
            conclusion_path_for(workspace).write_text(self.GOOD + "\n", encoding="utf-8")
            export_conclusion(workspace=workspace, paths=None, question=self.QUESTION)
            again = export_conclusion(workspace=workspace, paths=None, question=self.QUESTION)
            self.assertEqual(again.source, "fallback")

    def test_no_conclusion_and_no_stages_is_a_fallback_with_the_reason_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(tmp)
            calls: list[int] = []

            class Counting:
                def __call__(self, **_kwargs):
                    calls.append(1)
                    return "a synthesized conclusion long enough to clear the floor comfortably."

            result = export_conclusion(
                workspace=workspace,
                paths=object(),
                stages_approved=(),
                synthesize=Counting(),
                question=self.QUESTION,
            )
            self.assertEqual(result.source, "fallback")
            self.assertIn(FIRE_REFUSAL_NO_APPROVED_STAGE, result.refusals)
            self.assertEqual(calls, [], "the synthesizer must not be called with nothing approved")

    def test_a_refused_agent_file_is_recorded_and_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(tmp)
            conclusion_path_for(workspace).write_text("I will run three experiments." * 6, encoding="utf-8")
            result = export_conclusion(workspace=workspace, paths=None, question=self.QUESTION)
            self.assertEqual(result.source, "fallback")
            self.assertTrue(any("conclusion_is_a_plan" in reason for reason in result.refusals))


def _meta(**overrides) -> dict:
    payload = {
        "conclusion_chars": 250,
        "conclusion_source": "agent",
        "log_result_line_written": True,
        "refusals": [],
        "pipeline_completed": True,
    }
    payload.update(overrides)
    return payload


class ExitCodeTests(unittest.TestCase):
    """One test per clause. Six negatives and one positive, deliberately."""

    def test_all_six_clauses_satisfied_is_zero(self) -> None:
        self.assertEqual(fire_exit_failures(_meta()), [])
        self.assertEqual(fire_exit_code(_meta()), 0)

    def test_there_are_exactly_six_clauses(self) -> None:
        self.assertEqual(len(FIRE_EXIT_CLAUSES), 6)

    def test_a_missing_conclusion_fails(self) -> None:
        self.assertIn("conclusion_present", fire_exit_failures(_meta(conclusion_chars=0)))

    def test_a_fallback_fails(self) -> None:
        self.assertIn("conclusion_not_fallback", fire_exit_failures(_meta(conclusion_source="fallback")))

    def test_a_conclusion_past_the_ceiling_fails(self) -> None:
        self.assertIn(
            "conclusion_within_bounds",
            fire_exit_failures(_meta(conclusion_chars=FIRE_MAX_CONCLUSION_CHARS + 1)),
        )

    def test_a_conclusion_that_never_reached_the_log_fails(self) -> None:
        self.assertIn(
            "conclusion_published_to_log", fire_exit_failures(_meta(log_result_line_written=False))
        )

    def test_a_content_refusal_fails(self) -> None:
        self.assertIn(
            "no_content_refusal", fire_exit_failures(_meta(refusals=["content:conclusion_is_a_plan"]))
        )

    def test_an_unfinished_procedure_fails(self) -> None:
        self.assertIn("procedure_completed", fire_exit_failures(_meta(pipeline_completed=False)))

    def test_a_length_refusal_alone_does_not_fail_the_content_clause(self) -> None:
        """The clause reads a prefix, and the two prefixes have to stay apart.

        A length refusal is already caught by ``conclusion_within_bounds``; if the content
        clause caught it too, one of the six would be untestable in isolation and the
        suite could not tell which guard was doing the work.
        """
        self.assertNotIn(
            "no_content_refusal", fire_exit_failures(_meta(refusals=["length:below_floor:12"]))
        )


class DeadlineTests(unittest.TestCase):
    def test_the_reserve_is_never_spent_by_the_walk(self) -> None:
        deadline = Deadline(total_seconds=3600, reserve_seconds=480)
        self.assertLessEqual(deadline.remaining_before_reserve, 3600 - 480)

    def test_a_slice_never_falls_below_the_floor(self) -> None:
        """A thirty-second stage is not a fast stage, it is a timeout with a cost."""
        deadline = Deadline(total_seconds=600, reserve_seconds=480)
        self.assertGreaterEqual(deadline.stage_slice(20), 240)

    def test_slices_divide_what_is_left_and_not_the_total(self) -> None:
        deadline = Deadline(total_seconds=3600, reserve_seconds=600)
        self.assertLessEqual(deadline.stage_slice(4) * 4, 3000 + 4)

    def test_remaining_never_goes_negative(self) -> None:
        deadline = Deadline(total_seconds=0, reserve_seconds=100)
        self.assertEqual(deadline.remaining_before_reserve, 0.0)
        self.assertTrue(deadline.expired())

    def test_the_snapshot_carries_both_halves(self) -> None:
        snapshot = Deadline(total_seconds=3600, reserve_seconds=480).snapshot()
        self.assertEqual(snapshot["deadline_seconds"], 3600)
        self.assertEqual(snapshot["reserve_seconds"], 480)


def _task(tmp: Path, *, instruction: str = "Does X hold?", with_data: bool = False) -> FireTask:
    root = tmp / "papers" / "demo_task"
    (root / "instruction").mkdir(parents=True, exist_ok=True)
    (root / "instruction" / "instruction.txt").write_text(instruction, encoding="utf-8")
    (root / "instruction" / "instruction_gt.txt").write_text("THE ANSWER KEY", encoding="utf-8")
    (root / "conclusion.txt").write_text("THE REFERENCE CONCLUSION", encoding="utf-8")
    if with_data:
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "rows.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    return FireTask(task_id="demo_task", split="verified", root=root, instruction=instruction)


class StagingTests(unittest.TestCase):
    def test_a_task_with_no_data_directory_stages_cleanly(self) -> None:
        """Twenty of the thirty-five verified tasks. The shipped agent raises here."""
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), with_data=False)
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            staged = stage_task_inputs(task, workspace)
            self.assertIsNone(staged["data"])
            self.assertTrue((workspace / "code").is_dir())

    def test_data_is_copied_not_linked_under_the_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), with_data=True)
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            staged = stage_task_inputs(task, workspace)
            self.assertEqual(staged["data_mode"], "copy")
            self.assertFalse((workspace / "data").is_symlink())
            (workspace / "data" / "rows.jsonl").write_text("clobbered", encoding="utf-8")
            self.assertEqual(
                (task.root / "data" / "rows.jsonl").read_text(encoding="utf-8"), '{"a": 1}\n'
            )

    def test_staging_twice_does_not_accumulate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), with_data=True)
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            stage_task_inputs(task, workspace)
            (workspace / "data" / "stray.txt").write_text("x", encoding="utf-8")
            staged = stage_task_inputs(task, workspace)
            self.assertEqual(staged["data"], ["rows.jsonl"])

    def test_the_preview_and_the_staging_report_the_same_data(self) -> None:
        """``--print-goal`` renders the contract the run will render, or it is a fiction."""
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), with_data=True)
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            self.assertEqual(preview_task_inputs(task)["data"], stage_task_inputs(task, workspace)["data"])

    def test_the_task_object_never_carries_the_answer(self) -> None:
        """``conclusion.txt`` and ``instruction_gt.txt`` sit beside the instruction.

        The goal builder is handed a :class:`FireTask`; if either were a field on it, one
        refactor puts the answer key in the prompt and nothing downstream could tell.
        """
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), with_data=True)
            rendered = json.dumps(task.__dict__, default=str)
            self.assertNotIn("THE ANSWER KEY", rendered)
            self.assertNotIn("THE REFERENCE CONCLUSION", rendered)
            self.assertEqual({f for f in task.__dataclass_fields__},
                             {"task_id", "split", "root", "instruction"})


class GoalContractTests(unittest.TestCase):
    def test_the_task_comes_first_and_is_fenced(self) -> None:
        """Four readers excerpt this document by prefix; what is in front is what they see."""
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp), instruction="Does premise order matter?")
            goal = build_fire_goal(task, Path(tmp) / "ws")
            self.assertIn(f"{TASK_BEGIN_MARKER}\nDoes premise order matter?\n{TASK_END_MARKER}", goal)
            self.assertLess(goal.index("Does premise order matter?"), 700)

    def test_the_goal_never_contains_the_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = _task(Path(tmp))
            goal = build_fire_goal(task, Path(tmp) / "ws")
            self.assertNotIn("THE ANSWER KEY", goal)
            self.assertNotIn("THE REFERENCE CONCLUSION", goal)

    def test_the_length_target_is_derived_from_the_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            goal = build_fire_goal(_task(Path(tmp)), Path(tmp) / "ws")
            self.assertIn(str(min(REFERENCE_CONCLUSION_CHARS)), goal)
            self.assertIn(str(max(REFERENCE_CONCLUSION_CHARS)), goal)
            self.assertIn(str(FIRE_MAX_CONCLUSION_CHARS), goal)

    def test_the_catalogue_reaches_the_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            goal = build_fire_goal(
                _task(Path(tmp)),
                Path(tmp) / "ws",
                model_catalog={"openai": ["gpt-x"], "claude": ["claude-y"]},
            )
            self.assertIn("gpt-x", goal)
            self.assertIn("claude-y", goal)

    def test_a_task_with_no_data_says_so_rather_than_saying_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            goal = build_fire_goal(_task(Path(tmp)), Path(tmp) / "ws", staged={"data": None})
            self.assertIn("ships no data", goal)


class ArtifactVisibilityTests(unittest.TestCase):
    """Where the run's measurements are, and where the synthesizer was looking.

    Measured on a real pipeline run: the sandbox's ``code/`` and ``outputs/`` were empty
    while the run tree held 272 files including ``results/responses.jsonl`` and
    ``results/condition_accuracy.json``. The goal contract points stages at the sandbox
    and AutoR's stage contract points them at the run tree; the stages follow the one
    they are always given. The synthesizer -- the one call that turns experiments into
    the scored conclusion -- was therefore listing "(none)".
    """

    class _Paths:
        def __init__(self, root: Path) -> None:
            self.results_dir = root / "results"
            self.code_dir = root / "code"
            self.notes_dir = root / "notes"
            self.data_dir = root / "data"
            for directory in (self.results_dir, self.code_dir, self.notes_dir, self.data_dir):
                directory.mkdir(parents=True, exist_ok=True)

    def test_results_in_the_run_tree_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            paths = self._Paths(Path(tmp) / "run")
            (paths.results_dir / "condition_accuracy.json").write_text("{}", encoding="utf-8")
            listed = result_files(workspace=workspace, paths=paths)
            self.assertTrue(any("condition_accuracy.json" in name for name in listed), listed)

    def test_the_sandbox_alone_would_have_listed_nothing(self) -> None:
        """The negative control: this is exactly what the run produced."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            self.assertEqual(result_files(workspace=workspace, paths=None), [])

    def test_pycache_is_not_a_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            (workspace / "code" / "__pycache__").mkdir(parents=True)
            (workspace / "code" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
            (workspace / "code" / "run.py").write_text("x = 1", encoding="utf-8")
            self.assertEqual(result_files(workspace=workspace, paths=None), ["code/run.py"])

    def test_mirroring_puts_the_artifacts_where_the_contract_said(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            paths = self._Paths(Path(tmp) / "run")
            (paths.code_dir / "run_grid.py").write_text("x = 1", encoding="utf-8")
            (paths.results_dir / "responses.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
            mirror_run_artifacts(workspace, paths)
            self.assertTrue((workspace / "code" / "run_grid.py").is_file())
            self.assertTrue((workspace / "outputs" / "results" / "responses.jsonl").is_file())
            # A copy, not a move: the run tree is the provenance.
            self.assertTrue((paths.results_dir / "responses.jsonl").is_file())

    def test_mirroring_without_a_run_tree_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            ensure_fire_workspace(workspace)
            self.assertEqual(mirror_run_artifacts(workspace, None), {"code": 0, "outputs": 0})


class WorkspaceNameTests(unittest.TestCase):
    def test_a_task_id_with_underscores_survives_the_round_trip(self) -> None:
        """``to_cot_or_not_to_cot`` is a real task id. A single-underscore scheme loses it."""
        name = fire_workspace_name("to_cot_or_not_to_cot", "pipeline", stamp="20260818120000")
        self.assertEqual(name.split("__")[0], "to_cot_or_not_to_cot")
        self.assertEqual(name.split("__")[1], "pipeline")


class TaskLoadingTests(unittest.TestCase):
    def test_an_unknown_task_names_where_it_looked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "benchmark" / "papers").mkdir(parents=True)
            (root / "run_agent.py").write_text("", encoding="utf-8")
            with self.assertRaises(firebench.TaskNotFound) as caught:
                load_task(root, "nope")
            self.assertIn("benchmark/papers/nope", str(caught.exception).replace("\\", "/"))

    def test_a_directory_that_is_not_a_checkout_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(firebench.TaskNotFound):
                firebench.bench_root_from(tmp)


class MeasuredConstantsTests(unittest.TestCase):
    """The numbers in this module came off a checkout. Re-measure when one is present."""

    def test_the_reference_lengths_match_the_checkout(self) -> None:
        root = bench_checkout()
        if root is None:
            self.skipTest("no FIRE-Bench checkout on this box")
        lengths = sorted(
            len(path.read_text(encoding="utf-8").strip())
            for path in sorted((root / "benchmark" / "papers").glob("*/conclusion.txt"))
        )
        self.assertEqual(len(lengths), len(REFERENCE_CONCLUSION_CHARS))
        self.assertEqual(min(lengths), min(REFERENCE_CONCLUSION_CHARS))
        self.assertEqual(max(lengths), max(REFERENCE_CONCLUSION_CHARS))

    def test_the_harness_still_kills_at_the_deadline_this_adapter_assumes(self) -> None:
        root = bench_checkout()
        if root is None:
            self.skipTest("no FIRE-Bench checkout on this box")
        source = (root / "run_agent.py").read_text(encoding="utf-8")
        self.assertIn("TIME_LIMIT = 3600", source)


if __name__ == "__main__":
    unittest.main()
