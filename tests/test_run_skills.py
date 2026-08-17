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

import re
import tempfile
import unittest
from pathlib import Path

from src.run_skills import (
    discipline_of,
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
