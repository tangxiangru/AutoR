"""A benchmark row addressed by the wrong identifier loses a task and says nothing.

``research/test.jsonl`` has sixty rows and fifty-nine distinct ``task_group_id`` values:
rows 6 and 11 are byte-identical, group id included. Any store keyed on that id holds
fifty-nine entries, writes the second copy over the first, reports success, and drops the
most expensive thing in the file — a whole task's worth of paired evidence. Nothing
raises. :class:`TaskKeysAreRowIndicesTest` is the gate, and it carries the control that
makes the claim real: the same fixture indexed by group id really does come out one short.

The second defect this module is written against is quieter. The ``answer`` field of a row
is not an answer, it is a rubric, and three plausible ways to read it are wrong on most of
the split without failing: an integer ``Points:`` regex is wrong on 60 of 60 rows,
"one non-empty line is one item" on 33 of 60, and scraping ``N pts`` tokens on 58 of 60 —
the last because the rubric decomposes an item into weighted markdown sub-bullets that
look exactly like items. Every one of those produces a plausible item count and a
plausible total. :func:`src.frontierscience.parse_rubric` refuses instead, and the tests
below hold one positive and one negative case against each of its refusals.

``tests/fixtures/fs_synthetic.jsonl`` is written here rather than taken from the dataset.
It holds five problems and rubrics of my own — flat items, multi-line item descriptions,
weighted sub-bullets, a two-level sub-bullet tree, a decoration with its asterisks in the
wrong place, an ``&gt;`` the author never escaped, and totals that come to exactly ten
through eighths — plus a sixth line that is a byte-identical repeat of the second, which
is the rows 6/11 shape. No line of the real examination text is committed anywhere in this
repository: the tests that need the real file are gated on its presence and check it
against ``tests/fixtures/fs_manifest.json``, which holds digests, counts and subjects and
cannot be inverted into a single character of the questions.

Regenerate that manifest with::

    python3 -m tests.test_fs_dataset --manifest
"""

from __future__ import annotations

import json
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

from src.frontierscience import (
    DatasetRefused,
    FS_DATASET_ENV_VAR,
    FS_DATASET_POINTS_PER_ROW,
    FS_DATASET_ROWS,
    FS_DATASET_RUBRIC_ITEMS,
    FS_DATASET_SHA256,
    FS_DATASET_SUBJECT_ROWS,
    FS_DATASET_URL,
    FS_DEFAULT_DATASET_PATH,
    FS_RUBRIC_HEAD_PATTERN,
    FS_TASK_SELECTION_HELP,
    FS_TASK_SUBSET_ARGUMENTS,
    FsRow,
    RubricItem,
    RubricParseError,
    load_dataset,
    parse_rubric,
    resolve_dataset_path,
    resolve_task_keys,
    rows_by_key,
    task_key,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
SYNTHETIC = FIXTURES / "fs_synthetic.jsonl"
MANIFEST = FIXTURES / "fs_manifest.json"


def synthetic_payloads() -> list[dict]:
    """The fixture rows as they sit on disk, before anything interprets them."""
    return [
        json.loads(line)
        for line in SYNTHETIC.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def synthetic_rows() -> list[FsRow]:
    """The fixture through the real row constructor, which parses each rubric."""
    return [FsRow.from_payload(index, payload) for index, payload in enumerate(synthetic_payloads())]


def dataset_present() -> bool:
    """Whether the pinned split is on this machine, in the order the code looks for it.

    A skip, not a failure. The dataset is not committed and CI installs nothing, so on a
    clean runner the real-file tests must be absent rather than red — and the synthetic
    tests above them hold the grammar either way.
    """
    return resolve_dataset_path(None).is_file()


class TheRubricGrammarIsAssertedNotAssumedTest(unittest.TestCase):
    """One positive and one negative case for every refusal the parser makes."""

    def setUp(self) -> None:
        self.payloads = synthetic_payloads()

    def test_the_fixture_this_scan_reads_is_not_empty(self) -> None:
        """The control. Every assertion below is vacuous over an empty fixture."""
        self.assertGreaterEqual(len(self.payloads), 5, "the synthetic fixture lost its rows")
        self.assertTrue(all(payload.get("answer") for payload in self.payloads))

    def test_every_synthetic_row_parses_under_the_strict_grammar(self) -> None:
        for index, payload in enumerate(self.payloads):
            with self.subTest(row=index):
                items = parse_rubric(payload["answer"])
                self.assertGreater(len(items), 0)
                self.assertAlmostEqual(
                    sum(item.points for item in items), FS_DATASET_POINTS_PER_ROW, places=6
                )

    def test_the_fixture_covers_the_shapes_it_claims_to(self) -> None:
        """A fixture that quietly lost its hard rows would keep every test above green."""
        rubrics = [payload["answer"] for payload in self.payloads]
        joined = "\n".join(rubrics)
        self.assertIn("- **(0.25pts)**", joined, "no weighted sub-bullet in the fixture")
        self.assertIn("    - **(1.5pts)**", joined, "no two-level sub-bullet tree")
        self.assertIn("(**0.125pts)", joined, "no misplaced-asterisk decoration")
        self.assertIn("&gt;", joined, "no unescaped HTML entity")
        self.assertTrue(
            any(len([line for line in text.split("\n") if not line.startswith("Points:")]) > 1
                for text in rubrics),
            "no multi-line item description",
        )

    def test_a_weighted_sub_bullet_is_not_a_rubric_item(self) -> None:
        """The measured failure: scraping `N pts` tokens is wrong on 58 of the 60 real rows."""
        items = parse_rubric(self.payloads[2]["answer"])
        self.assertEqual([item.points for item in items], [4.0, 3.0, 3.0])
        self.assertIn("- **(2.0pts)**", items[0].description)

    def test_a_two_level_sub_bullet_tree_stays_inside_one_item(self) -> None:
        items = parse_rubric(self.payloads[3]["answer"])
        self.assertEqual(len(items), 3)
        self.assertIn("- **(1.5pts)**", items[0].description)

    def test_a_decoration_with_its_asterisks_in_the_wrong_place_is_still_not_an_item(self) -> None:
        """Decided on the column-0 anchor, so the shape of the decoration cannot matter."""
        items = parse_rubric(self.payloads[4]["answer"])
        self.assertEqual(len(items), 8)
        self.assertIn("(**0.125pts)", items[5].description)

    def test_a_continuation_line_joins_the_item_above_it(self) -> None:
        items = parse_rubric(self.payloads[1]["answer"])
        self.assertEqual(len(items), 4)
        self.assertIn("\n", items[0].description)
        self.assertIn("the substrate is primary", items[0].description)

    def test_an_html_entity_is_left_exactly_as_the_author_wrote_it(self) -> None:
        """No unescaping anywhere: the judge is shown the raw field, entity and all."""
        items = parse_rubric(self.payloads[0]["answer"])
        self.assertIn("&gt;", items[2].description)
        self.assertNotIn("theta > 0", items[2].description)

    def test_parse_rubric_does_not_modify_the_text_it_is_given(self) -> None:
        for index, payload in enumerate(self.payloads):
            with self.subTest(row=index):
                original = payload["answer"]
                copy = str(original)
                parse_rubric(original)
                self.assertEqual(original, copy)

    def test_the_head_pattern_is_anchored_at_column_zero(self) -> None:
        self.assertIsNotNone(FS_RUBRIC_HEAD_PATTERN.match("Points: 1.0, Item: an item"))
        self.assertIsNone(FS_RUBRIC_HEAD_PATTERN.match(" Points: 1.0, Item: indented"))
        self.assertIsNone(FS_RUBRIC_HEAD_PATTERN.match("- **(1.0pts)** a sub-bullet"))

    def test_an_indented_head_is_refused_rather_than_silently_absorbed(self) -> None:
        """The anchor and the count guard together. Absorbing the indented line into the
        description above it would be the quiet answer, and it would lose five points."""
        with self.assertRaises(RubricParseError) as caught:
            parse_rubric("Points: 10.0, Item: the only item\n  Points: 5.0, Item: indented")
        self.assertIn("substrings but", str(caught.exception))

    def test_text_before_the_first_item_is_refused(self) -> None:
        with self.assertRaises(RubricParseError) as caught:
            parse_rubric("Grade the answer below.\nPoints: 10.0, Item: the only item")
        self.assertIn("before the first", str(caught.exception))

    def test_an_empty_rubric_is_refused_rather_than_scored_as_zero(self) -> None:
        with self.assertRaises(RubricParseError):
            parse_rubric("")
        with self.assertRaises(RubricParseError):
            parse_rubric("\n\n   \n")

    def test_a_head_token_inside_a_description_is_refused(self) -> None:
        """Two readers disagreeing means every item boundary after it is a guess."""
        with self.assertRaises(RubricParseError) as caught:
            parse_rubric(
                "Points: 10.0, Item: the item\nsee \\text{Points: 3} in the expression above"
            )
        self.assertIn("substrings but", str(caught.exception))

    def test_a_rubric_that_does_not_total_ten_is_refused(self) -> None:
        with self.assertRaises(RubricParseError) as caught:
            parse_rubric("Points: 4.0, Item: one\nPoints: 5.0, Item: two")
        self.assertIn("sum to 9.0", str(caught.exception))

    def test_a_total_reached_through_eighths_is_accepted(self) -> None:
        """The other side of the same clause: 1e-6, not exact equality, because the real
        rubrics accumulate 0.125 and 0.25 weights and a float sum of those is not exact."""
        items = parse_rubric(self.payloads[4]["answer"])
        self.assertEqual(len(items), 8)
        self.assertIn(0.125, [item.points for item in items])


class TaskKeysAreRowIndicesTest(unittest.TestCase):
    """Rows 6 and 11 of the real split are byte-identical. Keys must still differ."""

    def setUp(self) -> None:
        self.rows = synthetic_rows()

    def test_two_byte_identical_rows_get_two_different_keys(self) -> None:
        first, repeat = self.rows[1], self.rows[5]
        self.assertEqual(first.task_group_id, repeat.task_group_id)
        self.assertEqual(first.rubric_sha256, repeat.rubric_sha256)
        self.assertNotEqual(first.key, repeat.key)
        self.assertEqual(len(rows_by_key(self.rows)), len(self.rows))

    def test_indexing_the_same_rows_by_group_id_really_does_lose_one(self) -> None:
        """The control. Without it the test above only says two strings differ."""
        by_group = {row.task_group_id: row for row in self.rows}
        self.assertEqual(len(by_group), len(self.rows) - 1)

    def test_the_key_format_sorts_numerically_when_sorted_as_text(self) -> None:
        keys = [task_key(index) for index in (0, 2, 9, 10, 59)]
        self.assertEqual(keys, ["fs:000", "fs:002", "fs:009", "fs:010", "fs:059"])
        self.assertEqual(sorted(keys), keys)


class TheDatasetIsPinnedTest(unittest.TestCase):
    """A file that cannot be identified is refused, and there is nowhere to fall back to."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_a_missing_file_names_the_url_and_the_environment_variable(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            load_dataset(self.tmp / "nothing.jsonl", environ={})
        message = str(caught.exception)
        self.assertIn(FS_DATASET_URL, message)
        self.assertIn(FS_DATASET_ENV_VAR, message)

    def test_a_digest_mismatch_is_refused_and_nothing_is_returned(self) -> None:
        wrong = self.tmp / "wrong.jsonl"
        wrong.write_text(SYNTHETIC.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(DatasetRefused) as caught:
            load_dataset(wrong, environ={})
        self.assertIn("not the pinned", str(caught.exception))

    def test_a_bad_explicit_path_does_not_fall_back_to_a_good_cached_one(self) -> None:
        """The failure this refusal exists against: the easiest repair for a broken
        ``--dataset`` is to use whatever copy is already on disk, which produces a full
        result file measured against an input the flags do not name."""
        wrong = self.tmp / "wrong.jsonl"
        wrong.write_text("{}\n", encoding="utf-8")
        environ = {FS_DATASET_ENV_VAR: str(FS_DEFAULT_DATASET_PATH)}
        with self.assertRaises(DatasetRefused):
            load_dataset(wrong, environ=environ)

    def test_the_resolution_order_is_flag_then_environment_then_cache(self) -> None:
        environ = {FS_DATASET_ENV_VAR: "/from/env.jsonl"}
        self.assertEqual(
            resolve_dataset_path("/from/flag.jsonl", environ=environ), Path("/from/flag.jsonl")
        )
        self.assertEqual(resolve_dataset_path(None, environ=environ), Path("/from/env.jsonl"))
        self.assertEqual(resolve_dataset_path(None, environ={}), FS_DEFAULT_DATASET_PATH)

    def test_the_default_dataset_path_is_outside_any_repository(self) -> None:
        """The dataset card asks that this text not enter a crawlable corpus, and a
        default inside the tree is one ``git add -A`` away from putting it in one."""
        default = FS_DEFAULT_DATASET_PATH.resolve()
        self.assertFalse(str(default).startswith(str(REPO.resolve()) + "/"))

    def test_no_examination_text_is_tracked_in_this_repository(self) -> None:
        """The scan, and it needs the population control below to mean anything."""
        import subprocess

        listing = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=False
        )
        if listing.returncode != 0:  # pragma: no cover - not a git checkout
            self.skipTest("not a git checkout")
        names = [name for name in listing.stdout.split() if name]
        self.assertGreater(len(names), 100, "git ls-files returned almost nothing")
        offenders = [name for name in names if Path(name).name == "research_test.jsonl"]
        self.assertEqual(offenders, [], f"the dataset is committed: {offenders}")

    def test_the_committed_manifest_holds_no_examination_text(self) -> None:
        """The fingerprints are the compromise that lets the real file be checked at all.

        Checked by shape rather than by reading them: every field is a digest, a count, a
        subject name or a key, and the longest string a fingerprint may carry is 64
        characters. A row of the real split is thousands. So a future edit that adds
        ``"problem": ...`` to make a failure easier to debug fails here instead.
        """
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        allowed = {
            "key", "subject", "problem_sha256", "problem_chars", "rubric_sha256",
            "rubric_chars", "rubric_items", "rubric_points_total", "duplicate_of",
        }
        self.assertEqual(len(manifest["row_fingerprints"]), FS_DATASET_ROWS)
        for entry in manifest["row_fingerprints"]:
            self.assertEqual(set(entry), allowed)
            for name, value in entry.items():
                self.assertIsInstance(value, (str, int, float, type(None)), name)
                if isinstance(value, str):
                    self.assertLessEqual(len(value), 64, f"{name} is too long to be a digest")


class TheTaskSubsetIsExplicitTest(unittest.TestCase):
    """Five syntaxes, one intersection, one seeded draw, and four refusals."""

    def setUp(self) -> None:
        self.rows = [
            FsRow.from_payload(index, payload)
            for index, payload in enumerate(_sixty_synthetic_payloads())
        ]

    def test_all_selects_every_row(self) -> None:
        self.assertEqual(len(resolve_task_keys(self.rows)), FS_DATASET_ROWS)
        self.assertEqual(len(resolve_task_keys(self.rows, tasks="all")), FS_DATASET_ROWS)

    def test_a_comma_list_of_row_indices_selects_those_rows(self) -> None:
        self.assertEqual(resolve_task_keys(self.rows, tasks="0,3,7"), ["fs:000", "fs:003", "fs:007"])

    def test_a_task_key_selects_itself(self) -> None:
        self.assertEqual(resolve_task_keys(self.rows, tasks="fs:000"), ["fs:000"])

    def test_ranges_are_inclusive_at_both_ends(self) -> None:
        keys = resolve_task_keys(self.rows, tasks="10-12,40-41")
        self.assertEqual(keys, ["fs:010", "fs:011", "fs:012", "fs:040", "fs:041"])

    def test_the_subject_filter_is_an_intersection_not_a_replacement(self) -> None:
        keys = resolve_task_keys(self.rows, tasks="0-29", subject="chemistry")
        self.assertTrue(all(self.rows[int(key[3:])].subject == "chemistry" for key in keys))
        self.assertLess(len(keys), 30)

    def test_a_seeded_sample_is_the_algorithm_the_help_text_names(self) -> None:
        keys = resolve_task_keys(self.rows, sample=8, sample_seed=20260817)
        by_hand = sorted(
            random.Random(20260817).sample(sorted(row.key for row in self.rows), 8)
        )
        self.assertEqual(keys, by_hand)
        self.assertEqual(keys, resolve_task_keys(self.rows, sample=8, sample_seed=20260817))

    def test_the_subset_arguments_name_the_algorithm_so_it_can_be_redone_by_hand(self) -> None:
        """The seeded draw's algorithm is written down; it just is not written down in a
        flag's help, because there is no flag."""
        self.assertIn("random.Random(S).sample(sorted(keys), N)", FS_TASK_SUBSET_ARGUMENTS)

    def test_the_help_text_promises_no_flag_no_front_end_declares(self) -> None:
        """Prose is a specification here.

        `FS_TASK_SELECTION_HELP` reaches a reader as the `--task` help on two front ends
        and as the tail of every spec refusal. It promised a `--tasks`, a `--subject` and
        a `--sample N --sample-seed S`, and nothing has ever declared any of them:
        `fs_agent.py` and `tools/score_fs_run.py` each take one `--task`, and the trial
        driver's population is the explicit `tasks` list in its plan.
        """
        declared = set()
        for name in ("fs_agent.py", "tools/score_fs_run.py", "tools/fs_trial.py"):
            body = (REPO / name).read_text(encoding="utf-8")
            declared |= set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', body))
        self.assertIn("--task", declared, "the scan found no flags to check against")
        promised = set(re.findall(r"(--[a-z][a-z0-9-]*)", FS_TASK_SELECTION_HELP))
        self.assertEqual(sorted(promised - declared), [])

    def test_the_scan_would_notice_a_promise_nobody_keeps(self) -> None:
        """The control: guards the regex rather than the tree."""
        self.assertEqual(
            re.findall(r"(--[a-z][a-z0-9-]*)", "use --subject and --sample-seed"),
            ["--subject", "--sample-seed"],
        )

    def test_a_sample_without_a_seed_is_refused(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            resolve_task_keys(self.rows, sample=4)
        self.assertIn("reproduced", str(caught.exception))
        # And it says what to pass, which is an argument and not a flag.
        self.assertIn("Neither is a command-line flag", str(caught.exception))

    def test_a_sample_larger_than_the_selection_is_refused_not_truncated(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            resolve_task_keys(self.rows, tasks="0-9", sample=40, sample_seed=1)
        self.assertIn("refusing rather than truncating", str(caught.exception))

    def test_an_index_outside_the_dataset_is_refused_not_skipped(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            resolve_task_keys(self.rows, tasks="58-61")
        self.assertIn("outside the dataset", str(caught.exception))

    def test_an_unreadable_spec_is_refused_with_the_grammar_attached(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            resolve_task_keys(self.rows, tasks="physics")
        self.assertIn("inclusive index ranges", str(caught.exception))
        self.assertIn(FS_TASK_SELECTION_HELP, str(caught.exception))

    def test_an_unknown_subject_is_refused(self) -> None:
        with self.assertRaises(DatasetRefused) as caught:
            resolve_task_keys(self.rows, subject="astronomy")
        self.assertIn("unknown subject", str(caught.exception))

    def test_an_empty_intersection_is_refused_rather_than_returned_empty(self) -> None:
        with self.assertRaises(DatasetRefused):
            resolve_task_keys(self.rows, tasks="0", subject="biology")


class FsRowSerialisationTest(unittest.TestCase):
    """Two serialisations, and only one of them may carry the questions."""

    def setUp(self) -> None:
        self.row = synthetic_rows()[0]

    def test_a_row_survives_a_round_trip_through_its_own_dictionary(self) -> None:
        self.assertEqual(FsRow.from_dict(self.row.to_dict()), self.row)

    def test_a_malformed_record_reads_as_defaults_rather_than_raising(self) -> None:
        """Defensive by contract: a record that cannot be read is not a run to crash on."""
        row = FsRow.from_dict({"row_index": "not a number", "rubric_points_total": None})
        self.assertEqual(row.row_index, 0)
        self.assertEqual(row.key, "fs:000")
        self.assertEqual(row.rubric_points_total, 0.0)
        self.assertIsNone(row.duplicate_of)

    def test_the_task_block_carries_no_examination_text(self) -> None:
        block = json.dumps(self.row.task_block())
        self.assertNotIn(self.row.problem[:40], block)
        self.assertNotIn(self.row.rubric[:40], block)
        self.assertIn(self.row.rubric_sha256, block)

    def test_a_rubric_item_survives_a_round_trip_and_a_malformed_record(self) -> None:
        item = RubricItem(index=3, points=0.125, description="something")
        self.assertEqual(RubricItem.from_dict(item.to_dict()), item)
        self.assertEqual(RubricItem.from_dict({"points": "x"}).points, 0.0)


@unittest.skipUnless(dataset_present(), "the pinned FrontierScience split is not on this machine")
class AgainstTheRealDatasetTest(unittest.TestCase):
    """The numbers this whole integration rests on, checked against the file itself."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_dataset(None)
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_the_split_holds_sixty_rows_and_six_hundred_and_thirty_five_items(self) -> None:
        self.assertEqual(len(self.rows), FS_DATASET_ROWS)
        self.assertEqual(sum(row.rubric_items for row in self.rows), FS_DATASET_RUBRIC_ITEMS)

    def test_every_row_totals_exactly_ten_points(self) -> None:
        for row in self.rows:
            with self.subTest(task=row.key):
                self.assertAlmostEqual(row.rubric_points_total, FS_DATASET_POINTS_PER_ROW, places=9)

    def test_the_subjects_are_twenty_each(self) -> None:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.subject] = counts.get(row.subject, 0) + 1
        self.assertEqual(counts, FS_DATASET_SUBJECT_ROWS)

    def test_rows_six_and_eleven_are_the_duplicate_and_both_survive_the_load(self) -> None:
        duplicates = [(row.row_index, row.duplicate_of) for row in self.rows if row.duplicate_of is not None]
        self.assertEqual(duplicates, [(11, 6)])
        self.assertEqual(self.rows[6].task_group_id, self.rows[11].task_group_id)
        self.assertEqual(len(rows_by_key(self.rows)), FS_DATASET_ROWS)

    def test_every_row_matches_the_committed_fingerprint(self) -> None:
        self.assertEqual(self.manifest["dataset_sha256"], FS_DATASET_SHA256)
        fingerprints = {entry["key"]: entry for entry in self.manifest["row_fingerprints"]}
        self.assertEqual(len(fingerprints), FS_DATASET_ROWS)
        for row in self.rows:
            with self.subTest(task=row.key):
                entry = fingerprints[row.key]
                self.assertEqual(entry["subject"], row.subject)
                self.assertEqual(entry["problem_sha256"], row.problem_sha256)
                self.assertEqual(entry["rubric_sha256"], row.rubric_sha256)
                self.assertEqual(entry["rubric_items"], row.rubric_items)
                self.assertEqual(entry["duplicate_of"], row.duplicate_of)

    def test_each_load_time_guard_refuses_when_what_it_pins_moves(self) -> None:
        """The guards, not the facts. Four of ``load_dataset``'s six refusals were dead.

        ``if len(rows) != FS_DATASET_ROWS:``, the subject-count check and the item-count
        check could each be replaced with ``if False:`` and the whole suite stayed green,
        because the tests above re-assert the same three facts on the rows that come *back*
        — and the facts hold, so removing the guard is invisible. The only way into a
        refusal branch that is guarded by an equality against the real, pinned bytes is to
        move the constant instead of the file, which is what this does.

        The blob-sha1 branch is deliberately not here. It sits behind the sha256 equality
        over the same bytes, so it is unreachable by construction and its own message says
        as much; a test that reached it would have to lie about which pin was wrong. Its
        *constant* is covered all the same, and in the direction that matters: changing
        ``FS_DATASET_BLOB_SHA1`` makes ``load_dataset`` refuse the real file and takes this
        whole class down with it.
        """
        import unittest.mock

        cases = (
            ("FS_DATASET_ROWS", 59, "rows, not 59"),
            ("FS_DATASET_SUBJECT_ROWS", {"physics": 20, "chemistry": 20, "biology": 21},
             "subject counts"),
            ("FS_DATASET_RUBRIC_ITEMS", 634, "the grammar in parse_rubric has moved"),
        )
        for name, wrong, marker in cases:
            with self.subTest(guard=name):
                with unittest.mock.patch(f"src.frontierscience.{name}", wrong):
                    with self.assertRaises(DatasetRefused) as caught:
                        load_dataset(None)
                self.assertIn(marker, str(caught.exception))

    def test_the_real_file_loads_when_none_of_those_constants_is_moved(self) -> None:
        """The control for the three refusals above. Without it they would all pass against
        a ``load_dataset`` that refused every file it was ever handed."""
        self.assertEqual(len(load_dataset(None)), FS_DATASET_ROWS)

    def test_the_sibling_olympiad_split_is_rejected_by_the_same_grammar(self) -> None:
        """The negative control for '60 of 60 parse'. Without it the grammar could be
        `return [RubricItem(0, 10.0, text)]` and every count above would still hold."""
        olympiad = Path.home() / ".cache" / "frontierscience" / "olympiad_test.jsonl"
        if not olympiad.is_file():
            self.skipTest("the olympiad split is not on this machine")
        rejected = 0
        total = 0
        for line in olympiad.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            try:
                parse_rubric(json.loads(line).get("answer", ""))
            except RubricParseError:
                rejected += 1
        self.assertGreater(total, 0)
        self.assertEqual(rejected, total)


def _sixty_synthetic_payloads() -> list[dict]:
    """Sixty rows built from the five synthetic ones, in the real file's subject order.

    The selection rules are about indices and subjects, so they need a sixty-row
    population with twenty of each subject and nothing else about the real file. Building
    it from the fixture keeps the real text out of the tests entirely.
    """
    base = synthetic_payloads()
    by_subject = {
        subject: [payload for payload in base if payload["subject"] == subject]
        for subject in ("physics", "chemistry", "biology")
    }
    rows: list[dict] = []
    for subject in ("physics", "chemistry", "biology"):
        pool = by_subject[subject] or base
        for index in range(20):
            payload = dict(pool[index % len(pool)])
            payload["subject"] = subject
            rows.append(payload)
    return rows


def _write_manifest() -> str:
    """Rebuild ``tests/fixtures/fs_manifest.json`` from the pinned file on this machine."""
    rows = load_dataset(None)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["rows"] = len(rows)
    manifest["rubric_items"] = sum(row.rubric_items for row in rows)
    manifest["row_fingerprints"] = [
        {
            "key": row.key,
            "subject": row.subject,
            "problem_sha256": row.problem_sha256,
            "problem_chars": len(row.problem),
            "rubric_sha256": row.rubric_sha256,
            "rubric_chars": len(row.rubric),
            "rubric_items": row.rubric_items,
            "rubric_points_total": row.rubric_points_total,
            "duplicate_of": row.duplicate_of,
        }
        for row in rows
    ]
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return f"wrote {MANIFEST} for {len(rows)} rows"


if __name__ == "__main__":  # pragma: no cover - a maintenance entry point
    if "--manifest" in sys.argv:
        print(_write_manifest())
    else:
        unittest.main()
