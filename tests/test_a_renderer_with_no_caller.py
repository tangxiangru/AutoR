"""Two prompt renderers that were tested, documented, and reached no prompt.

``format_protocol_for_prompt`` and ``format_project_context_for_prompt`` each
had unit tests asserting what their output contains, and neither had a
production caller. The consequence was not cosmetic. The experimental protocol
is the run's own answer to "what would count as having shown it" — the primary
metric, the planned seed count, and a tuning budget per baseline — and no stage
prompt carried any of it: Stage 05's template names the file path, and the
templates for 04, 06 and 07 do not mention the protocol at all. A run started
with ``--project-root`` walked every stage over a repository that no prompt
described.

**What made the second one invisible.** ``src.manager`` imported
``format_project_context_for_prompt`` and never called it, so the cheapest
check — grep for the symbol — reported it wired. Nine more prompt renderers
were imported there and uncalled, left behind when ``information_flow`` took
delivery over, so the camouflage was not a one-off.
``test_no_prompt_renderer_is_imported_without_being_called`` is the guard, and
it is an AST check on calls rather than a text search on names, because a text
search is the thing that was fooled.

**What the second block overlaps.** ``project_context`` and ``# Approved Memory``
do carry the same readings, because ``_adopt_project_bootstrap_baseline`` writes
each below-entry assessment into ``memory.md`` as a stage summary. The first
version of this channel narrowed the assessment list to remove that overlap;
``TheOverlapWithApprovedMemoryTest`` measures why that was wrong twice over, and
the list is complete again.

These tests hold the topology, the arrival of the numbers, and the two facts the
overlap argument turns on — not the wording of either block.
"""

from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from pathlib import Path

from src.evolution import EvolutionConfig
from src.information_flow import ALL_STAGES, CHANNELS, ChannelContext, render_inbound
from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.project_bootstrap import (
    CARRIED_FORWARD_MARK,
    STILL_OWED_MARK,
    CodeState,
    ExperimentState,
    ProjectBootstrapResult,
    StageAssessment,
    WritingState,
    format_project_context_for_prompt,
    recommend_entry_stage,
    save_project_bootstrap,
)
from src.stage_graph import REVISIT_EDGES
from src.terminal_ui import TerminalUI
from src.utils import (
    INTAKE_STAGE,
    STAGES,
    append_approved_stage_summary,
    approved_stage_numbers,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    initialize_memory,
    read_text,
    write_text,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

BY_KEY = {channel.key: channel for channel in CHANNELS}
STAGE = {stage.slug: stage for stage in STAGES}
STAGE[INTAKE_STAGE.slug] = INTAKE_STAGE


def _imported_and_called(path: Path) -> tuple[set[str], set[str]]:
    """Prompt-renderer names this module imports, and the names it calls."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if (alias.asname or alias.name.split(".")[0]).endswith("_for_prompt")
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    return imported, called


class ImportIsNotWiringTest(unittest.TestCase):
    def test_no_prompt_renderer_is_imported_without_being_called(self) -> None:
        dead: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            imported, called = _imported_and_called(path)
            for name in sorted(imported - called):
                dead.append(
                    f"{path.relative_to(REPO_ROOT)} imports {name} and never calls it — "
                    "either wire it into a channel or drop the import; an uncalled import "
                    "makes a grep for the symbol answer 'wired'"
                )
        self.assertEqual(dead, [], "\n" + "\n".join(dead))

    def test_the_scan_looks_at_a_population_that_contains_renderers(self) -> None:
        """Control: with no imports found, the check above passes on anything."""
        seen = set()
        for path in sorted(SRC.rglob("*.py")):
            imported, _ = _imported_and_called(path)
            seen |= imported
        self.assertGreaterEqual(len(seen), 5, sorted(seen))

    def test_both_renderers_this_module_is_about_are_reached_from_a_channel(self) -> None:
        """The positive half: the two names now appear in a channel builder."""
        source = (SRC / "information_flow.py").read_text(encoding="utf-8")
        for name in ("format_protocol_for_prompt", "format_project_context_for_prompt"):
            with self.subTest(renderer=name):
                self.assertIn(f"{name}(", source)


def _protocol_payload() -> dict[str, object]:
    return {
        "declared_at": "2026-04-04T10:00:00",
        "primary_metric": "held-out accuracy",
        "planned_seeds": 5,
        "baselines": [
            {
                "name": "long-context prompting",
                "why_competent": "the standard approach and the one the method must beat",
                "tuning_budget": "20 prompt-search configurations, the same as the method",
            }
        ],
    }


class ExperimentalProtocolChannelTest(unittest.TestCase):
    """Where the declared metric, seed count and budgets arrive."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        self.channel = BY_KEY["experimental_protocol"]

    def _write_protocol(self) -> None:
        self.paths.experimental_protocol.parent.mkdir(parents=True, exist_ok=True)
        write_text(self.paths.experimental_protocol, json.dumps(_protocol_payload(), indent=2))

    def _inbound(self, slug: str) -> tuple[str, list[str]]:
        return render_inbound(
            ChannelContext(paths=self.paths, stage=STAGE[slug], attempt_no=1), CHANNELS
        )

    def test_the_protocol_is_produced_by_the_stage_whose_template_asks_for_it(self) -> None:
        self.assertEqual(self.channel.produced_by, "03_study_design")
        template = (SRC / "prompts" / "03_study_design.md").read_text(encoding="utf-8")
        self.assertIn("experimental_protocol.json", template)

    def test_the_only_templates_that_name_the_protocol_are_03_and_05(self) -> None:
        """The rationale argues the four consumers are served nowhere else: Stage
        05's template names the file path and states the obligations, and 04, 06
        and 07 do not mention it. That is the argument for the edge, so it has to
        fail when it stops being true rather than sit in a docstring."""
        named = {
            path.stem
            for path in sorted((SRC / "prompts").glob("*.md"))
            if "experimental_protocol.json" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(
            named,
            {"03_study_design", "05_experimentation"},
            "a template started or stopped naming the protocol — rewrite "
            "experimental_protocol.rationale to match",
        )

    def test_every_stage_the_protocol_binds_is_sent_it(self) -> None:
        for slug in ("04_implementation", "05_experimentation", "06_analysis", "07_writing"):
            with self.subTest(stage=slug):
                self.assertIn(slug, self.channel.consumed_by)

    def test_the_author_is_not_sent_its_own_file_back(self) -> None:
        """Stage 03's own template carries the schema and the rules for writing it,
        so a block echoing the file to its writer restates an instruction rather
        than delivering anything. Contrast ``report_plan``, which does reach its
        producer: a Stage 06 gate refuses a slot whose ``source_artifact`` is
        missing, so a second round's Stage 03 has a repair to make from the block.
        Nothing downstream refuses a protocol for having changed."""
        self.assertNotIn("03_study_design", self.channel.consumed_by)

    def test_the_stages_that_cannot_act_on_it_are_not_sent_it(self) -> None:
        for slug in ("00_intake", "01_literature_survey", "02_hypothesis_generation"):
            with self.subTest(stage=slug):
                self.assertNotIn(slug, self.channel.consumed_by)
        self.assertNotIn(
            "08_dissemination",
            self.channel.consumed_by,
            "Stage 08 packages a comparison it cannot re-run",
        )

    def test_the_declared_numbers_reach_the_stage_that_spends_them(self) -> None:
        """Stage 05 owes each baseline its budget and the metric its result. Before
        this channel, its prompt carried the path to the file and none of its
        contents."""
        self._write_protocol()
        text, delivered = self._inbound("05_experimentation")
        self.assertIn("experimental_protocol", delivered)
        self.assertIn("held-out accuracy", text)
        self.assertIn("20 prompt-search configurations", text)
        self.assertIn("long-context prompting", text)
        self.assertIn("Planned seeds: 5", text)

    def test_the_analysis_stage_is_told_the_metric_it_may_not_replace(self) -> None:
        self._write_protocol()
        text, delivered = self._inbound("06_analysis")
        self.assertIn("experimental_protocol", delivered)
        self.assertIn("held-out accuracy", text)

    def test_a_stage_outside_the_consumer_set_receives_none_of_it(self) -> None:
        self._write_protocol()
        for slug in ("03_study_design", "08_dissemination"):
            text, delivered = self._inbound(slug)
            with self.subTest(stage=slug):
                self.assertNotIn("experimental_protocol", delivered)
                self.assertNotIn("20 prompt-search configurations", text)

    def test_the_block_is_silent_until_the_design_declares_one(self) -> None:
        """An empty heading before Stage 03 has written the file would teach the run
        that the protocol is optional."""
        _, delivered = self._inbound("05_experimentation")
        self.assertNotIn("experimental_protocol", delivered)

    def test_the_preface_separates_building_for_it_from_spending_it(self) -> None:
        """The preface is the only instruction that travels with the block, and it
        is the same text for every consumer. Stage 04's own template requires a
        smoke run, so a block that reached it saying only "run the planned seeds"
        would pull the experiment two stages early."""
        preface = self.channel.preface.lower()
        self.assertIn("stage 04 builds for this protocol", preface)
        self.assertIn("smoke run is not the experiment", preface)

    def test_the_repair_the_preface_names_is_a_real_edge(self) -> None:
        """The preface argues the cost of arriving late by naming the revisit edge
        that pays it. A preface citing an edge the graph does not have is prose."""
        self.assertIn("`05_experimentation → 04_implementation`", self.channel.preface)
        self.assertIn(
            ("05_experimentation", "04_implementation"),
            {(edge.source, edge.target) for edge in REVISIT_EDGES},
        )

    def test_the_preface_does_not_restate_the_body(self) -> None:
        """``format_protocol_for_prompt`` already carries the metric rule and the
        budget rule inside the block. Saying them again in the preface would be
        the same defect as the duplicated hypotheses this module exists to fix."""
        preface = self.channel.preface.lower()
        self.assertNotIn("do not switch to a metric", preface)
        self.assertNotIn("tuning budget declared above", preface)

    def test_the_body_the_preface_defers_to_is_actually_there(self) -> None:
        """Control for the test above: an empty body makes both absences vacuous."""
        self._write_protocol()
        body = self.channel.build(
            ChannelContext(paths=self.paths, stage=STAGE["05_experimentation"], attempt_no=1)
        )
        self.assertIn("do not switch to a metric that came out better", body)
        self.assertIn("tuning budget declared above", body)


def _assessments() -> list[StageAssessment]:
    return [
        StageAssessment(1, "Literature Survey", "complete", "high", ["12 references in refs.bib"]),
        StageAssessment(4, "Implementation", "complete", "high", ["15 code files"]),
        StageAssessment(5, "Experimentation", "partial", "medium", ["1 result file"]),
        StageAssessment(7, "Writing", "not_started", "medium", ["no .tex file"]),
    ]


def _scan_result(entry_stage: int) -> ProjectBootstrapResult:
    return ProjectBootstrapResult(
        project_root="/tmp/my-project",
        scanned_at="2026-04-04T10:00:00",
        total_files=42,
        code_state=CodeState(
            languages=["Python"], frameworks=["pytorch"], entry_points=["train.py"],
            total_code_files=15, status="complete", evidence=["15 code files"],
        ),
        experiment_state=ExperimentState(
            config_files=["configs/exp1.yaml"], result_files=["results/metrics.json"],
            status="partial", evidence=["1 config, 1 result"],
        ),
        writing_state=WritingState(
            tex_files=[], bib_files=["paper/refs.bib"], status="not_started",
            evidence=["no .tex file"],
        ),
        stage_assessments=_assessments(),
        recommended_entry_stage=entry_stage,
        file_tree_sample=["train.py", "model.py"],
    )


class ProjectContextChannelTest(unittest.TestCase):
    """A repository the run did not create, described to the stages working in it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        self.channel = BY_KEY["project_context"]

    def _inbound(self, slug: str) -> tuple[str, list[str]]:
        return render_inbound(
            ChannelContext(paths=self.paths, stage=STAGE[slug], attempt_no=1), CHANNELS
        )

    def test_the_channel_is_silent_on_a_run_with_no_project_root(self) -> None:
        """Most runs start from nothing. The block must not appear as an empty
        heading on every one of them."""
        for slug in ("01_literature_survey", "07_writing"):
            text, delivered = self._inbound(slug)
            with self.subTest(stage=slug):
                self.assertNotIn("project_context", delivered)
                self.assertNotIn("Existing Project Repository", text)

    def test_every_stage_the_run_can_be_dropped_into_is_a_consumer(self) -> None:
        """The constraint that rules out a fixed early set. ``recommend_entry_stage``
        picks where the walk starts, and its answer is not bounded above by the
        early stages: a repository with everything through Stage 07 already done
        re-enters at 08, and that run has seen less of the repository than any
        other, not more."""
        for stage in STAGES:
            with self.subTest(stage=stage.slug):
                self.assertIn(stage.slug, self.channel.consumed_by)

    def test_the_entry_stage_is_not_bounded_by_the_early_stages(self) -> None:
        """The control for the test above: without this, "all eight" is an
        unargued width rather than the answer to a live range."""
        complete_through = lambda last: [  # noqa: E731
            StageAssessment(n, f"Stage {n}", "complete" if n <= last else "not_started",
                            "medium", [])
            for n in range(1, 9)
        ]
        self.assertEqual(recommend_entry_stage(complete_through(7)), 8)
        self.assertEqual(recommend_entry_stage(complete_through(6)), 7)
        self.assertEqual(recommend_entry_stage(complete_through(5)), 6)

    def test_intake_is_the_only_stage_left_out(self) -> None:
        self.assertNotIn(INTAKE_STAGE.slug, self.channel.consumed_by)
        self.assertEqual(
            len(self.channel.consumed_by), len(ALL_STAGES) - 1, sorted(self.channel.consumed_by)
        )

    def test_intake_is_left_out_because_it_finishes_before_the_scan_starts(self) -> None:
        """The one exclusion has to be a fact about the code, not a preference.
        ``run()`` calls the scan after intake has been approved, so the block
        would be empty at Stage 00 on every run that has one."""
        import inspect

        source = inspect.getsource(ResearchManager.run)
        self.assertLess(
            source.index("self._run_intake("),
            source.index("self._run_project_bootstrap("),
            "the scan now runs before intake; 00_intake can read it and the "
            "exclusion in project_context.rationale is no longer true",
        )

    def test_the_scan_reaches_the_stage_the_run_re_enters_at(self) -> None:
        save_project_bootstrap(self.paths, _scan_result(entry_stage=7))
        text, delivered = self._inbound("07_writing")
        self.assertIn("project_context", delivered)
        self.assertIn("Existing Project Repository", text)
        self.assertIn("Project Bootstrap Summary", text)


class TheOverlapWithApprovedMemoryTest(unittest.TestCase):
    """What this block and ``# Approved Memory`` each hold, measured.

    An earlier version of this channel dropped every assessment below the
    recommended entry stage, arguing that ``_adopt_project_bootstrap_baseline``
    had already written those readings into ``memory.md`` so the block would
    otherwise send them twice. The tests below are the two measurements that
    retired that argument, and they are here so it cannot come back by assertion:
    the summary section above the list already re-sends every assessment with its
    evidence, and memory's copy is destroyed by the first approval at a stage
    below the re-entry point. The overlap is real, it is not the list's fault,
    and the list is the only place the carried/owed split is written down.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_dir = Path(self._tmp.name) / "runs"
        self.runs_dir.mkdir()
        self.paths = build_run_paths(self.runs_dir / "run_0001")
        ensure_run_layout(self.paths)
        ensure_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "project context")
        write_text(self.paths.user_input, "project context")
        ui = TerminalUI()
        self.manager = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=self.runs_dir,
            operator=ClaudeOperator(model="sonnet", fake_mode=True, ui=ui),
            ui=ui,
            output_stream=io.StringIO(),
            evolution=EvolutionConfig(rounds=0),
        )

    def _adopt(self, entry_stage: int) -> None:
        save_project_bootstrap(self.paths, _scan_result(entry_stage))
        self.manager._adopt_project_bootstrap_baseline(  # noqa: SLF001
            self.paths, _assessments(), entry_stage
        )

    def _assessment_list(self) -> str:
        block = format_project_context_for_prompt(self.paths) or ""
        self.assertIn("## Project Stage Assessments", block)
        return block.split("## Project Stage Assessments", 1)[1]

    def test_the_summary_section_already_re_sends_every_carried_forward_reading(self) -> None:
        """Measurement one: narrowing the list narrows the wrong copy.

        ``save_project_bootstrap`` writes ``result.summary or
        _generate_summary_text(result)`` and nothing in the tree assigns
        ``ProjectBootstrapResult.summary``, so ``bootstrap_summary.md`` is always
        the generated text — which lists every stage's status, confidence *and*
        evidence. Whatever the list below it does, the block re-sends the
        below-entry readings in full, with the same evidence strings memory got.
        """
        self._adopt(entry_stage=5)
        block = format_project_context_for_prompt(self.paths) or ""
        summary_section = block.split("## Project Stage Assessments", 1)[0]
        memory = read_text(self.paths.memory)
        for evidence in ("12 references in refs.bib", "15 code files"):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, summary_section)
                self.assertIn(evidence, memory)

    def test_nothing_sets_the_summary_field_the_generated_text_falls_back_from(self) -> None:
        """Control for the test above: if some caller wrote an agent-authored
        summary, ``bootstrap_summary.md`` need not list the assessments and the
        overlap would be conditional rather than certain."""
        constructed = 0
        assigns: list[str] = []
        for path in sorted(SRC.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                where = f"{path.relative_to(REPO_ROOT)}:{getattr(node, 'lineno', 0)}"
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "ProjectBootstrapResult"
                ):
                    constructed += 1
                    if any(kw.arg == "summary" for kw in node.keywords):
                        assigns.append(f"{where} passes summary=")
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and t.attr == "summary"
                    for t in node.targets
                ):
                    assigns.append(f"{where} assigns .summary")
        self.assertGreater(constructed, 0, "the scan found no construction site at all")
        self.assertEqual(assigns, [], "\n".join(assigns))

    def test_an_approval_below_the_entry_stage_erases_memorys_copy(self) -> None:
        """Measurement two: memory's copy is not durable.

        ``07_writing → 01_literature_survey`` is a ``guard="always"`` revisit
        edge, and ``recommend_entry_stage`` can put the walk at Stage 07. Once
        that Stage 01 is approved, ``append_approved_stage_summary`` keeps only
        the entries numbered below 1 — so Stages 02-06 leave memory and the scan's
        reading of them exists nowhere but in this block.
        """
        self.assertIn(
            ("07_writing", "01_literature_survey"),
            {(edge.source, edge.target) for edge in REVISIT_EDGES},
        )
        self._adopt(entry_stage=7)
        self.assertEqual(
            approved_stage_numbers(read_text(self.paths.memory)), {1, 2, 3, 4, 5, 6}
        )

        append_approved_stage_summary(
            self.paths.memory, STAGE["01_literature_survey"], "# Stage 01: redone\n"
        )
        memory = read_text(self.paths.memory)
        self.assertEqual(approved_stage_numbers(memory), {1})
        self.assertNotIn("15 code files", memory)
        self.assertIn("15 code files", format_project_context_for_prompt(self.paths) or "")

    def test_every_assessment_is_listed_whatever_the_entry_stage(self) -> None:
        """The consequence of both measurements: no assessment is withheld."""
        self._adopt(entry_stage=5)
        listed = self._assessment_list()
        for number in ("Stage 01", "Stage 04", "Stage 05", "Stage 07"):
            with self.subTest(stage=number):
                self.assertIn(number, listed)

    def test_each_line_says_whether_this_run_accepted_that_stage_or_owes_it(self) -> None:
        """What the list adds over the summary above it. The status is duplicated
        on purpose; the carried/owed split is written down here and nowhere else —
        ``bootstrap_summary.md`` predates the entry-stage decision, and memory
        holds it only as one carry-forward sentence per stage."""
        self._adopt(entry_stage=5)
        listed = self._assessment_list()
        by_stage = {
            line.split("(", 1)[0].strip(" -*"): line
            for line in listed.splitlines()
            if line.startswith("- **Stage")
        }
        self.assertEqual(sorted(by_stage), ["Stage 01", "Stage 04", "Stage 05", "Stage 07"])
        self.assertIn(CARRIED_FORWARD_MARK, by_stage["Stage 01"])
        self.assertIn(CARRIED_FORWARD_MARK, by_stage["Stage 04"])
        self.assertIn(STILL_OWED_MARK, by_stage["Stage 05"])
        self.assertIn(STILL_OWED_MARK, by_stage["Stage 07"])

    def test_with_no_entry_stage_recorded_every_stage_is_owed(self) -> None:
        """``load_recommended_entry_stage`` returns ``None`` when the scan metadata
        is missing or unparseable. Nothing was carried forward in that case, so
        marking a stage accepted would tell the run it may skip work it owes."""
        save_project_bootstrap(self.paths, _scan_result(entry_stage=5))
        (self.paths.bootstrap_dir / "scan_metadata.json").unlink()
        listed = self._assessment_list()
        self.assertNotIn(CARRIED_FORWARD_MARK, listed)
        self.assertEqual(listed.count(STILL_OWED_MARK), len(_assessments()))

    def test_the_prompt_the_stage_actually_receives_carries_both_halves(self) -> None:
        """End to end through ``_build_stage_prompt``: the marked list in the
        channel block, the carry-forward sentence in ``# Approved Memory``."""
        self._adopt(entry_stage=5)
        prompt = self.manager._build_stage_prompt(  # noqa: SLF001
            self.paths, STAGE["05_experimentation"], None, False
        )
        self.assertIn("# Existing Project Repository (from the project bootstrap)", prompt)
        self.assertIn("Bootstrap carry-forward status:", prompt)
        block = prompt.split("Existing Project Repository", 1)[1]
        self.assertIn("Stage 05 (Experimentation)", block)
        self.assertIn(CARRIED_FORWARD_MARK, block)

    def test_the_preface_does_not_deny_the_overlap_it_creates(self) -> None:
        """The rationale and preface are the part of this that a reviewer reads.
        Both were wrong before, and a sentence saying the carried-forward stages
        are *only* in memory is the specific claim the two measurements refuted."""
        channel = BY_KEY["project_context"]
        self.assertIn("only copy left", channel.preface)
        self.assertIn("append_approved_stage_summary", channel.rationale)
        self.assertNotIn("the ones the run still owes", channel.preface)


if __name__ == "__main__":
    unittest.main()
