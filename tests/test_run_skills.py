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

import tempfile
import unittest
from pathlib import Path

from src.run_skills import (
    discipline_of,
    install_run_skills,
    read_skill_pack,
    validate_skill_pack,
)
from src.utils import build_run_paths, ensure_run_layout


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
        self.assertEqual(sorted(installed), sorted(entry.name for entry in read_skill_pack(SKILL_PACK)))
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
