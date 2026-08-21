"""The skill pack has to be well-formed, and it has to land where the CLI looks.

Both halves fail silently in production. A skill with broken frontmatter is
simply not listed by the agent CLI, and a skill installed to the wrong
directory is not either — in both cases the stage runs without guidance nobody
notices is missing. Before this test existed, the repository shipped 1029 lines
of writing, citation and venue reference material as loose ``.md`` files under
``.claude/skills/guides/``, which is neither a valid skill layout nor on the
path the operator's CLI searches. It was referenced by no code and had never
been loaded.
"""

from __future__ import annotations

import io
import re
import json
import tempfile
import unittest
from pathlib import Path

from src.run_skills import (
    discipline_of,
    DEFAULT_PINS_FILENAME,
    KNOWN_BENCHMARKS,
    MAX_PINS_PER_TASK,
    format_skills_for_prompt,
    load_task_pins,
    pinned_skills_note,
    pins_for,
    select_run_skills,
    validate_task_pins,
    install_run_skills,
    read_skill_pack,
    validate_skill_pack,
)
from src.utils import (
    TASK_BEGIN_MARKER,
    TASK_END_MARKER,
    build_run_paths,
    ensure_run_layout,
    write_text,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PACK = REPO_ROOT / "src" / "skills"


class SkillPackShapeTest(unittest.TestCase):
    def test_the_shipped_pack_is_valid(self) -> None:
        self.assertEqual(validate_skill_pack(SKILL_PACK), [])

    def test_the_pack_is_not_empty(self) -> None:
        self.assertGreater(len(read_skill_pack(SKILL_PACK)), 0)

    def test_every_skill_directory_is_picked_up(self) -> None:
        """A directory that exists but is not readable as a skill is the silent case."""
        on_disk = {
            child.name
            for child in SKILL_PACK.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        }
        parsed = {entry.name for entry in read_skill_pack(SKILL_PACK)}
        self.assertEqual(on_disk, parsed)

    def test_descriptions_name_the_situation_that_triggers_the_skill(self) -> None:
        """The description is the only routing signal the model gets.

        It has to describe *when* to reach for the skill, not what the skill is
        about. "Writing guidance" is a topic; "use when the draft reads
        generic" is a trigger.
        """
        for entry in read_skill_pack(SKILL_PACK):
            with self.subTest(skill=entry.name):
                lowered = entry.description.lower()
                self.assertTrue(lowered.startswith("use "), entry.description)
                self.assertIn("when", lowered)

    def test_no_skill_refers_to_another_project_workflow(self) -> None:
        """The pack was ported from a different project; its vocabulary was too.

        A skill that tells the operator to run ``paper-plan`` names a stage
        AutoR does not have.
        """
        foreign = ("paper-plan", "paper-write", "insleep", "Orchestra")
        for path in SKILL_PACK.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for token in foreign:
                with self.subTest(file=path.name, token=token):
                    self.assertNotIn(token, text)


class SkillInstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def test_skills_install_where_the_agent_cli_looks(self) -> None:
        """``.claude/skills`` under the run root, because that is the operator's cwd."""
        installed = install_run_skills(self.paths, SKILL_PACK)

        self.assertEqual(
            self.paths.skills_dir,
            self.paths.run_root / ".claude" / "skills",
        )
        # Everything the router offers a run with no field and no brief, which is the
        # unconditional half of the pack. Not "every skill in the pack": a task-scoped
        # skill is deliberately absent here, and comparing against the whole pack would
        # make this test fail every time one is added rather than when an install breaks.
        self.assertEqual(
            sorted(installed),
            sorted(entry.name for entry in select_run_skills(read_skill_pack(SKILL_PACK))),
        )
        self.assertTrue(installed, "the unconditional pack is empty")
        for name in installed:
            with self.subTest(skill=name):
                self.assertTrue((self.paths.skills_dir / name / "SKILL.md").is_file())

    def test_reference_files_come_along(self) -> None:
        install_run_skills(self.paths, SKILL_PACK)
        self.assertTrue((self.paths.skills_dir / "paper-writing" / "reference.md").is_file())

    def test_installing_twice_replaces_rather_than_accumulates(self) -> None:
        install_run_skills(self.paths, SKILL_PACK)
        stray = self.paths.skills_dir / "paper-writing" / "stale.md"
        stray.write_text("left over from an older version", encoding="utf-8")

        install_run_skills(self.paths, SKILL_PACK)

        self.assertFalse(stray.exists())
        self.assertTrue((self.paths.skills_dir / "paper-writing" / "SKILL.md").is_file())

    def test_a_missing_pack_installs_nothing_rather_than_raising(self) -> None:
        self.assertEqual(install_run_skills(self.paths, REPO_ROOT / "no-such-dir"), [])


class SkillPackValidationTest(unittest.TestCase):
    """The validator is the gate, so it has to actually reject things."""

    def _pack(self, name: str, body: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / name).mkdir(parents=True)
        (root / name / "SKILL.md").write_text(body, encoding="utf-8")
        return root

    def test_a_name_that_does_not_match_its_directory_is_rejected(self) -> None:
        pack = self._pack(
            "venue-checklist",
            "---\nname: venue-checklists\ndescription: "
            "Use when checking a paper against venue submission requirements.\n---\n\nbody\n",
        )
        problems = validate_skill_pack(pack)
        self.assertTrue(any("does not match its directory" in problem for problem in problems), problems)

    def test_a_missing_frontmatter_block_is_rejected(self) -> None:
        problems = validate_skill_pack(self._pack("thing", "# Thing\n\nno frontmatter\n"))
        self.assertTrue(any("frontmatter" in problem for problem in problems), problems)

    def test_a_description_too_short_to_route_on_is_rejected(self) -> None:
        problems = validate_skill_pack(
            self._pack("thing", "---\nname: thing\ndescription: Writing help.\n---\n\nbody\n")
        )
        self.assertTrue(any("too short to route on" in problem for problem in problems), problems)

    def test_a_directory_without_a_skill_file_is_rejected(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "empty-skill").mkdir()
        problems = validate_skill_pack(Path(tmp.name))
        self.assertTrue(any("has no SKILL.md" in problem for problem in problems), problems)

    def test_a_valid_skill_produces_no_problems(self) -> None:
        pack = self._pack(
            "thing",
            "---\nname: thing\ndescription: "
            "Use when a specific and clearly described situation comes up during a stage.\n---\n\nbody\n",
        )
        self.assertEqual(validate_skill_pack(pack), [])


if __name__ == "__main__":
    unittest.main()


class DisciplineRoutingTest(unittest.TestCase):
    """Twenty field-specific skills in one run is nineteen descriptions about other fields.

    A skill reaches the operator through its `description`, and the model chooses from what
    is installed. The pack is meant to grow one field at a time, so without routing it gets
    less useful as it gets bigger -- the wrong direction for a pack designed to grow.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        self.pack = Path(__file__).resolve().parent.parent / "src" / "skills"

    def test_a_field_run_gets_the_general_pack_plus_its_own_field(self) -> None:
        installed = install_run_skills(self.paths, self.pack, discipline="earth")
        fields = {discipline_of(name) for name in installed} - {""}
        self.assertEqual(fields, {"earth"})
        self.assertTrue(any(not discipline_of(name) for name in installed))

    def test_an_unknown_field_still_gets_the_general_pack(self) -> None:
        installed = install_run_skills(self.paths, self.pack, discipline="palaeography")
        self.assertTrue(installed)
        self.assertEqual({discipline_of(name) for name in installed} - {""}, set())

    def test_no_field_installs_everything(self) -> None:
        """An ordinary run does not know its field, and must not lose the pack over it."""
        everything = install_run_skills(self.paths, self.pack)
        narrowed = install_run_skills(self.paths, self.pack, discipline="earth")
        self.assertGreater(len(everything), len(narrowed))

    def test_routing_never_drops_a_general_skill(self) -> None:
        general = {n for n in install_run_skills(self.paths, self.pack) if not discipline_of(n)}
        for field in ("earth", "life", "physics"):
            got = set(install_run_skills(self.paths, self.pack, discipline=field))
            self.assertTrue(general <= got, field)

    def test_the_installed_directory_matches_what_was_returned(self) -> None:
        """A stale skill from a previous install must not linger and mislead the router.

        This is the resume case and it is the one that matters: the first install writes
        every field's skills, a later one narrows to eleven, and without a sweep the run
        still offers the model all twenty-nine. The narrowing would be a no-op exactly where
        it was needed.
        """
        install_run_skills(self.paths, self.pack)
        installed = install_run_skills(self.paths, self.pack, discipline="earth")
        on_disk = {p.name for p in self.paths.skills_dir.iterdir() if p.is_dir()}
        self.assertEqual(on_disk, set(installed))

    def test_the_sweep_leaves_skills_the_pack_does_not_own(self) -> None:
        """The learned-notes layer writes into the same directory and is not ours to delete."""
        install_run_skills(self.paths, self.pack, discipline="earth")
        foreign = self.paths.skills_dir / "learned-from-earlier-runs"
        foreign.mkdir(parents=True, exist_ok=True)
        (foreign / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\n", encoding="utf-8")
        install_run_skills(self.paths, self.pack, discipline="life")
        self.assertTrue(foreign.is_dir())


class TaskShapedRoutingTest(unittest.TestCase):
    """A skill written for one shape of task is offered only to tasks of that shape.

    The field filter above narrows twenty field skills to two. It cannot go further:
    four ResearchClawBench tasks share a field, so every run in a field is offered an
    identical pack and the model picks from an undifferentiated listing of thirty
    entries — sixteen from AutoR plus the fourteen Claude Code ships. Measured over a
    40-task arm it picked 1.75 per run in 19.7 hours each.

    `applies_when` is the second filter, and it is the one that makes two runs in the
    same field differ. The predicate reads the research *brief*, never the task's
    identifier: a table of benchmark ids would select the same tasks today and
    generalise to nothing, while a claim about what a task asks for can be wrong in
    public. `tools/skill_selectivity.py` is where it is checked against a corpus.
    """

    BRIEF_WITH = "Scientific Objective: quantify per-feature attribution over the cohort."
    BRIEF_WITHOUT = "Scientific Objective: forecast the daily series and report RMSE."

    def _pack(self, *skills: tuple[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, frontmatter in skills:
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\n{frontmatter}\n---\n\nbody\n", encoding="utf-8"
            )
        return root

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        self.pack = self._pack(
            (
                "scoped",
                "description: Use when the brief names an attribution deliverable.\n"
                "applies_when: attribution|salien\n"
                "stages: 03_study_design, 06_analysis",
            ),
            ("always", "description: Use when writing anything at all, at every stage."),
        )

    def test_a_scoped_skill_is_installed_only_for_a_matching_brief(self) -> None:
        write_text(self.paths.user_input, self.BRIEF_WITH)
        self.assertEqual(sorted(install_run_skills(self.paths, self.pack)), ["always", "scoped"])
        write_text(self.paths.user_input, self.BRIEF_WITHOUT)
        self.assertEqual(install_run_skills(self.paths, self.pack), ["always"])

    def test_a_brief_that_stops_matching_removes_the_skill_from_disk(self) -> None:
        """The resume case. A pack narrowing that only ever adds is not a narrowing."""
        write_text(self.paths.user_input, self.BRIEF_WITH)
        install_run_skills(self.paths, self.pack)
        self.assertTrue((self.paths.skills_dir / "scoped").is_dir())
        write_text(self.paths.user_input, self.BRIEF_WITHOUT)
        install_run_skills(self.paths, self.pack)
        self.assertFalse((self.paths.skills_dir / "scoped").exists())

    def test_a_missing_brief_installs_only_the_unconditional_skills(self) -> None:
        """Fail closed, not open.

        A task-scoped skill is by construction wrong for most runs, so admitting one on
        missing information adds a description that competes with the rest and describes
        a situation this run is probably not in.
        """
        self.assertEqual(install_run_skills(self.paths, self.pack), ["always"])

    def test_applies_unless_vetoes_a_match(self) -> None:
        pack = self._pack(
            (
                "scoped",
                "description: Use when the brief names an attribution deliverable.\n"
                "applies_when: attribution\napplies_unless: cohort\n"
                "stages: 06_analysis",
            ),
        )
        write_text(self.paths.user_input, self.BRIEF_WITH)  # says both
        self.assertEqual(install_run_skills(self.paths, pack), [])
        write_text(self.paths.user_input, "We need an attribution map per atom.")
        self.assertEqual(install_run_skills(self.paths, pack), ["scoped"])

    def test_the_predicate_reads_the_brief_and_not_the_wrapper(self) -> None:
        """The benchmark contract is identical in every run; matching it matches everywhere.

        `user_input.txt` carries AutoR's own preamble and the benchmark's workspace
        contract around the task. A predicate matched against the whole file would fire
        on "figures are mandatory" in all forty runs. `task_brief` narrows to the brief
        for the same reason `research_brief` narrows the demand extractor.
        """
        wrapped = (
            "# Benchmark Run\n\nFigures are mandatory; write report/report.md.\n\n"
            f"{TASK_BEGIN_MARKER}\n## Task Description\n{self.BRIEF_WITHOUT}\n"
            f"{TASK_END_MARKER}\n\n### Deliverables\nSaliency is not required here.\n"
        )
        write_text(self.paths.user_input, wrapped)
        self.assertEqual(install_run_skills(self.paths, self.pack), ["always"])

    def test_a_scoped_skill_survives_the_field_filter_independently(self) -> None:
        pack = self._pack(
            (
                "earth-scoped",
                "description: Use when the brief names an attribution deliverable in earth science.\n"
                "applies_when: attribution\nstages: 06_analysis",
            ),
        )
        write_text(self.paths.user_input, self.BRIEF_WITH)
        self.assertEqual(install_run_skills(self.paths, pack, discipline="earth"), ["earth-scoped"])
        self.assertEqual(install_run_skills(self.paths, pack, discipline="life"), [])

    def test_a_malformed_predicate_removes_the_skill_rather_than_raising(self) -> None:
        pack = self._pack(
            ("broken", "description: Use when something happens, at some stage.\n"
                       "applies_when: (unclosed\nstages: 06_analysis"),
        )
        write_text(self.paths.user_input, self.BRIEF_WITH)
        self.assertEqual(install_run_skills(self.paths, pack), [])
        self.assertTrue(any("not a valid regex" in p for p in validate_skill_pack(pack)))

    def test_a_task_scoped_skill_that_no_stage_announces_is_refused(self) -> None:
        """Selected and never mentioned is worse than unconditional.

        It is offered to a minority of runs and told to none of them, and it costs a
        predicate nobody reads. Over the measured arm the declarative form of naming a
        skill produced zero launches in forty runs; the imperative form produced 31.
        """
        pack = self._pack(
            ("orphan", "description: Use when the brief names an attribution deliverable.\n"
                       "applies_when: attribution"),
        )
        self.assertTrue(any("names no stages" in p for p in validate_skill_pack(pack)))

    def test_a_stage_that_does_not_exist_is_refused(self) -> None:
        pack = self._pack(
            ("wrong", "description: Use when the brief names an attribution deliverable.\n"
                      "applies_when: attribution\nstages: 09_publication"),
        )
        self.assertTrue(any("not a stage" in p for p in validate_skill_pack(pack)))


class SkillsNamedInThePromptTest(unittest.TestCase):
    """What `format_skills_for_prompt` renders, and what it deliberately does not."""

    def _entries(self) -> list:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, extra in (
            ("scoped-design", "applies_when: attribution\nstages: 03_study_design"),
            ("scoped-analysis", "applies_when: attribution\nstages: 06_analysis"),
            ("always", ""),
        ):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when the situation arises, at a stage.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        return read_skill_pack(root)

    def test_only_the_scoped_skills_that_name_this_stage_are_rendered(self) -> None:
        entries = self._entries()
        block = format_skills_for_prompt(entries, "03_study_design")
        self.assertIn("scoped-design", block)
        self.assertNotIn("scoped-analysis", block)

    def test_the_unconditional_pack_is_never_rendered(self) -> None:
        """The whole point of the pull mechanism is not paying for it in every prompt.

        This renderer sat unwired for several releases under exactly that objection, and
        the objection was right about a roster of the whole pack. What is different about
        a task-scoped skill is that a predicate chose it for *this* brief, and nothing
        else in the prompt says so.
        """
        entries = self._entries()
        for slug in ("03_study_design", "06_analysis", "07_writing"):
            self.assertNotIn("always", format_skills_for_prompt(entries, slug))

    def test_a_table_over_the_cap_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            names = []
            for index in range(MAX_PINS_PER_TASK + 1):
                name = f"skill-{index:02d}"
                names.append(name)
                (pack / name).mkdir(parents=True)
                (pack / name / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Use when.\nstages: 03_study_design\n---\n\nb\n",
                    encoding="utf-8",
                )
            problems = validate_task_pins({"Physics_000": names}, pack)
            self.assertTrue(any("over the maximum" in p for p in problems))
            self.assertEqual(validate_task_pins({"Physics_000": names[:-1]}, pack), [])

    def test_a_big_table_of_stageless_pins_is_refused(self) -> None:
        """The cap was raised on the assumption that pins are routed. A stageless pin is
        announced in every prompt, so a table of them spends the budget the routing was
        supposed to save -- silently, because the run still works."""
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            names = []
            for index in range(4):
                name = f"loose-{index}"
                names.append(name)
                (pack / name).mkdir(parents=True)
                (pack / name / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Use when.\n---\n\nb\n", encoding="utf-8"
                )
            problems = validate_task_pins({"Physics_000": names}, pack)
            self.assertTrue(any("name no stage" in p for p in problems))
            # Three is still allowed without stages: that was the whole table before.
            self.assertEqual(validate_task_pins({"Physics_000": names[:3]}, pack), [])

    def test_the_constant_and_the_tables_own_prose_agree(self) -> None:
        """`_maximum` is the argument for the number and the constant is the number. A
        change to either alone leaves a table whose stated reasoning is for a different
        cap than the one enforced, and the prose is the half a reader believes."""
        import re

        table = json.loads(
            (REPO_ROOT / "configs" / DEFAULT_PINS_FILENAME).read_text(encoding="utf-8")
        )
        words = {
            "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "eighteen": 18, "twenty": 20,
        }
        head = table["_maximum"].split(" per task", 1)[0].strip().lower()
        self.assertIn(head, words, f"`_maximum` opens with {head!r}, which is not a count")
        self.assertEqual(words[head], MAX_PINS_PER_TASK)

    def test_the_shipped_table_passes_its_own_rules(self) -> None:
        self.assertEqual(
            validate_task_pins(
                load_task_pins(REPO_ROOT / "configs" / DEFAULT_PINS_FILENAME),
                REPO_ROOT / "src" / "skills",
            ),
            [],
        )

    def _scoped_pack(self, tmp: str):
        root = Path(tmp)
        for name, extra in (
            ("rcb-only", "benchmarks: researchclawbench"),
            ("two-benchmarks", "benchmarks: researchclawbench, firebench"),
            ("unscoped", ""),
        ):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when the situation arises, at a stage.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        return read_skill_pack(root)

    def test_a_scoped_skill_reaches_only_its_own_benchmark(self) -> None:
        """Measured: a FIRE-Bench run was installing 117 skills, 116 of them written from
        ResearchClawBench's per-criterion losses, and the paired difference against a pack
        with them removed was -2.6 F1 over 33 tasks -- nothing, from a listing seven times
        larger. On the benchmark they came from the same skills carry +8.63."""
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._scoped_pack(tmp)
            got = {e.name for e in select_run_skills(pack, benchmark="researchclawbench")}
            self.assertEqual(got, {"rcb-only", "two-benchmarks", "unscoped"})
            got = {e.name for e in select_run_skills(pack, benchmark="firebench")}
            self.assertEqual(got, {"two-benchmarks", "unscoped"})

    def test_a_run_with_no_benchmark_is_offered_no_scoped_skill(self) -> None:
        """The safe direction, and the same one an empty brief takes: a skill that names
        its benchmark is by construction wrong for most runs."""
        with tempfile.TemporaryDirectory() as tmp:
            got = {e.name for e in select_run_skills(self._scoped_pack(tmp), benchmark=None)}
            self.assertEqual(got, {"unscoped"})

    def test_the_benchmark_name_is_matched_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._scoped_pack(tmp)
            got = {e.name for e in select_run_skills(pack, benchmark="ResearchClawBench")}
            self.assertIn("rcb-only", got)

    def test_a_pin_cannot_carry_a_skill_into_another_benchmark(self) -> None:
        """A pin is keyed on a task id, and a task id belongs to one benchmark. Ordering the
        scope after the pin check would let a ResearchClawBench table reach a FIRE-Bench run
        the moment two benchmarks named a task the same way."""
        with tempfile.TemporaryDirectory() as tmp:
            pack = self._scoped_pack(tmp)
            got = {e.name for e in select_run_skills(
                pack, benchmark="firebench", pinned=frozenset({"rcb-only"}))}
            self.assertNotIn("rcb-only", got)

    def test_an_unknown_benchmark_name_is_refused_by_the_validator(self) -> None:
        """A typo removes the skill from every run and nothing says so."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "typo"
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text(
                "---\nname: typo\ndescription: Use when the situation arises, at a stage.\n"
                "benchmarks: research-claw-bench\n---\n\nbody\n", encoding="utf-8")
            problems = validate_skill_pack(Path(tmp))
            self.assertTrue(any("research-claw-bench" in p for p in problems), problems)

    def test_every_shipped_scope_names_a_benchmark_a_front_end_sets(self) -> None:
        for entry in read_skill_pack(SKILL_PACK):
            with self.subTest(skill=entry.name):
                self.assertLessEqual(entry.benchmarks, KNOWN_BENCHMARKS)

    def test_a_pin_is_announced_at_the_stage_it_names(self) -> None:
        """Unconditional announcement was affordable at a cap of three pins per task and
        is not at fifteen: a description competes against every other description in the
        prompt, so fifteen pins announced seven times over is the listing problem the cap
        existed to avoid, reintroduced by the mechanism meant to solve it."""
        entries = self._entries()
        pinned = frozenset({"scoped-design", "scoped-analysis"})
        design = format_skills_for_prompt(entries, "03_study_design", pinned)
        self.assertIn("scoped-design", design)
        self.assertNotIn("scoped-analysis", design)
        analysis = format_skills_for_prompt(entries, "06_analysis", pinned)
        self.assertIn("scoped-analysis", analysis)
        self.assertNotIn("scoped-design", analysis)

    def test_a_pin_that_names_no_stage_is_announced_everywhere(self) -> None:
        """The fallback has to hold, or routing turns a pin the table asserts into a pin
        nobody is ever told about -- a silent regression of the strongest signal here."""
        entries = self._entries()
        pinned = frozenset({"always"})
        for slug in ("01_literature_survey", "03_study_design", "07_writing"):
            self.assertIn("always", format_skills_for_prompt(entries, slug, pinned))

    def test_a_pin_still_outranks_a_shape_match_at_the_same_stage(self) -> None:
        """Routing changes where a pin appears, not what it is worth: a pin is a record
        of what this task lost, and a shape match is an inference about tasks like it."""
        entries = self._entries()
        block = format_skills_for_prompt(entries, "03_study_design", frozenset({"scoped-design"}))
        self.assertIn("pinned to this task by name", block)
        self.assertLess(
            block.index("pinned to this task by name"), block.index("scoped-design")
        )

    def test_a_stage_with_no_selected_skill_gets_no_block(self) -> None:
        self.assertEqual(format_skills_for_prompt(self._entries(), "01_literature_survey"), "")

    def test_the_block_tells_the_operator_to_read_them(self) -> None:
        """Imperative, because that is the form measured to work.

        Over the 40-task arm the one skill a rendered prompt told the operator to *read*
        fired in 31 of 40 runs; the three a prompt said were "installed for this stage"
        fired in none.
        """
        block = format_skills_for_prompt(self._entries(), "03_study_design")
        self.assertIn("Read each one", block)


class DescriptionsDiscriminateTest(unittest.TestCase):
    """Two skills a run is offered together must not open the same way.

    The description is the only thing the model sees when choosing. All twenty field
    descriptions used to open with one formula — "Use when the research task is in
    <field> — <gloss> — at study design, analysis or writing." — which is 63% of the
    average field description and which the installer already guarantees, because it
    only copies that field's two skills into the run. So within a run the pair was
    distinguished by a trailing clause of 56 to 134 characters, and six of the twenty
    tails spent their first word re-naming the field a second time.

    What that produced was all-or-nothing rather than choose-one: across the measured
    arm, of the forty runs' eighty field-skill install opportunities, the runs that
    opened a field skill mostly opened both of their pair in adjacent turns, and
    fourteen of the twenty never launched at all.
    """

    def setUp(self) -> None:
        self.entries = read_skill_pack(SKILL_PACK)
        self.assertTrue(self.entries)

    def _trigger(self, description: str) -> str:
        """The first sentence — what a model reads before deciding to read on."""
        return re.split(r"(?<=[.!?])\s", description.strip())[0].casefold()

    def test_no_two_skills_share_a_trigger_sentence(self) -> None:
        seen: dict[str, str] = {}
        clashes: list[str] = []
        for entry in self.entries:
            trigger = self._trigger(entry.description)
            if trigger in seen:
                clashes.append(f"{seen[trigger]} and {entry.name}")
            seen[trigger] = entry.name
        self.assertEqual(clashes, [], f"skills opening identically: {clashes}")

    def test_a_field_skill_does_not_spend_its_trigger_on_the_field(self) -> None:
        """`install_run_skills` already guarantees the field; saying it carries no bit.

        The field is in the directory name, in the skill name the model sees in its
        listing, and in the install decision. A description that leads with it is
        spending the only routing signal there is on something already known.
        """
        for entry in self.entries:
            field = discipline_of(entry.name)
            if not field:
                continue
            with self.subTest(skill=entry.name):
                self.assertNotIn(
                    f"the research task is in {field}",
                    entry.description.casefold(),
                    "the description opens with the clause the installer enforces",
                )


class TaskPinTest(unittest.TestCase):
    """Skills forced into a run by its identifier, over both routing filters.

    The field prefix and the `applies_when` predicate are inferences: guesses about
    what a task needs, made from the task alone. A pin is not a guess — it is a
    record that this identifier already ran, already scored, and lost criteria whose
    subject is these skills. So it wins over both filters, and so it has to announce
    itself: a pinned arm and an unpinned arm are two configurations, and the run
    config and the log both say which one produced a given score.
    """

    def _pack(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, extra in (
            ("physics-two-things", ""),
            ("scoped-thing", "applies_when: widget\nstages: 06_analysis"),
            ("always-thing", ""),
        ):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a situation arises, at some stage.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        return root

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Scientific Objective: forecast the series.")
        self.pack = self._pack()

    def test_a_pin_beats_the_field_filter(self) -> None:
        """A physics skill in a chemistry run, because a previous chemistry run needed it."""
        without = install_run_skills(self.paths, self.pack, discipline="chemistry")
        self.assertNotIn("physics-two-things", without)
        with_pin = install_run_skills(
            self.paths, self.pack, discipline="chemistry", pinned=frozenset({"physics-two-things"})
        )
        self.assertIn("physics-two-things", with_pin)
        self.assertTrue((self.paths.skills_dir / "physics-two-things" / "SKILL.md").is_file())

    def test_a_pin_beats_a_predicate_that_does_not_match(self) -> None:
        self.assertNotIn("scoped-thing", install_run_skills(self.paths, self.pack))
        self.assertIn(
            "scoped-thing",
            install_run_skills(self.paths, self.pack, pinned=frozenset({"scoped-thing"})),
        )

    def test_an_unpinned_run_is_unchanged(self) -> None:
        self.assertEqual(
            install_run_skills(self.paths, self.pack),
            install_run_skills(self.paths, self.pack, pinned=frozenset()),
        )

    def test_a_pin_naming_nothing_in_the_pack_changes_nothing(self) -> None:
        """Silent by construction, which is why `validate_task_pins` exists."""
        self.assertEqual(
            install_run_skills(self.paths, self.pack, pinned=frozenset({"no-such-skill"})),
            install_run_skills(self.paths, self.pack),
        )

    def test_a_pin_is_announced_at_every_stage_and_marked_as_a_pin(self) -> None:
        """Unlike a shape match, which is announced only at the stages it names.

        A pin is short by construction and the stage that needed it is usually the one
        that had already gone wrong before anyone looked, so it is repeated.
        """
        entries = read_skill_pack(self.pack)
        pinned = frozenset({"physics-two-things"})
        for slug in ("01_literature_survey", "03_study_design", "07_writing"):
            block = format_skills_for_prompt(entries, slug, pinned)
            with self.subTest(stage=slug):
                self.assertIn("physics-two-things", block)
                self.assertIn("pinned to this task by name", block)

    def test_a_skill_that_is_both_pinned_and_shape_matched_is_listed_once(self) -> None:
        entries = read_skill_pack(self.pack)
        block = format_skills_for_prompt(entries, "06_analysis", frozenset({"scoped-thing"}))
        self.assertEqual(block.count("`scoped-thing`"), 1)

    def test_no_pin_means_no_pin_block(self) -> None:
        entries = read_skill_pack(self.pack)
        self.assertNotIn("pinned", format_skills_for_prompt(entries, "06_analysis", frozenset()))


class PinTableTest(unittest.TestCase):
    """The shipped table, and the ways it dies quietly."""

    PINS = REPO_ROOT / "configs" / "task_skill_pins.json"

    def test_every_pinned_name_is_a_skill_that_exists(self) -> None:
        """A renamed skill silently empties every pin that names it.

        `select_run_skills` filters the pack by name, so an unknown name selects
        nothing and the task runs with the pack it would have had anyway — no error,
        no log line, and a table that looks fine in the diff.
        """
        table = load_task_pins(self.PINS)
        self.assertEqual(validate_task_pins(table, SKILL_PACK), [])

    def test_the_table_parses_and_is_not_accidentally_empty(self) -> None:
        table = load_task_pins(self.PINS)
        self.assertTrue(self.PINS.is_file(), f"{self.PINS} is missing")
        self.assertTrue(table, "the pin table parsed to nothing")

    def test_a_malformed_table_is_ignored_rather_than_fatal(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "pins.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_task_pins(bad), {})
        self.assertEqual(load_task_pins(Path(tmp.name) / "absent.json"), {})

    def test_a_note_key_is_not_a_task(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "pins.json"
        path.write_text('{"_why": "a note", "T_000": ["a"]}', encoding="utf-8")
        self.assertEqual(load_task_pins(path), {"T_000": ["a"]})

    def test_the_validator_catches_the_ways_a_table_goes_wrong(self) -> None:
        problems = validate_task_pins(
            {"A_000": ["citation-discipline", "citation-discipline"],
             "B_000": ["no-such-skill"],
             "C_000": []},
            SKILL_PACK,
        )
        self.assertTrue(any("same skill twice" in p for p in problems), problems)
        self.assertTrue(any("not in" in p for p in problems), problems)
        self.assertTrue(any("empty list" in p for p in problems), problems)

    def test_pins_are_read_by_task_id(self) -> None:
        table = {"Physics_000": ["a", "b"]}
        self.assertEqual(pins_for("Physics_000", table), frozenset({"a", "b"}))
        self.assertEqual(pins_for("Physics_001", table), frozenset())
        self.assertEqual(pins_for(None, table), frozenset())

    def test_the_note_names_the_task_and_the_skills(self) -> None:
        note = pinned_skills_note("Physics_000", frozenset({"b", "a"}))
        self.assertIn("Physics_000", note)
        self.assertIn("a, b", note)
        self.assertEqual(pinned_skills_note("Physics_000", frozenset()), "")


class ThePinRecordSurvivesTest(unittest.TestCase):
    """`skill_pins` has to still be in the config after the run finishes starting.

    `Manager._install_skills` writes it and `ensure_run_config` used to run on the very
    next line of `create_run`, rebuilding the config field by field and dropping
    everything it does not name. So a pinned run logged that it was pinned and then
    published a config saying it was not — and the config is the half a later reader
    parses. Both halves or neither.
    """

    def test_ensure_run_config_keeps_a_key_it_does_not_manage(self) -> None:
        from src.utils import ensure_run_config, load_run_config, save_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run_0001")
            ensure_run_layout(paths)
            ensure_run_config(paths, model="opus")
            config = load_run_config(paths)
            config["skill_pins"] = ["a-skill"]
            config["skill_pin_task_id"] = "Physics_000"
            save_run_config(paths, config)

            ensure_run_config(paths, model="opus", venue="neurips_2025")

            after = load_run_config(paths)
            self.assertEqual(after.get("skill_pins"), ["a-skill"])
            self.assertEqual(after.get("skill_pin_task_id"), "Physics_000")
            self.assertEqual(after.get("venue"), "neurips_2025", "a managed field still wins")


class ForcedSkillsTest(unittest.TestCase):
    """Skills a front end installs on every run of a benchmark, over both filters.

    A third standing, and the reason it is not folded into either of the two that
    already exist. A predicate is an inference about the shape of *this* task; a pin
    is a record of what *this identifier* lost when it ran. Forcing is neither: it is
    a decision about a whole population, taken outside the run, on evidence the run
    cannot see. Recording it as a pin would put a claim in the prompt that is false —
    "a previous run of this exact task lost this" — and recording it as a predicate
    match would make the run's own brief responsible for a choice it did not make.

    It also closes a hole the predicate half cannot. `select_run_skills` fails closed
    on an empty brief: every task-scoped skill is refused, silently, and a front end
    that means "every run of this benchmark gets these five" has no way to say so.
    """

    def _pack(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, extra in (
            ("physics-forced-thing", "applies_when: widget\nstages: 02_hypothesis_generation"),
            ("scoped-design", "applies_when: widget\nstages: 03_study_design"),
            ("always-thing", ""),
        ):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a situation arises, at some stage.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        return root

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        self.pack = self._pack()
        self.entries = read_skill_pack(self.pack)

    def test_a_forced_skill_is_announced_under_its_own_banner(self) -> None:
        """Its own banner, and not the pin's. The pin sentence earns its force by being
        precise about a scored run of this exact task, and a forced skill has no such
        record behind it — so reusing that wording would put a false claim in the
        prompt of every run that reads it."""
        forced = frozenset({"physics-forced-thing"})
        block = format_skills_for_prompt(
            self.entries, "02_hypothesis_generation", frozenset(), forced
        )
        self.assertIn("physics-forced-thing", block)
        self.assertIn("installed on every run of this benchmark", block)
        self.assertNotIn("pinned to this task by name", block)
        self.assertIn("Read every one of them", block)

    def test_a_forced_skill_is_listed_once_and_not_also_as_a_shape_match(self) -> None:
        """Its predicate matches the brief too, and it must still be announced once.

        Two announcements of one skill spend two descriptions' worth of prompt on it
        and leave a reader deciding which of two justifications to believe.
        """
        forced = frozenset({"physics-forced-thing"})
        block = format_skills_for_prompt(
            self.entries, "02_hypothesis_generation", frozenset(), forced
        )
        self.assertEqual(block.count("`physics-forced-thing`"), 1)
        self.assertNotIn("selected against the brief you were given", block)

    def test_a_skill_that_is_both_pinned_and_forced_is_announced_as_forced(self) -> None:
        """The front end is what put it there on this run, so that is what is declared."""
        names = frozenset({"physics-forced-thing"})
        block = format_skills_for_prompt(self.entries, "02_hypothesis_generation", names, names)
        self.assertEqual(block.count("`physics-forced-thing`"), 1)
        self.assertIn("installed on every run of this benchmark", block)
        self.assertNotIn("pinned to this task by name", block)

    def test_a_forced_skill_is_announced_only_at_the_stages_it_names(self) -> None:
        forced = frozenset({"physics-forced-thing"})
        for slug in ("01_literature_survey", "03_study_design", "07_writing"):
            with self.subTest(stage=slug):
                block = format_skills_for_prompt(self.entries, slug, frozenset(), forced)
                self.assertNotIn("physics-forced-thing", block)
                self.assertNotIn("installed on every run of this benchmark", block)

    def test_a_forced_skill_that_names_no_stage_is_announced_everywhere(self) -> None:
        """Same fallback as a pin, and for the same reason: a skill nothing announces is
        a skill nobody is told about, which is the failure the routing must not create."""
        forced = frozenset({"always-thing"})
        for slug in ("01_literature_survey", "02_hypothesis_generation", "07_writing"):
            with self.subTest(stage=slug):
                self.assertIn(
                    "always-thing",
                    format_skills_for_prompt(self.entries, slug, frozenset(), forced),
                )

    def test_the_three_groups_are_rendered_weakest_claim_first(self) -> None:
        """Shape, then force, then pin. The last thing read is the strongest reason."""
        block = format_skills_for_prompt(
            self.entries,
            "02_hypothesis_generation",
            frozenset({"always-thing"}),
            frozenset({"physics-forced-thing"}),
        )
        self.assertLess(
            block.index("installed on every run of this benchmark"),
            block.index("pinned to this task by name"),
        )

    def test_forcing_nothing_renders_no_forced_block(self) -> None:
        """The control for every assertion above: the banner is absent when nothing
        was forced, so its presence in the others is the seam and not the template."""
        block = format_skills_for_prompt(
            self.entries, "03_study_design", frozenset(), frozenset()
        )
        self.assertIn("scoped-design", block)
        self.assertNotIn("installed on every run of this benchmark", block)

    def test_forcing_survives_a_predicate_that_rejects_everything(self) -> None:
        """`brief=""` is the fail-closed case, and it is the one that made this seam
        necessary: every task-scoped skill is refused and nothing says so."""
        without = install_run_skills(self.paths, self.pack, brief="")
        self.assertEqual(without, ["always-thing"])
        with_force = install_run_skills(
            self.paths, self.pack, brief="", pinned=frozenset({"physics-forced-thing"})
        )
        self.assertIn("physics-forced-thing", with_force)
        self.assertTrue((self.paths.skills_dir / "physics-forced-thing" / "SKILL.md").is_file())

    def test_forcing_beats_the_field_filter_too(self) -> None:
        """The name carries a field prefix the run is not in; it is installed anyway."""
        installed = install_run_skills(
            self.paths,
            self.pack,
            discipline="chemistry",
            brief="a widget",
            pinned=frozenset({"physics-forced-thing"}),
        )
        self.assertIn("physics-forced-thing", installed)


class ForcingIsDeclaredWhereAScoreIsReadTest(unittest.TestCase):
    """A forced run has to say so in the log and in the run config, or the seam is a
    silent prompt change.

    This is the whole point of the mechanism rather than a nicety. Two arms of the next
    trial differ by exactly this set, and the only durable statement that a given run
    was in the treatment arm is the one the run itself writes down: a directory listing
    of `.claude/skills/` is deleted with the workspace, and the front-end flag that
    caused it lives in somebody's shell history.
    """

    class _Operator:
        model = "test-model"
        backend_name = "claude"

    def _manager(self, project_root: Path, skills_dir: Path):
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI

        manager = ResearchManager(
            project_root=project_root,
            runs_dir=project_root / "runs",
            operator=self._Operator(),
            ui=TerminalUI(interactive=False, output_stream=io.StringIO()),
        )
        manager.skills_dir = skills_dir
        return manager

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.pack = self.root / "pack"
        for name in ("forced-one", "forced-two"):
            (self.pack / name).mkdir(parents=True)
            (self.pack / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a situation arises, at some "
                f"stage.\napplies_when: nothing in this brief\n"
                f"stages: 02_hypothesis_generation\n---\n\nbody\n",
                encoding="utf-8",
            )
        self.paths = build_run_paths(self.root / "runs" / "run_0001")
        ensure_run_layout(self.paths)
        from src.utils import ensure_run_config

        ensure_run_config(self.paths, model="opus")

    def test_a_forced_run_writes_both_halves_of_its_declaration(self) -> None:
        from src.utils import load_run_config, read_text

        manager = self._manager(self.root, self.pack)
        manager.skill_force = frozenset({"forced-one", "forced-two"})
        manager.skill_force_source = "test_agent:TEST_FORCED_SKILLS"
        installed = manager._install_skills(self.paths)

        self.assertEqual(sorted(installed), ["forced-one", "forced-two"])
        self.assertEqual(manager._forced_skills, frozenset({"forced-one", "forced-two"}))
        config = load_run_config(self.paths)
        self.assertEqual(config["skill_forced"], ["forced-one", "forced-two"])
        self.assertEqual(config["skill_forced_by"], "test_agent:TEST_FORCED_SKILLS")
        log = read_text(self.paths.logs)
        self.assertIn("skills forced_by_front_end", log)
        self.assertIn("is not comparable", log)
        self.assertIn("test_agent:TEST_FORCED_SKILLS", log)

    def test_an_unforced_run_writes_neither_half(self) -> None:
        """The control. Without it every assertion above could be the template."""
        from src.utils import load_run_config, read_text

        manager = self._manager(self.root, self.pack)
        manager._install_skills(self.paths)

        config = load_run_config(self.paths)
        self.assertNotIn("skill_forced", config)
        self.assertNotIn("skill_forced_by", config)
        self.assertNotIn("forced_by_front_end", read_text(self.paths.logs))

    def test_forcing_a_name_the_pack_does_not_have_declares_nothing(self) -> None:
        """Silent by construction otherwise: `select_run_skills` filters by name, so a
        renamed skill would leave a run config claiming a skill that never arrived."""
        from src.utils import load_run_config

        manager = self._manager(self.root, self.pack)
        manager.skill_force = frozenset({"forced-one", "no-such-skill"})
        manager.skill_force_source = "test_agent:TEST_FORCED_SKILLS"
        manager._install_skills(self.paths)

        self.assertEqual(load_run_config(self.paths)["skill_forced"], ["forced-one"])

    def test_a_forced_name_is_not_also_reported_as_a_pin(self) -> None:
        """One skill, one standing. Reporting it twice would double-count the treatment
        in any later census of which runs were pinned."""
        pins = self.root / "configs"
        pins.mkdir(parents=True, exist_ok=True)
        (pins / DEFAULT_PINS_FILENAME).write_text(
            json.dumps({"T_000": ["forced-one"]}), encoding="utf-8"
        )
        manager = self._manager(self.root, self.pack)
        manager.skill_task_id = "T_000"
        manager.skill_force = frozenset({"forced-one"})
        manager.skill_force_source = "test_agent:TEST_FORCED_SKILLS"
        manager._install_skills(self.paths)

        self.assertEqual(manager._forced_skills, frozenset({"forced-one"}))
        self.assertEqual(manager._pinned_skills, frozenset())


class TheForcedRecordSurvivesTest(unittest.TestCase):
    """`skill_forced` has to still be in the config after the run finishes starting.

    Written against the defect `ThePinRecordSurvivesTest` was written against, because
    it is the same defect one field along: `Manager._install_skills` writes the key and
    `ensure_run_config` rebuilds the config field by field, dropping everything it does
    not name. A forced run that logs the treatment and then publishes a config saying it
    had none is worse than one that records nothing, because the config is the half a
    later reader parses when they are deciding which arm a score came from.
    """

    def test_ensure_run_config_keeps_the_forced_keys_too(self) -> None:
        from src.utils import ensure_run_config, load_run_config, save_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run_0001")
            ensure_run_layout(paths)
            ensure_run_config(paths, model="opus")
            config = load_run_config(paths)
            config["skill_forced"] = ["a-skill", "b-skill"]
            config["skill_forced_by"] = "a_front_end:FORCED_SKILLS"
            save_run_config(paths, config)

            ensure_run_config(paths, model="opus", venue="neurips_2025")

            after = load_run_config(paths)
            self.assertEqual(after.get("skill_forced"), ["a-skill", "b-skill"])
            self.assertEqual(after.get("skill_forced_by"), "a_front_end:FORCED_SKILLS")
            self.assertEqual(after.get("venue"), "neurips_2025", "a managed field still wins")


class TheDeclarationSurvivesAFreshRunTest(unittest.TestCase):
    """The half the two `...RecordSurvives` tests above cannot reach: a *new* run.

    Both of those call `ensure_run_config` directly, which is the resume path, and
    `ensure_run_config` preserves keys it does not manage. So both were green for the
    whole period `skill_pins` was being dropped from every fresh run in production:
    `Manager._create_run` installed the skills and *then* called
    `initialize_run_config`, which does not preserve anything — it builds the config
    from scratch and writes it whole, over the keys `_install_skills` had just written.
    The log banner survived that and the config did not, which is the worse half to
    lose, because the log is prose and the config is what a later reader parses when
    they are deciding which arm a score came from.

    The repair is an ordering, and an ordering is exactly the kind of fix a suite does
    not hold: move `self._install_skills(paths)` back above `initialize_run_config` and
    every other test in this repository still passes. This one does not. It drives the
    real `_create_run` and reads the config off disk afterwards, and it covers both
    declarations at once because they are one defect — `skill_pins` is the half that was
    broken in production and `skill_forced` is the half that would have been broken next.
    """

    class _Operator:
        model = "test-model"
        backend_name = "claude"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.pack = self.root / "pack"
        # None of the three can be selected by the shape filter: the brief written below
        # matches no predicate here, so anything that arrives arrived by pin or by force.
        for name in ("forced-one", "forced-two", "pinned-one"):
            (self.pack / name).mkdir(parents=True)
            (self.pack / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a situation arises, at some "
                f"stage.\napplies_when: nothing in this brief\n"
                f"stages: 02_hypothesis_generation\n---\n\nbody\n",
                encoding="utf-8",
            )
        (self.root / "configs").mkdir(parents=True, exist_ok=True)
        (self.root / "configs" / DEFAULT_PINS_FILENAME).write_text(
            json.dumps({"T_000": ["pinned-one"]}), encoding="utf-8"
        )

    def _manager(self):
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI

        manager = ResearchManager(
            project_root=self.root,
            runs_dir=self.root / "runs",
            operator=self._Operator(),
            ui=TerminalUI(interactive=False, output_stream=io.StringIO()),
        )
        manager.skills_dir = self.pack
        return manager

    def test_a_fresh_run_writes_both_declarations_into_the_config_it_keeps(self) -> None:
        from src.utils import load_run_config, read_text

        manager = self._manager()
        manager.skill_task_id = "T_000"
        manager.skill_force = frozenset({"forced-one", "forced-two"})
        manager.skill_force_source = "a_front_end:FORCED_SKILLS"

        paths = manager._create_run("Scientific Objective: measure the widget.")

        config = load_run_config(paths)
        self.assertEqual(
            config.get("skill_forced"),
            ["forced-one", "forced-two"],
            "a fresh run lost `skill_forced`: the config was rebuilt after the skills "
            "were installed, so the run says it was in the control arm",
        )
        self.assertEqual(config.get("skill_forced_by"), "a_front_end:FORCED_SKILLS")
        self.assertEqual(
            config.get("skill_pins"),
            ["pinned-one"],
            "a fresh run lost `skill_pins`: this is the half that was silently broken "
            "in production for every run between the pin landing and its repair",
        )
        self.assertEqual(config.get("skill_pin_task_id"), "T_000")

        # The pack really did arrive, so the config is describing a run that happened.
        for name in ("forced-one", "forced-two", "pinned-one"):
            self.assertTrue((paths.skills_dir / name / "SKILL.md").is_file(), name)

        # Both banners too: the failure mode this guards against kept the log and lost
        # the config, so a test that only read the log would have stayed green.
        log = read_text(paths.logs)
        self.assertIn("skills forced_by_front_end", log)
        self.assertIn("skills pinned_by_task_id", log)

    def test_a_fresh_unforced_unpinned_run_declares_neither(self) -> None:
        """The control. Without it the four assertions above could be the template."""
        from src.utils import load_run_config

        paths = self._manager()._create_run("Scientific Objective: measure the widget.")

        config = load_run_config(paths)
        self.assertNotIn("skill_forced", config)
        self.assertNotIn("skill_pins", config)


class WithholdingIsWhatBuildsAControlArmTest(unittest.TestCase):
    """The one input that is not a routing decision, and why clearing `skill_force`
    could not do the job on its own.

    A benchmark front end since removed force-installed five skills that *also* carried a
    predicate matching all sixty of that benchmark's task statements. So the first
    version of `--no-forced-skills` cleared the force and the shape filter put the same
    five back, announced under the shape banner instead of the forced one — measured on a
    `--fake-operator` run, where the "control" arm differed from the treatment arm by one
    paragraph of prompt. A control a predicate can re-add is not a control, and it fails
    in the direction that produces a null result and an explanation for it.
    """

    def _pack(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, extra in (
            ("matching-thing", "applies_when: widget\nstages: 06_analysis"),
            ("always-thing", ""),
        ):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a situation arises, at some stage.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        return root

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Scientific Objective: measure the widget.")
        self.pack = self._pack()

    def test_withholding_beats_a_predicate_that_matches(self) -> None:
        self.assertIn("matching-thing", install_run_skills(self.paths, self.pack))
        self.assertNotIn(
            "matching-thing",
            install_run_skills(self.paths, self.pack, withheld=frozenset({"matching-thing"})),
        )

    def test_withholding_beats_a_pin(self) -> None:
        """A pin is the strongest routing input and this is not a routing input at all:
        a control arm a pin table can quietly opt out of is not one."""
        pinned = frozenset({"always-thing"})
        self.assertIn("always-thing", install_run_skills(self.paths, self.pack, pinned=pinned))
        self.assertNotIn(
            "always-thing",
            install_run_skills(
                self.paths, self.pack, pinned=pinned, withheld=frozenset({"always-thing"})
            ),
        )

    def test_a_withheld_skill_an_earlier_install_wrote_is_swept_from_disk(self) -> None:
        """The resume case, and the one that would have been silent: the run directory
        already holds the treatment arm's pack, and the flag would have changed only what
        the prompt said about it."""
        install_run_skills(self.paths, self.pack)
        self.assertTrue((self.paths.skills_dir / "matching-thing").is_dir())
        install_run_skills(self.paths, self.pack, withheld=frozenset({"matching-thing"}))
        self.assertFalse((self.paths.skills_dir / "matching-thing").exists())

    def test_withholding_nothing_changes_nothing(self) -> None:
        self.assertEqual(
            install_run_skills(self.paths, self.pack),
            install_run_skills(self.paths, self.pack, withheld=frozenset()),
        )

    def test_the_manager_withholds_what_the_front_end_told_it_to(self) -> None:
        """End to end through `_install_skills`, because that is where the two halves --
        the force set and the withhold set -- have to agree."""
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI

        class _Operator:
            model = "test-model"
            backend_name = "claude"

        manager = ResearchManager(
            project_root=Path(self._tmp.name),
            runs_dir=Path(self._tmp.name) / "runs",
            operator=_Operator(),
            ui=TerminalUI(interactive=False, output_stream=io.StringIO()),
        )
        manager.skills_dir = self.pack
        manager.skill_force = frozenset({"matching-thing"})
        manager.skill_force_source = "test_agent:TEST"
        manager.skill_withhold = frozenset({"matching-thing"})

        installed = manager._install_skills(self.paths)

        self.assertNotIn("matching-thing", installed)
        self.assertEqual(manager._forced_skills, frozenset())
