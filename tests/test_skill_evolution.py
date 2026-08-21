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
import os
import tempfile
import unittest
from pathlib import Path

from src.skill_evolution import (
    DEFAULT_POOL,
    MAX_NOTES_PER_DISCIPLINE,
    MIN_NOTE_CHARS,
    POOL_ENV_VAR,
    default_pool,
    install_learned_skill,
    load_notes,
    looks_like_a_result,
    pool_fingerprint,
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


class ASharedChannelMustLeaveAReceiptTest(unittest.TestCase):
    """The pool is the one input two arms of an ablation cannot pin.

    Everything else a run reads is inside its worktree, so an ablation pins two commits
    and the difference between them is the treatment. This is not: `DEFAULT_POOL` is
    `~/.autor/learned_skills`, outside every worktree and every run directory, and it is
    rewritten while arms run -- twelve notes per field, oldest evicted.

    Measured on the `pins_on`/`pins_off` ablation: the installed skill was byte-identical
    in all forty pairs, so the channel cancelled in the paired difference. But that is a
    fact about scheduling -- the twins launch in the same second and read the same
    snapshot -- not about the design. A task relaunched out of step with its twin reads a
    different pool, and nothing anywhere said which one it read.

    Two things follow: a run records what it read, and a paired arm can be given a pool
    of its own.
    """

    def setUp(self) -> None:
        self._saved = os.environ.pop(POOL_ENV_VAR, None)

    def tearDown(self) -> None:
        os.environ.pop(POOL_ENV_VAR, None)
        if self._saved is not None:
            os.environ[POOL_ENV_VAR] = self._saved

    def test_unset_the_pool_is_exactly_where_it_was(self) -> None:
        """The override may not move the default for anyone who has not asked."""
        self.assertEqual(default_pool(), DEFAULT_POOL)

    def test_the_environment_moves_the_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            self.assertEqual(default_pool(), Path(tmp))

    def test_it_is_read_at_call_time_not_import_time(self) -> None:
        """A launcher that sets it after import must still get the pool it asked for."""
        with tempfile.TemporaryDirectory() as tmp:
            before = default_pool()
            os.environ[POOL_ENV_VAR] = tmp
            self.assertNotEqual(default_pool(), before)

    def test_reads_and_writes_go_to_the_same_pool(self) -> None:
        """A private read with a shared write is worse than no isolation: it looks isolated.

        `record_note` defaulted to `DEFAULT_POOL` while `load_notes` honoured the override,
        which would have given an isolated arm a private view and a shared side effect.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            note, problems = record_note("physics", "A title that is long enough", GOOD, "run-1")
            self.assertEqual(problems, [])
            self.assertIsNotNone(note)
            self.assertTrue((Path(tmp) / "physics" / "learned_notes.json").is_file())
            self.assertEqual(len(load_notes("physics")), 1)

    def test_the_fingerprint_names_what_was_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            record_note("physics", "A title that is long enough", GOOD, "run-1")
            fp = pool_fingerprint("physics")
            self.assertEqual(fp["pool"], tmp)
            self.assertEqual(fp["discipline"], "physics")
            self.assertEqual(fp["notes"], 1)
            self.assertTrue(fp["digest"])

    def test_an_empty_pool_fingerprints_as_empty_rather_than_as_a_hash(self) -> None:
        """A digest over nothing is a constant, and a constant reads as agreement."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            fp = pool_fingerprint("physics")
            self.assertEqual(fp["notes"], 0)
            self.assertEqual(fp["digest"], "")

    def test_the_digest_changes_when_the_notes_change(self) -> None:
        """The whole point: two runs that read different pools must not agree."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            record_note("physics", "A title that is long enough", GOOD, "run-1")
            first = pool_fingerprint("physics")["digest"]
            record_note("physics", "A second title, also long enough", GOOD.replace("latitude", "longitude"), "run-2")
            second = pool_fingerprint("physics")["digest"]
            self.assertNotEqual(first, second)

    def test_two_runs_reading_the_same_pool_agree(self) -> None:
        """And the converse, or the receipt would flag every pair as contaminated."""
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            record_note("physics", "A title that is long enough", GOOD, "run-1")
            self.assertEqual(
                pool_fingerprint("physics")["digest"], pool_fingerprint("physics")["digest"]
            )

    def test_different_fields_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            record_note("physics", "A title that is long enough", GOOD, "run-1")
            self.assertEqual(pool_fingerprint("chemistry")["notes"], 0)
            self.assertNotEqual(
                pool_fingerprint("physics")["digest"], pool_fingerprint("chemistry")["digest"]
            )

    def test_the_digest_covers_the_body_and_not_just_the_title(self) -> None:
        """A note's content is its body; two pools can agree on titles and differ entirely.

        `record_note` replaces a note with the same title, so this rewrites one note's body
        and nothing else. A digest over titles alone passes every other test in this class
        and would report a contaminated pair as clean.
        """
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[POOL_ENV_VAR] = tmp
            title = "A title that is long enough"
            record_note("physics", title, GOOD, "run-1")
            first = pool_fingerprint("physics")["digest"]
            record_note("physics", title, GOOD.replace("latitude", "longitude"), "run-2")
            after = pool_fingerprint("physics")
            self.assertEqual(after["notes"], 1, "the title should have deduplicated")
            self.assertNotEqual(first, after["digest"])

    def test_the_digest_covers_the_title_too(self) -> None:
        """Titles are rendered as headings in the installed skill, so they are content.

        Two pools, one note each, same body and different titles: a digest over bodies
        alone calls them identical.
        """
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            os.environ[POOL_ENV_VAR] = a
            record_note("physics", "The first title, long enough", GOOD, "run-1")
            first = pool_fingerprint("physics")["digest"]
            os.environ[POOL_ENV_VAR] = b
            record_note("physics", "A different title, also long", GOOD, "run-1")
            second = pool_fingerprint("physics")["digest"]
            self.assertNotEqual(first, second)

    def test_the_field_separators_are_load_bearing(self) -> None:
        """Without them the digest hashes a concatenation, and boundaries stop mattering.

        `("ab", "c")` and `("a", "bc")` are different pools that a separator-free digest
        calls identical. Contrived, and pinned anyway: a separator is invisible, cheap, and
        the sort of thing a later edit removes as noise. Written straight into the pool
        file because `record_note` would reject titles and bodies this short, and the
        digest reads whatever is on disk.
        """
        def write(pool: str, title: str, body: str) -> None:
            path = Path(pool) / "physics" / "learned_notes.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps([{"discipline": "physics", "title": title, "body": body,
                             "learned_in": "run-1", "recorded_at": "2026-01-01"}]),
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            write(a, "ab", "c")
            write(b, "a", "bc")
            os.environ[POOL_ENV_VAR] = a
            first = pool_fingerprint("physics")["digest"]
            os.environ[POOL_ENV_VAR] = b
            self.assertNotEqual(first, pool_fingerprint("physics")["digest"])
