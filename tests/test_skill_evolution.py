"""The third skill layer: what a run writes down for the next run in its field.

Two fixed layers ship with the pack -- guidance for all research, and guidance for one
field. Neither can know what a particular corpus punishes: that an archive stores its grid
transposed, that a reference implementation needs an undocumented flag. A run learns those
once, and without this layer the next run learns them again.

The whole risk of the layer is in one direction. A note travels to a *different task*, so a
note carrying a finding is contamination -- it invites the next run to expect an answer
instead of measuring one. Most of these tests are about refusing that.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.skill_evolution import (
    MAX_NOTES_PER_DISCIPLINE,
    MIN_NOTE_CHARS,
    install_learned_skill,
    load_notes,
    looks_like_a_result,
    record_note,
    validate_note,
)
from src.utils import build_run_paths, ensure_run_layout

GOOD = (
    "Several archives in this field store latitude descending, and the obvious reduction "
    "then averages over a flipped axis with no warning. Check the coordinate ordering "
    "against the file metadata before any spatial reduction, and assert it in code so a "
    "later refactor cannot silently undo the check."
)


class RefusesFindingsTest(unittest.TestCase):
    """A method note may travel between tasks. A measurement may not."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pool = Path(self._tmp.name)

    def test_a_measured_value_is_refused(self) -> None:
        note, problems = record_note(
            "earth", "What the RMSE came to",
            GOOD + " The RMSE came to 0.011719 on the held-out split.",
            "Earth_003", pool=self.pool)
        self.assertIsNone(note)
        self.assertTrue(any("measured value" in p for p in problems), problems)

    def test_a_stated_finding_is_refused_even_without_a_number(self) -> None:
        note, problems = record_note(
            "earth", "What we established", GOOD + " We found the cascade explains the gain.",
            "Earth_003", pool=self.pool)
        self.assertIsNone(note)
        self.assertTrue(any("finding" in p for p in problems), problems)

    def test_a_method_note_carrying_a_version_number_is_not_a_finding(self) -> None:
        """Refusing every digit would refuse most real guidance."""
        self.assertEqual(looks_like_a_result(GOOD + " This applies to v2 of the archive."), "")

    def test_a_method_note_is_accepted(self) -> None:
        note, problems = record_note("earth", "Check grid orientation first", GOOD,
                                     "Earth_003", pool=self.pool)
        self.assertEqual(problems, [])
        self.assertIsNotNone(note)


class NoteShapeTest(unittest.TestCase):
    def test_a_slogan_is_refused(self) -> None:
        self.assertTrue(any("slogan" in p for p in validate_note("earth", "Be careful", "Check things.")))

    def test_a_stage_summary_is_refused(self) -> None:
        self.assertTrue(any("stage summary" in p for p in
                            validate_note("earth", "A long one", "word " * 400)))

    def test_a_note_needs_a_routable_title(self) -> None:
        self.assertTrue(any("route on" in p for p in validate_note("earth", "hi", GOOD)))

    def test_the_floor_is_stated_rather_than_assumed(self) -> None:
        self.assertGreater(MIN_NOTE_CHARS, 0)


class PoolTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pool = Path(self._tmp.name)

    def test_fields_do_not_mix(self) -> None:
        """What is true of weather archives is not true of protein structures."""
        record_note("earth", "Grid orientation", GOOD, "Earth_003", pool=self.pool)
        self.assertEqual(len(load_notes("earth", pool=self.pool)), 1)
        self.assertEqual(load_notes("life", pool=self.pool), [])

    def test_rediscovering_a_lesson_refreshes_rather_than_doubles_it(self) -> None:
        record_note("earth", "Grid orientation", GOOD, "Earth_000", pool=self.pool)
        record_note("earth", "grid ORIENTATION", GOOD + " Also true of the reanalysis.",
                    "Earth_003", pool=self.pool)
        notes = load_notes("earth", pool=self.pool)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].learned_in, "Earth_003")

    def test_the_pool_is_capped_so_it_cannot_become_a_second_prompt(self) -> None:
        for i in range(MAX_NOTES_PER_DISCIPLINE + 5):
            record_note("earth", f"Lesson number {i:02d}", GOOD, f"Earth_{i:03d}", pool=self.pool)
        self.assertEqual(len(load_notes("earth", pool=self.pool)), MAX_NOTES_PER_DISCIPLINE)

    def test_an_unreadable_pool_is_no_notes_rather_than_a_crash(self) -> None:
        (self.pool / "earth.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(load_notes("earth", pool=self.pool), [])


class InstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pool = Path(self._tmp.name) / "pool"
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def test_a_field_with_no_history_installs_nothing(self) -> None:
        self.assertEqual(install_learned_skill(self.paths, "earth", pool=self.pool), "")

    def test_notes_arrive_as_one_skill_the_model_can_route_to(self) -> None:
        record_note("earth", "Check grid orientation first", GOOD, "Earth_003", pool=self.pool)
        name = install_learned_skill(self.paths, "earth", pool=self.pool)
        self.assertEqual(name, "learned-from-earlier-runs")
        text = (self.paths.skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Check grid orientation first", text)
        self.assertIn("descending", text)
        self.assertIn("never findings", text)

    def test_one_skill_not_one_per_note(self) -> None:
        """Twelve descriptions would crowd out the pack the run already has."""
        for i in range(4):
            record_note("earth", f"Lesson number {i:02d}", GOOD, f"Earth_{i:03d}", pool=self.pool)
        install_learned_skill(self.paths, "earth", pool=self.pool)
        installed = [p.name for p in self.paths.skills_dir.iterdir() if p.is_dir()]
        self.assertEqual(installed, ["learned-from-earlier-runs"])


if __name__ == "__main__":
    unittest.main()
