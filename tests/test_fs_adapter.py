"""A run that reports success while producing nothing is the defect this file guards.

Forty of forty real ResearchClawBench runs on this machine wrote ``status: "completed"``
into ``_meta.json``. Thirty-one of them had auto-skipped at least one stage and seven had
auto-skipped *the very stage being scored*, and the word ``auto_skipped_stages`` appeared
nowhere in the metadata — it existed only in the stdout event stream, which no downstream
reads. The scorer, the leaderboard importer and the trial driver all recorded those runs
as successes, and nothing surfaced it until a human read the transcripts thirteen hours
later.

So the FrontierScience adapter computes its exit code from the same dictionary it writes
to disk, and refuses six separate ways. :class:`ExitCodeTests` flips exactly one conjunct
per test — six negatives and one positive — because a single test of the conjunction is
satisfied by any one clause working, which is how a six-part guard rots into a one-part
guard without a line changing.

The second defect is quieter and has no observable symptom at all: **the agent seeing the
shape of the scoring function.** The rubric is a checklist of independently weighted
specifics, and an agent told that is writing to the marker rather than answering the
question. The first draft of the task instruction contained the sentence "A named
specific is worth more than a correct generality", and nothing in the tree could have
noticed — the run would have completed, the answer would have been longer, the score would
have gone up, and the number would have been about the prompt.
:class:`TheAgentIsNeverToldHowItIsMarkedTests` is the word list, and it carries three
controls: the list is non-empty, a deliberate violation is caught, and the one block that
*is* allowed to describe the marking (``--answer-guidance coverage``, a declared
experimental intervention) trips the same scanner. Without that third control the scanner
could be matching nothing at all and every assertion would still pass.

The third is the one that turns a measurement into a coin flip: **a synthesizer with
nothing to synthesize from.** With zero approved stage summaries, "turn the run's work
into an answer" is the problem asked a second time, and its output is a fresh single-shot
answer published under the pipeline arm's label — the control arm's result recorded as the
treatment's, long, on-topic, and invisible.
:meth:`AnswerResolutionTests.test_the_synthesizer_refuses_when_no_stage_was_approved`
proves the operator is never reached, and its sibling proves the refusal is recorded where
a trial can read it.

No line of the real examination text is committed here. Everything below runs on
``tests/fixtures/fs_synthetic.jsonl`` or on problems written for the test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import fs_agent
from src.frontierscience import (
    DEFAULT_FS_ANSWER_GUIDANCE,
    FS_ANSWER_GUIDANCE_CHOICES,
    FS_COVERAGE_GUIDANCE,
    FS_EXIT_CLAUSES,
    FS_FALLBACK_MARKER,
    FS_MAX_ANSWER_CHARS,
    FS_MIN_ANSWER_CHARS,
    FS_PROFILE_CHOICES,
    FS_REFUSAL_ANSWER_IS_A_PLAN,
    FS_REFUSAL_NO_APPROVED_STAGE,
    FS_SOURCE_AGENT,
    FS_SOURCE_FALLBACK,
    FS_SOURCE_STAGE,
    FS_SOURCE_SYNTHESIZED,
    FS_TASK_INSTRUCTION,
    FS_TASK_INSTRUCTION_SHA256,
    FS_WORKSPACE_CONTRACT,
    AnswerSynthesizer,
    DatasetRefused,
    FsAnswer,
    FsRunResult,
    answer_content_refusals,
    answer_path_for,
    build_fs_goal,
    build_fs_meta,
    export_answer,
    fs_exit_code,
    fs_exit_failures,
    fs_workspace_name,
    infer_fs_task_key,
    resolve_answer_guidance,
    stages_approved_in,
    write_fs_meta,
)
from src.utils import (
    TASK_BEGIN_MARKER,
    TASK_END_MARKER,
    build_run_paths,
    ensure_run_layout,
    task_statement,
    write_text,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
INSTRUCTION_FIXTURE = FIXTURES / "fs_task_instruction.txt"
SYNTHETIC = FIXTURES / "fs_synthetic.jsonl"

#: A problem written here rather than taken from the dataset. Short, and carrying a
#: literal brace so that a rendering bug in ``str.format`` cannot hide: real problems in
#: this split are full of LaTeX.
A_PROBLEM = (
    "A rigid pendulum of length L = 1.00 m swings in air. Give the period in the "
    r"small-angle limit as T = 2\pi\sqrt{L/g}, state the condition under which that "
    "limit holds, and name the dominant loss channel."
)

#: Long enough to clear :data:`FS_MIN_ANSWER_CHARS` and say nothing that trips a content
#: refusal. Used wherever a test needs "a plausible answer" and does not care what it says.
AN_ANSWER = (
    "# Period of the pendulum\n\n"
    "In the small-angle limit the restoring torque is linear in the angular displacement, "
    "so the equation of motion is that of a simple harmonic oscillator and the period is "
    "T = 2*pi*sqrt(L/g) = 2.01 s for L = 1.00 m and g = 9.81 m/s^2. The limit holds while "
    "sin(theta) may be replaced by theta, which costs under one per cent of the restoring "
    "torque below roughly 0.2 rad. Air drag dominates the observed decay: the pivot "
    "contributes a nearly constant Coulomb torque, whereas the drag torque grows with the "
    "square of the bob speed and therefore with the amplitude.\n"
)


def a_synthetic_problem() -> str:
    """The first fixture row's problem. Never a real one."""
    return json.loads(SYNTHETIC.read_text(encoding="utf-8").splitlines()[0])["problem"]


class RecordingOperator:
    """An operator that records every call and makes none.

    Deliberately not a Mock. The property under test is that the synthesizer never
    *reaches* the operator, and a Mock answers every attribute, so a synthesizer that
    called something else entirely would still look untouched.
    """

    fake_mode = False
    model = "recording"

    def __init__(self, reply: str = "") -> None:
        self.reply = reply
        self.calls: list[str] = []

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume, tools=None):
        self.calls.append(str(prompt_path))
        return (["true"], paths.run_root, None)

    def _run_streaming_command(self, *, command, cwd, stage, attempt_no, paths, mode, stdin_text):
        return (0, self.reply, "", None, {})


def a_run_tree(root: Path):
    """A run tree with the layout the operator seam expects."""
    paths = build_run_paths(root / ".autor" / "20260817_000000")
    ensure_run_layout(paths)
    return paths


def a_meta(**overrides) -> dict:
    """A metadata record that passes every exit clause, before the overrides."""
    workspace = Path(overrides.pop("workspace", "/nonexistent"))
    answer = FsAnswer(
        path=Path(overrides.pop("answer_path", str(workspace / "answer.md"))),
        source=overrides.pop("answer_source", FS_SOURCE_AGENT),
        chars=overrides.pop("answer_chars", 900),
        sha256="0" * 64,
        refusals=list(overrides.pop("refusals", [])),
    )
    meta = build_fs_meta(
        workspace=workspace,
        task="fs:000",
        profile="direct",
        answer_guidance="minimal",
        model="opus",
        review_model="opus",
        operator="claude",
        answer=answer,
        pipeline_completed=overrides.pop("pipeline_completed", True),
        auto_skipped_stages=overrides.pop("auto_skipped_stages", []),
        stages_approved=overrides.pop("stages_approved", []),
        disallowed_tools=("WebSearch", "WebFetch"),
        dataset_path=Path("/dataset/research_test.jsonl"),
        dataset_sha256="96c0434a",
        run_id="20260817_000000",
        duration_seconds=12,
    )
    meta.update(overrides)
    return meta


class TheFencedTaskComesFirstTests(unittest.TestCase):
    """Five readers in this tree take a prefix of the goal and one reads the fence."""

    def all_goals(self) -> list[tuple[str, str]]:
        """Every combination of guidance and workspace, labelled."""
        with tempfile.TemporaryDirectory() as tmp:
            return [
                (
                    f"{guidance}/{'workspace' if ws else 'no workspace'}",
                    build_fs_goal(
                        A_PROBLEM,
                        workspace=Path(tmp) if ws else None,
                        answer_guidance=guidance,
                    ),
                )
                for guidance in FS_ANSWER_GUIDANCE_CHOICES
                for ws in (True, False)
            ]

    def test_the_task_fence_opens_in_the_first_line_or_two_of_every_goal(self) -> None:
        for label, goal in self.all_goals():
            with self.subTest(combination=label):
                self.assertIn(TASK_BEGIN_MARKER, goal)
                self.assertIn(TASK_END_MARKER, goal)
                self.assertLess(
                    goal.index(TASK_BEGIN_MARKER),
                    120,
                    "the fence has to be at the top: the router, the deliberation panel "
                    "and the validity reviewer each read a prefix, and a contract in "
                    "front of the task is what they read instead of the question",
                )

    def test_every_goal_yields_the_problem_and_only_the_problem(self) -> None:
        for label, goal in self.all_goals():
            with self.subTest(combination=label):
                self.assertEqual(task_statement(goal), A_PROBLEM)

    def test_without_the_fence_the_reader_returns_the_whole_contract(self) -> None:
        """The control. Without it the assertion above could be true of any string.

        This is the measured failure it stands for: read off an unfenced goal,
        ``demanding_sentences`` returned 23 requirements for a task that has 10, and the
        first phantom was the adapter's own banner.
        """
        unfenced = build_fs_goal(A_PROBLEM).replace(TASK_BEGIN_MARKER, "").replace(TASK_END_MARKER, "")
        recovered = task_statement(unfenced)
        self.assertNotEqual(recovered, A_PROBLEM)
        self.assertIn("What is being asked of you", recovered)

    def test_a_problem_full_of_braces_survives_rendering(self) -> None:
        """Real problems in this split are LaTeX, and ``str.format`` reads a brace."""
        goal = build_fs_goal(a_synthetic_problem() + r" Give \frac{a}{b} and \{x\}.")
        self.assertIn(r"\frac{a}{b}", goal)
        self.assertIn(r"\{x\}", goal)


class TheAgentIsNeverToldHowItIsMarkedTests(unittest.TestCase):
    """The rubric is the scoring function, and the agent must not see its shape."""

    #: Forbidden in the task instruction and in the workspace contract alike.
    SCORING_WORDS = ("worth more", "earns", "lost mark", "points", "credit", "score", "weighted")

    #: Forbidden in the workspace contract only. It is plumbing — where the file goes —
    #: and a sentence about what a good answer contains belongs in the instruction, where
    #: it is one block with one digest rather than two places to keep in step.
    CONTRACT_ONLY_WORDS = ("every part", "derivation", "specific", "complete")

    def scan(self, text: str, words) -> list[str]:
        lowered = text.lower()
        return [word for word in words if word in lowered]

    def test_the_task_instruction_never_describes_the_marking(self) -> None:
        self.assertEqual(self.scan(FS_TASK_INSTRUCTION, self.SCORING_WORDS), [])

    def test_the_workspace_contract_never_describes_the_marking_or_the_answer(self) -> None:
        self.assertEqual(
            self.scan(FS_WORKSPACE_CONTRACT, self.SCORING_WORDS + self.CONTRACT_ONLY_WORDS), []
        )

    def test_the_word_list_is_not_empty(self) -> None:
        """A scanner over an empty list passes on every input, silently."""
        self.assertGreaterEqual(len(self.SCORING_WORDS), 5)
        self.assertGreaterEqual(len(self.CONTRACT_ONLY_WORDS), 3)

    def test_the_scan_catches_a_deliberate_violation(self) -> None:
        violation = FS_TASK_INSTRUCTION + "\n- A named specific is worth more than a generality."
        self.assertEqual(self.scan(violation, self.SCORING_WORDS), ["worth more"])

    def test_the_one_block_allowed_to_say_it_trips_the_same_scan(self) -> None:
        """The strongest control available: a real string that must fail the gate.

        ``--answer-guidance coverage`` is a declared prompt intervention, so it is
        *supposed* to describe the marking. If the scanner returned nothing here it would
        be matching nothing anywhere, and the two assertions above would be vacuous.
        """
        hits = self.scan(FS_COVERAGE_GUIDANCE, self.SCORING_WORDS)
        self.assertIn("worth more", hits)
        self.assertIn("earns", hits)
        self.assertIn("lost mark", hits)

    def test_the_coverage_block_is_off_unless_it_is_asked_for(self) -> None:
        self.assertNotIn(FS_COVERAGE_GUIDANCE, build_fs_goal(A_PROBLEM))
        self.assertNotIn(FS_COVERAGE_GUIDANCE, build_fs_goal(A_PROBLEM, answer_guidance="paper"))
        self.assertIn(FS_COVERAGE_GUIDANCE, build_fs_goal(A_PROBLEM, answer_guidance="coverage"))

    def test_the_default_guidance_is_the_one_that_says_nothing_about_marking(self) -> None:
        self.assertEqual(DEFAULT_FS_ANSWER_GUIDANCE, "minimal")
        self.assertEqual(build_fs_goal(A_PROBLEM), build_fs_goal(A_PROBLEM, answer_guidance="minimal"))


class TheTaskInstructionIsFrozenTests(unittest.TestCase):
    """Two arms are comparable only if they were given the same words."""

    def test_the_published_digest_is_the_digest_of_the_shipped_block(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(FS_TASK_INSTRUCTION.encode("utf-8")).hexdigest(),
            FS_TASK_INSTRUCTION_SHA256,
            "the task instruction moved; decide whether numbers produced under the old "
            "one still stand before updating this constant",
        )

    def test_the_block_matches_its_fixture_byte_for_byte(self) -> None:
        self.assertEqual(INSTRUCTION_FIXTURE.read_text(encoding="utf-8"), FS_TASK_INSTRUCTION)

    def test_the_fixture_is_the_prompt_and_not_a_summary_of_it(self) -> None:
        """The control on the pin above: a fixture that is a paraphrase pins nothing."""
        text = INSTRUCTION_FIXTURE.read_text(encoding="utf-8")
        self.assertIn("No browsing.", text)
        self.assertIn("{problem}", text)
        self.assertGreater(len(text), 1000)


class TheWorkspaceContractIsPipelineOnlyTests(unittest.TestCase):
    def test_a_direct_call_is_told_nothing_about_a_workspace(self) -> None:
        """Its reply is the answer, so there is no file for it to write and no path."""
        goal = build_fs_goal(A_PROBLEM, workspace=None)
        self.assertNotIn("Where the answer goes", goal)
        self.assertNotIn("answer.md", goal)

    def test_the_pipeline_arm_is_given_the_absolute_path_it_must_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "fs000_ideate"
            goal = build_fs_goal(A_PROBLEM, workspace=workspace)
            self.assertIn(str(answer_path_for(workspace.resolve())), goal)

    def test_an_unknown_guidance_is_refused_rather_than_defaulted(self) -> None:
        with self.assertRaises(DatasetRefused):
            resolve_answer_guidance("covrage")
        self.assertEqual(resolve_answer_guidance(None), DEFAULT_FS_ANSWER_GUIDANCE)


class AnAnswerThatIsAPlanIsNotAnAnswerTests(unittest.TestCase):
    """A 250-character "I will (1)... (2)..." clears every length and format check."""

    def test_a_stage_summary_reaching_the_answer_is_refused(self) -> None:
        summary = "# Stage 02\n\n## Objective\n\nSomething.\n\n## What I Did\n\nSomething else.\n"
        reasons = answer_content_refusals(summary)
        self.assertTrue(any(reason.startswith(FS_REFUSAL_ANSWER_IS_A_PLAN) for reason in reasons))
        self.assertIn("Objective", reasons[0])

    def test_placeholder_text_is_refused(self) -> None:
        self.assertTrue(
            any(
                reason.startswith(FS_REFUSAL_ANSWER_IS_A_PLAN)
                for reason in answer_content_refusals(AN_ANSWER + "\n[TODO: finish part 3]\n")
            )
        )

    def test_an_answer_that_merely_uses_the_word_objective_is_not_refused(self) -> None:
        """The control, and the reason the match is anchored on a heading.

        A bare substring test refuses "The objective is to show that..." — ordinary
        English in a physics answer — and a false refusal costs the whole task, where a
        missed detection costs one low score in a population of sixty.
        """
        prose = AN_ANSWER + "\nThe objective is to show that the key results scale as L^(1/2).\n"
        self.assertEqual(answer_content_refusals(prose), [])

    def test_a_clean_answer_is_not_refused(self) -> None:
        self.assertEqual(answer_content_refusals(AN_ANSWER), [])


class AnswerResolutionTests(unittest.TestCase):
    """Four paths, first that yields real content, and one of them must refuse."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "fs000_direct"
        self.workspace.mkdir(parents=True)

    def test_a_direct_reply_is_the_agents_own_answer(self) -> None:
        answer = export_answer(workspace=self.workspace, direct_answer=AN_ANSWER)
        self.assertEqual(answer.source, FS_SOURCE_AGENT)
        self.assertEqual(answer.refusals, [])
        self.assertIn("2.01 s", answer_path_for(self.workspace).read_text(encoding="utf-8"))

    def test_an_answer_the_agent_wrote_itself_outranks_everything(self) -> None:
        write_text(answer_path_for(self.workspace), AN_ANSWER)
        answer = export_answer(workspace=self.workspace)
        self.assertEqual(answer.source, FS_SOURCE_AGENT)

    def test_this_adapters_own_export_is_not_read_back_as_the_agents_work(self) -> None:
        """Without the digest marker, ``--export-only`` republishes its own output forever."""
        first = export_answer(workspace=self.workspace, direct_answer=AN_ANSWER)
        self.assertEqual(first.source, FS_SOURCE_AGENT)
        second = export_answer(workspace=self.workspace)
        self.assertEqual(second.source, FS_SOURCE_FALLBACK)

    def test_the_synthesizer_refuses_when_no_stage_was_approved(self) -> None:
        """Blocker: with nothing approved, "synthesis" is the problem asked twice."""
        paths = a_run_tree(self.workspace)
        operator = RecordingOperator(reply=AN_ANSWER)
        synthesizer = AnswerSynthesizer(operator)
        self.assertIsNone(
            synthesizer(paths=paths, workspace=self.workspace, problem=A_PROBLEM, stages_approved=[])
        )
        self.assertEqual(operator.calls, [], "the operator must never be reached")

    def test_the_refusal_reaches_the_ledger_a_trial_reads(self) -> None:
        paths = a_run_tree(self.workspace)
        operator = RecordingOperator(reply=AN_ANSWER)
        answer = export_answer(
            workspace=self.workspace,
            paths=paths,
            stages_approved=[],
            synthesize=AnswerSynthesizer(operator),
            problem=A_PROBLEM,
        )
        self.assertIn(FS_REFUSAL_NO_APPROVED_STAGE, answer.refusals)
        self.assertEqual(answer.source, FS_SOURCE_FALLBACK)
        self.assertEqual(operator.calls, [])

    def test_the_synthesizer_runs_once_a_stage_has_been_approved(self) -> None:
        """The other half: the refusal above has to be about the approval, not the wiring."""
        paths = a_run_tree(self.workspace)
        operator = RecordingOperator(reply=AN_ANSWER)
        answer = export_answer(
            workspace=self.workspace,
            paths=paths,
            stages_approved=["02_hypothesis_generation"],
            synthesize=AnswerSynthesizer(operator),
            problem=A_PROBLEM,
        )
        self.assertEqual(answer.source, FS_SOURCE_SYNTHESIZED)
        self.assertEqual(len(operator.calls), 1)

    def test_a_synthesis_that_wrote_nothing_does_not_relabel_the_old_file(self) -> None:
        """The file was already there, and it was ours. A silent call must not claim it.

        Reaching synthesis means the exporter rejected whatever was at the scored path --
        usually this adapter's own fallback from an earlier pass. The synthesis prompt
        asks the model to write that same file, so a call that writes nothing leaves the
        old bytes in place, and reading them back would publish a fallback under
        ``answer_source: synthesized``.
        """
        paths = a_run_tree(self.workspace)
        export_answer(workspace=self.workspace)  # leaves a fallback at the scored path
        operator = RecordingOperator(reply="")  # the call comes back with nothing
        answer = export_answer(
            workspace=self.workspace,
            paths=paths,
            stages_approved=["02_hypothesis_generation"],
            synthesize=AnswerSynthesizer(operator),
            problem=A_PROBLEM,
        )
        self.assertEqual(len(operator.calls), AnswerSynthesizer.MAX_ATTEMPTS)
        self.assertEqual(answer.source, FS_SOURCE_FALLBACK)

    def test_the_stage_summary_is_the_last_thing_before_the_fallback(self) -> None:
        paths = a_run_tree(self.workspace)
        write_text(
            paths.stages_dir / "02_hypothesis_generation.md",
            "# Stage 02: Hypothesis Generation\n\n## Key Results\n\n" + AN_ANSWER,
        )
        answer = export_answer(
            workspace=self.workspace,
            paths=paths,
            stages_approved=["02_hypothesis_generation"],
            synthesize=None,
            problem=A_PROBLEM,
        )
        self.assertEqual(answer.source, FS_SOURCE_STAGE)

    def test_a_fallback_says_so_in_the_file_and_not_only_in_the_metadata(self) -> None:
        """Two witnesses. Metadata can be regenerated; a line in the file travels with it."""
        answer = export_answer(workspace=self.workspace)
        self.assertEqual(answer.source, FS_SOURCE_FALLBACK)
        body = answer_path_for(self.workspace).read_text(encoding="utf-8")
        self.assertTrue(body.startswith(FS_FALLBACK_MARKER))


class AnswerLengthBoundsTests(unittest.TestCase):
    """200, not 1200, and 150,000 is a refusal rather than a knife."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "fs000_direct"
        self.workspace.mkdir(parents=True)

    def test_an_eight_hundred_character_derivation_is_a_legitimate_answer(self) -> None:
        """The reason this floor is not the report floor the sibling benchmark uses."""
        self.assertLess(FS_MIN_ANSWER_CHARS, 800)
        answer = export_answer(workspace=self.workspace, direct_answer="x" * 800)
        self.assertEqual(answer.source, FS_SOURCE_AGENT)
        self.assertEqual(answer.refusals, [])

    def test_a_reply_under_the_floor_is_not_taken_as_the_answer(self) -> None:
        answer = export_answer(workspace=self.workspace, direct_answer="x" * (FS_MIN_ANSWER_CHARS - 1))
        self.assertEqual(answer.source, FS_SOURCE_FALLBACK)

    def test_a_short_reply_is_told_apart_from_a_call_that_never_returned(self) -> None:
        """Both end in a fallback, and the ledger has to say which happened.

        The length check at the end of the export runs against whatever was published, so
        for a short reply it inspects the fallback and finds it well formed. Without the
        reply's own length recorded, "the model answered in forty characters" and "the
        call timed out" are one entry.
        """
        short = export_answer(workspace=self.workspace, direct_answer="too short")
        self.assertTrue(any("driver:answer_out_of_bounds" in reason for reason in short.refusals))

        silent = export_answer(workspace=self.workspace, direct_answer=None)
        self.assertEqual(silent.refusals, [])
        self.assertEqual(silent.source, FS_SOURCE_FALLBACK)

    def test_the_fallbacks_own_shape_is_not_charged_to_the_run(self) -> None:
        """A fallback quotes the stage summaries, headings and all.

        Running the content check over it would record ``answer_is_a_plan`` against a run
        whose actual failure was producing no answer, and the ledger would name the wrong
        defect. The fallback is refused by its own clause; it does not need a second,
        wrong reason.
        """
        paths = a_run_tree(self.workspace)
        write_text(
            paths.stages_dir / "02_hypothesis_generation.md",
            "# Stage 02: Hypothesis Generation\n\n## Objective\n\nToo short to publish.\n",
        )
        answer = export_answer(workspace=self.workspace, paths=paths)
        self.assertEqual(answer.source, FS_SOURCE_FALLBACK)
        self.assertEqual(answer.refusals, [])
        self.assertIn("Objective", answer_path_for(self.workspace).read_text(encoding="utf-8"))

    def test_an_answer_past_the_ceiling_is_refused_and_not_truncated(self) -> None:
        oversize = "x" * (FS_MAX_ANSWER_CHARS + 1)
        answer = export_answer(workspace=self.workspace, direct_answer=oversize)
        self.assertGreater(answer.chars, FS_MAX_ANSWER_CHARS)
        self.assertTrue(any("driver:answer_out_of_bounds" in reason for reason in answer.refusals))
        self.assertEqual(
            len(answer_path_for(self.workspace).read_text(encoding="utf-8").strip()),
            FS_MAX_ANSWER_CHARS + 1,
            "the file must still hold what the model produced: truncating would hand a "
            "judge a sentence that stops mid-clause and score it",
        )


class ExitCodeTests(unittest.TestCase):
    """Six conjuncts, six negative tests. One test of the conjunction tests one clause."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name)
        write_text(answer_path_for(self.workspace), AN_ANSWER)

    def passing(self, **overrides) -> dict:
        return a_meta(workspace=self.workspace, **overrides)

    def test_a_run_that_satisfies_every_clause_exits_zero(self) -> None:
        meta = self.passing()
        self.assertEqual(fs_exit_failures(meta), [])
        self.assertEqual(fs_exit_code(meta), 0)
        self.assertEqual(meta["status"], "completed")

    def test_a_missing_answer_file_exits_non_zero(self) -> None:
        answer_path_for(self.workspace).unlink()
        self.assertEqual(fs_exit_failures(self.passing()), ["answer_present"])
        self.assertEqual(fs_exit_code(self.passing()), 1)

    def test_an_answer_under_the_floor_exits_non_zero(self) -> None:
        meta = self.passing(answer_chars=FS_MIN_ANSWER_CHARS - 1)
        self.assertEqual(fs_exit_failures(meta), ["answer_within_bounds"])

    def test_an_answer_over_the_ceiling_exits_non_zero(self) -> None:
        meta = self.passing(answer_chars=FS_MAX_ANSWER_CHARS + 1)
        self.assertEqual(fs_exit_failures(meta), ["answer_within_bounds"])

    def test_a_fallback_answer_exits_non_zero(self) -> None:
        meta = self.passing(answer_source=FS_SOURCE_FALLBACK)
        self.assertEqual(fs_exit_failures(meta), ["answer_not_fallback"])

    def test_a_pipeline_that_did_not_complete_exits_non_zero(self) -> None:
        """The clause the sibling benchmark did not have. It is the one that fires here.

        When Stage 02 exhausts its retries under ``--max-auto-skips 0`` the manager routes
        to the deliverable, finds it is already at the final stage, and aborts —
        ``auto_skipped_stages`` stays *empty* the whole way. Only this clause sees it.
        """
        meta = self.passing(pipeline_completed=False)
        self.assertEqual(fs_exit_failures(meta), ["pipeline_completed"])

    def test_an_auto_skipped_stage_exits_non_zero(self) -> None:
        meta = self.passing(auto_skipped_stages=["02_hypothesis_generation"])
        self.assertEqual(fs_exit_failures(meta), ["no_auto_skips"])

    def test_an_answer_that_is_a_plan_exits_non_zero(self) -> None:
        meta = self.passing(refusals=[FS_REFUSAL_ANSWER_IS_A_PLAN + ":Objective"])
        self.assertEqual(fs_exit_failures(meta), ["no_content_refusal"])

    def test_every_declared_clause_is_one_the_checker_can_report(self) -> None:
        """The control on the six tests above: a clause nobody can fail is decoration."""
        names = {name for name, _reason, _holds in FS_EXIT_CLAUSES}
        self.assertEqual(len(names), 6)
        reachable = set()
        answer_path_for(self.workspace).unlink()
        reachable.update(fs_exit_failures(self.passing()))
        write_text(answer_path_for(self.workspace), AN_ANSWER)
        for overrides in (
            {"answer_chars": 1},
            {"answer_source": FS_SOURCE_FALLBACK},
            {"pipeline_completed": False},
            {"auto_skipped_stages": ["02_hypothesis_generation"]},
            {"refusals": [FS_REFUSAL_ANSWER_IS_A_PLAN]},
        ):
            reachable.update(fs_exit_failures(self.passing(**overrides)))
        self.assertEqual(reachable, names)

    def test_every_clause_gives_a_reason_and_a_predicate(self) -> None:
        """A clause with a name and no predicate is a refusal that never fires."""
        for name, reason, holds in FS_EXIT_CLAUSES:
            with self.subTest(clause=name):
                self.assertGreater(len(reason), 30, f"{name}: the reason restates the name")
                self.assertTrue(callable(holds), f"{name}: no predicate evaluates this clause")

    def test_the_checker_walks_the_declared_table_and_not_a_second_copy(self) -> None:
        """A declared list beside a hand-written ladder is one rule written twice.

        Removing a clause from the table has to remove it from the verdict. If it does
        not, the table is documentation and the ladder is the gate, and the two can
        disagree without anything failing.
        """
        import unittest.mock

        from src import frontierscience

        without_pipeline = tuple(
            clause for clause in FS_EXIT_CLAUSES if clause[0] != "pipeline_completed"
        )
        meta = self.passing(pipeline_completed=False)
        self.assertEqual(fs_exit_failures(meta), ["pipeline_completed"])
        with unittest.mock.patch.object(frontierscience, "FS_EXIT_CLAUSES", without_pipeline):
            self.assertEqual(fs_exit_failures(meta), [])


class MetadataCarriesWhatTheVerdictNeedsTests(unittest.TestCase):
    """Every field the exit code and a trial's admission clauses read is in the file."""

    #: The fields a downstream may not have to reconstruct. ``pipeline_completed``,
    #: ``auto_skipped_stages`` and ``stages_approved`` head the list because their absence
    #: is the measured defect: on the sibling benchmark the first was written and the
    #: second existed only in stdout, so a workspace could say "completed" while the scored
    #: stage had been skipped.
    REQUIRED = (
        "pipeline_completed",
        "auto_skipped_stages",
        "stages_approved",
        "answer_source",
        "answer_chars",
        "answer_sha256",
        "refusals",
        "profile",
        "answer_guidance",
        "task_instruction_sha256",
        "disallowed_tools",
        "model",
        "task",
        "dataset_sha256",
    )

    def test_the_record_carries_all_fourteen_load_bearing_fields(self) -> None:
        meta = a_meta()
        for field in self.REQUIRED:
            with self.subTest(field=field):
                self.assertIn(field, meta)

    def test_the_status_is_computed_from_the_clauses_and_not_handed_in(self) -> None:
        """A status somebody passes in is a claim. Forty of forty runs got that claim wrong."""
        meta = a_meta(pipeline_completed=False)
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["exit_clause_failures"], ["answer_present", "pipeline_completed"])

    def test_writing_the_record_preserves_what_an_outer_harness_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "_meta.json").write_text(
                json.dumps({"agent_cmd": "fs_agent.py --profile ideate", "arm": "treatment"}),
                encoding="utf-8",
            )
            write_fs_meta(workspace, a_meta(workspace=workspace))
            written = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(written["arm"], "treatment")
        self.assertEqual(written["task"], "fs:000")

    def test_the_result_object_and_the_metadata_cannot_disagree(self) -> None:
        meta = a_meta(pipeline_completed=False)
        result = FsRunResult(workspace=Path("/nonexistent"), meta=meta)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.failures, meta["exit_clause_failures"])


class StagesApprovedIsTheNarrowClaimTests(unittest.TestCase):
    """A skipped stage is written into approved memory too, so memory is the wrong witness."""

    def test_a_run_with_no_manifest_has_approved_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(stages_approved_in(a_run_tree(Path(tmp))), [])

    def test_only_a_reviewed_stage_counts_as_approved(self) -> None:
        from src.manifest import initialize_run_manifest, save_run_manifest

        with tempfile.TemporaryDirectory() as tmp:
            paths = a_run_tree(Path(tmp))
            manifest = initialize_run_manifest(paths)
            stages = []
            for entry in manifest.stages:
                if entry.slug == "02_hypothesis_generation":
                    entry = entry.__class__(**{**entry.__dict__, "approved": True, "status": "approved"})
                elif entry.slug == "03_study_design":
                    entry = entry.__class__(
                        **{**entry.__dict__, "approved": True, "skipped": True, "status": "skipped"}
                    )
                stages.append(entry)
            save_run_manifest(paths.run_manifest, manifest.__class__(**{**manifest.__dict__, "stages": stages}))
            self.assertEqual(stages_approved_in(paths), ["02_hypothesis_generation"])


class TheIdeateArmIsOneStageAndNothingElseTests(unittest.TestCase):
    """Everything that is off is off because it is a second thing changing."""

    def a_manager(self, argv: list[str] | None = None):
        args = fs_agent.parse_args(["--fake-operator", *(argv or [])])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        workspace = Path(tmp.name)
        from src.terminal_ui import TerminalUI

        return fs_agent.build_manager(
            args,
            workspace=workspace,
            runs_dir=workspace / ".autor",
            operator=fs_agent.create_operator(
                "claude",
                model="sonnet",
                codex_sandbox="workspace-write",
                fake_mode=True,
                ui=TerminalUI(interactive=False),
                stage_timeout=60,
            ),
            ui=TerminalUI(interactive=False),
            review_backend="claude",
            review_model="sonnet",
        )

    def test_the_walk_is_linear_with_routing_off_and_no_evolution_rounds(self) -> None:
        manager = self.a_manager()
        self.assertEqual(manager.stage_graph.name, "linear")
        self.assertEqual(manager.router.mode, "off")
        self.assertEqual(manager._walk_settings["evolve_rounds"], 0)
        self.assertEqual(manager.max_rounds, 1)

    def test_no_archive_and_no_cross_reviewer_are_seated(self) -> None:
        manager = self.a_manager()
        self.assertIsNone(manager.router.archive)
        self.assertIsNone(manager.cross_reviewer)

    def test_the_auto_skip_budget_is_zero(self) -> None:
        self.assertEqual(self.a_manager().max_auto_skips, 0)
        self.assertEqual(fs_agent.DEFAULT_FS_MAX_AUTO_SKIPS, 0)

    def test_the_ideation_panel_is_assigned_after_construction(self) -> None:
        self.assertIsNotNone(self.a_manager().ideation_panel)
        self.assertIsNone(self.a_manager(["--no-ideation-panel"]).ideation_panel)

    def test_the_panel_is_an_attribute_and_not_a_constructor_keyword(self) -> None:
        """The control. Passing it as a keyword raises, which is why the code assigns it."""
        from src.manager import ResearchManager

        with self.assertRaises(TypeError):
            ResearchManager(
                project_root=REPO,
                runs_dir=REPO,
                operator=RecordingOperator(),
                ideation_panel=object(),
            )

    def test_the_defaults_that_are_load_bearing_are_the_measured_ones(self) -> None:
        args = fs_agent.parse_args([])
        self.assertEqual(args.stage_timeout, 3600)
        self.assertEqual(args.max_attempts, 2)
        self.assertEqual(args.max_auto_skips, 0)
        self.assertEqual(args.web_search, "off")
        self.assertEqual(args.first_stage, "02_hypothesis_generation")
        self.assertEqual(args.final_stage, "02_hypothesis_generation")


class BrowsingIsDeniedOnBothArmsTests(unittest.TestCase):
    """The protocol is the same for the control and the treatment, or there is no pair."""

    def test_the_default_denies_the_two_browsing_tools_to_the_cli(self) -> None:
        from src.web_search import disallowed_tools_for

        args = fs_agent.parse_args([])
        self.assertEqual(disallowed_tools_for(args.web_search), ("WebSearch", "WebFetch"))

    def test_the_operator_is_built_with_those_tools_denied(self) -> None:
        from src.terminal_ui import TerminalUI

        operator = fs_agent.create_operator(
            "claude",
            model="sonnet",
            codex_sandbox="workspace-write",
            fake_mode=True,
            ui=TerminalUI(interactive=False),
            stage_timeout=60,
            disallowed_tools=("WebSearch", "WebFetch"),
        )
        self.assertEqual(operator.disallowed_tools, ("WebSearch", "WebFetch"))

    def test_a_run_records_which_tools_it_denied(self) -> None:
        """Recorded rather than implied: two arms given different lists is not a pair."""
        self.assertEqual(a_meta()["disallowed_tools"], ["WebSearch", "WebFetch"])

    def test_no_search_tool_is_offered_to_either_operator(self) -> None:
        """The other half of `off`: denying the tool and offering an MCP one is neither."""
        from src.terminal_ui import TerminalUI

        operator = fs_agent.create_operator(
            "claude",
            model="sonnet",
            codex_sandbox="workspace-write",
            fake_mode=True,
            ui=TerminalUI(interactive=False),
            stage_timeout=60,
        )
        self.assertFalse(operator.web_search_mcp)


class WorkspaceNamingTests(unittest.TestCase):
    def test_two_workspaces_named_in_the_same_second_do_not_collide(self) -> None:
        """A second was not enough: two arms in one directory made the paired delta zero."""
        names = {fs_workspace_name("fs:043", "direct-opus") for _ in range(50)}
        self.assertGreater(len(names), 1)
        self.assertTrue(all(name.startswith("fs043_direct-opus_") for name in names))

    def test_the_task_key_is_recoverable_from_the_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / fs_workspace_name("fs:043", "ideate")
            workspace.mkdir()
            self.assertEqual(infer_fs_task_key(workspace), "fs:043")

    def test_a_directory_that_carries_no_key_is_not_guessed_at(self) -> None:
        """The control. A wrong guess scores one question against another's rubric."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(infer_fs_task_key(Path(tmp)))

    def test_a_run_with_no_task_and_no_named_workspace_is_refused(self) -> None:
        """And refused before the dataset is opened, so the message names what is missing.

        The path handed in does not exist. That is the assertion: a refusal that had to
        read sixty rows first would say "no dataset here" to a user whose actual mistake
        was not naming a question, and this test would pass or fail depending on whether
        the machine happened to have the split.
        """
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DatasetRefused) as caught:
                fs_agent.resolve_task_row(
                    dataset="/nonexistent/research_test.jsonl", task=None, workspace=Path(tmp)
                )
        self.assertIn("No task selected", str(caught.exception))


class TheScoreNeverReachesTheRunArchiveTests(unittest.TestCase):
    """A rubric total out of ten must not be stored where a fitness in [0, 1] lives."""

    FENCED = ("Archive(", "record_run", "runs.jsonl")

    def test_neither_the_front_end_nor_the_adapter_touches_the_archive(self) -> None:
        for name in ("fs_agent.py", "src/frontierscience.py"):
            source = (REPO / name).read_text(encoding="utf-8")
            for token in self.FENCED:
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, source)

    def test_the_fence_would_notice_the_thing_it_forbids(self) -> None:
        """The control: the tokens are spelled the way the tree spells them."""
        archive_source = (REPO / "src" / "archive.py").read_text(encoding="utf-8")
        self.assertIn("record_run", archive_source)
        self.assertIn("runs.jsonl", archive_source)


class TheFrontEndDeclaresTwoArmsAndNoMoreTests(unittest.TestCase):
    def test_the_profiles_are_exactly_the_control_and_the_treatment(self) -> None:
        self.assertEqual(FS_PROFILE_CHOICES, ("direct", "ideate"))

    def test_the_front_end_declares_more_than_twenty_flags(self) -> None:
        """`tests/test_cli_flags_are_read.py` is the gate; this is the population check."""
        import re

        source = (REPO / "fs_agent.py").read_text(encoding="utf-8")
        self.assertGreater(len(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)), 20)


def dataset_present() -> bool:
    """Whether the pinned split is on this machine, in the order the code looks for it.

    A skip, not a failure. The dataset is not committed and CI installs nothing, so on a
    clean runner the end-to-end class below is absent rather than red; every guarantee it
    checks also has a unit test above that runs everywhere.
    """
    from src.frontierscience import resolve_dataset_path

    return resolve_dataset_path(None).is_file()


@unittest.skipUnless(dataset_present(), "the pinned FrontierScience split is not on this machine")
class BothArmsRunEndToEndUnderTheFakeOperatorTests(unittest.TestCase):
    """The whole path: dataset, goal, run, export, metadata, exit code.

    Under ``--fake-operator``, which is the only mode a test may use: the real operator
    spawns a coding agent with permissions bypassed, and a suite that could do that is a
    suite nobody can run.
    """

    def a_workspace(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name) / "fs000_arm"

    def run_agent(self, *argv: str) -> tuple[int, dict]:
        """Run the front end and capture its log rather than printing it into the suite.

        The log is the harness's own event stream and the terminal UI's frames; a suite
        that prints them buries every other test's failure message under a run trace.
        """
        import contextlib
        import io

        workspace = self.a_workspace()
        with contextlib.redirect_stdout(io.StringIO()):
            code = fs_agent.main(
                ["--fake-operator", "--task", "fs:000", "--workspace", str(workspace), *argv]
            )
        meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        return code, meta

    def test_the_direct_arm_answers_and_exits_zero(self) -> None:
        code, meta = self.run_agent("--profile", "direct")
        self.assertEqual(code, 0)
        self.assertEqual(meta["answer_source"], FS_SOURCE_AGENT)
        self.assertTrue(meta["pipeline_completed"])
        self.assertEqual(meta["auto_skipped_stages"], [])
        self.assertEqual(meta["refusals"], [])
        self.assertTrue(meta["fake_operator"], "a smoke artifact has to say it is one")

    def test_the_recorded_dataset_digest_is_the_one_on_disk(self) -> None:
        """Measured, not copied from the pin, even though the two must agree today.

        ``load_dataset`` refuses a file whose digest is not the pinned one, so recording
        the constant would produce a field that agrees with itself by construction and
        witnesses nothing. This asserts the recorded value is the hash of the bytes the
        run actually read.
        """
        import hashlib

        from src.frontierscience import FS_DATASET_SHA256, resolve_dataset_path

        _code, meta = self.run_agent("--profile", "direct")
        on_disk = hashlib.sha256(Path(meta["dataset_path"]).read_bytes()).hexdigest()
        self.assertEqual(meta["dataset_sha256"], on_disk)
        self.assertEqual(on_disk, FS_DATASET_SHA256)
        self.assertEqual(Path(meta["dataset_path"]), resolve_dataset_path(None))

    def test_the_pipeline_arm_approves_stage_two_and_nothing_else(self) -> None:
        code, meta = self.run_agent("--profile", "ideate")
        self.assertEqual(code, 0)
        self.assertEqual(meta["stages_approved"], ["02_hypothesis_generation"])
        self.assertTrue(meta["pipeline_completed"])
        self.assertEqual(meta["auto_skipped_stages"], [])

    def test_a_pipeline_arm_whose_only_stage_fails_exits_non_zero_and_says_why(self) -> None:
        """The regression for the defect this adapter was written against.

        When Stage 02 exhausts its retries under ``--max-auto-skips 0``, the manager
        routes to the deliverable, finds it is already at the final stage and aborts —
        with ``auto_skipped_stages`` still empty. On the sibling benchmark that same
        shape wrote ``status: "completed"``. Here the run must exit non-zero, the
        metadata must say ``pipeline_completed: false``, and the synthesizer must have
        refused rather than invented an answer out of nothing.
        """
        from unittest.mock import patch

        from src.operator import ClaudeOperator, OperatorResult

        def a_draft_that_never_validates(self, stage, prompt, paths, attempt_no, continue_session=False):
            draft = paths.stage_tmp_file(stage)
            write_text(draft, f"# Stage {stage.number:02d}\n\n## Objective\n\nIncomplete.\n")
            return OperatorResult(
                exit_code=0, stdout="", stderr="", stage_file_path=draft, session_id="test"
            )

        with patch.object(ClaudeOperator, "_run_fake", a_draft_that_never_validates):
            code, meta = self.run_agent("--profile", "ideate", "--max-attempts", "1")

        self.assertEqual(code, 1)
        self.assertFalse(meta["pipeline_completed"])
        self.assertEqual(meta["auto_skipped_stages"], [], "the empty list is the whole point")
        self.assertEqual(meta["stages_approved"], [])
        self.assertEqual(meta["answer_source"], FS_SOURCE_FALLBACK)
        self.assertIn(FS_REFUSAL_NO_APPROVED_STAGE, meta["refusals"])
        self.assertIn("pipeline_completed", meta["exit_clause_failures"])

    def test_print_goal_writes_the_contract_and_runs_nothing(self) -> None:
        import contextlib
        import io

        workspace = self.a_workspace()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = fs_agent.main(
                ["--task", "fs:000", "--workspace", str(workspace), "--profile", "ideate", "--print-goal"]
            )
        printed = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(TASK_BEGIN_MARKER, printed)
        self.assertIn("Where the answer goes", printed)
        self.assertFalse(workspace.exists(), "printing the contract must leave nothing behind")


if __name__ == "__main__":
    unittest.main()
