"""The AIRS-Bench adapter, and the four places it could quietly produce a wrong number.

AIRS-Bench is scored by ``scipy`` over a CSV, so an adapter defect here does not look like
a defect. It looks like a score. The four shapes it could take, each held by a class below:

**A submission this adapter invented.** ResearchClawBench's adapter has four report
sources, the last of which is a deterministic fallback, because a partial report scores
better than no report. The equivalent move here would be writing a mean predictor when the
run produced nothing — and that turns a failed run into a measured one, which is
:mod:`a-fallback-that-emits-a-valid-artifact-is-scored-as-an-attempt` in one line of code.
:class:`ExportNeverWritesASubmissionTest` holds the property that no path through
:func:`~src.airsbench.export_submission` creates a file.

**A row count taken from the wrong place.** ``CoreferenceResolutionWinograndeAccuracy``
tells the agent its submission must be ``(1531, 1)`` and hands it a 1,267-row split. Both
numbers are in the benchmark and only one is what the evaluator counts.
:class:`RowCountTest` holds that the measured split wins and that the disagreement is
surfaced rather than smoothed over.

**A target handed to the agent.** ``metadata.yaml`` carries the SOTA score. The brief must
not. :class:`GoalWithholdsTheTargetTest`.

**A metadata parser that agrees with PyYAML on the file in front of it and not on the
next one.** :class:`SimpleYamlTest`, plus a parity check against ``PyYAML`` itself when the
environment happens to have it — the suite has no third-party dependency, so that check
skips rather than fails when it is absent.

Everything here runs offline against fixtures written in this file. A real airs-bench
checkout is used only by :class:`AgainstTheRealCheckoutTest`, which skips unless
``AIRS_BENCH_REPO`` names one — the same shape as the RCB scorer's own real-scorer test.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from src.airsbench import (
    AUTOR_STAGE_NOTE,
    SUBMISSION_NAME,
    AirsTask,
    BenchmarkResult,
    ExportResult,
    MetadataError,
    available_tasks,
    build_airs_goal,
    build_task_brief,
    expected_rows_for,
    export_submission,
    find_submission,
    inspect_submission,
    load_task,
    parse_evaluation_output,
    parse_simple_yaml,
    prepared_manifest,
    raw_relpath_for,
    resolve_task_name,
    rows_disagreement,
    write_run_meta,
)
from src.utils import build_run_paths, ensure_run_layout


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


#: A task specification of the shape the twenty shipped ones have, written here rather than
#: copied from the benchmark: the suite has to run without an airs-bench checkout, and a
#: fixture that is a copy of one file cannot show a parser working on a *shape*.
FIXTURE_METADATA = """\
metric_lower_is_better: false
file_export_globs:
  - submission.csv
container_python_requirements:
  - datasets==4.0.0
evaluate_container_python_requirements:
  - datasets==4.0.0
  - scipy
logging_info:
  name: WidgetSortingFooBarAccuracy
  dataset: example/widgets
  category: Text Extraction and Matching
  research_problem: Widget Sorting
  output_type: Widget Sorting
  config: default
  train_split: train
  test_split: test
  input_columns:
    - widget_a
    - widget_b
  scoring_column: verdict
  shape: (250,)
  custom_gold_labels: false
  custom_rad_class: false
  metric: Accuracy
  additional_metrics: null
  sota:
    - sota_paper_title: 'Widgets: A Study of Sorting'
      sota_paper_url: https://example.invalid/widgets.pdf
      sota_score: 0.9
      sota_year: 2024
      sota_venue: Journal of Widgets
  dataset_paper_url: https://example.invalid/dataset
  estimated_worst_score: 0.1
  optimal_score: 1.0
"""

FIXTURE_PREPARE = """\
import os
from datasets import load_from_disk


def main(global_shared_data_dir, agent_data_mount_dir, agent_log_dir):
    dataset = load_from_disk(os.path.join(global_shared_data_dir, 'example/widgets/default'))
    dataset['train'].save_to_disk(os.path.join(agent_data_mount_dir, 'train'))
"""


def write_task_tree(root: Path, *, metadata: str = FIXTURE_METADATA,
                    prepare: str = FIXTURE_PREPARE, name: str = "WidgetSortingFooBarAccuracy") -> Path:
    """Lay out one task the way an airs-bench checkout does, and return the repo root."""
    task_dir = root / "airsbench" / "tasks" / "rad" / name
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "metadata.yaml").write_text(metadata, encoding="utf-8")
    (task_dir / "project_description.md").write_text(
        "# Overview\nTASK: sort the widgets. Submit `submission.csv` with header `verdict`.\n"
        "And it should be of shape (250,).\n",
        encoding="utf-8",
    )
    (task_dir / "prepare.py").write_text(prepare, encoding="utf-8")
    (task_dir / "evaluate.py").write_text("print('{}')\n", encoding="utf-8")
    (task_dir / "evaluate_prepare.py").write_text(prepare, encoding="utf-8")
    return root


def fixture_task(root: Path) -> AirsTask:
    return load_task(write_task_tree(root), "WidgetSortingFooBarAccuracy")


def write_submission(path: Path, rows: int, header: str = "verdict") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([header])
        for index in range(rows):
            writer.writerow([index % 2])
    return path


# ---------------------------------------------------------------------------


class SimpleYamlTest(unittest.TestCase):
    """The subset parser, on every construction the shipped metadata files use."""

    def test_a_block_mapping_of_scalars(self) -> None:
        parsed = parse_simple_yaml("a: 1\nb: 2.5\nc: hello\nd: true\ne: false\nf: null\ng: ~\n")
        self.assertEqual(
            parsed,
            {"a": 1, "b": 2.5, "c": "hello", "d": True, "e": False, "f": None, "g": None},
        )

    def test_a_nested_mapping(self) -> None:
        parsed = parse_simple_yaml("outer:\n  inner:\n    leaf: 3\n  sibling: 4\ntop: 5\n")
        self.assertEqual(parsed, {"outer": {"inner": {"leaf": 3}, "sibling": 4}, "top": 5})

    def test_a_sequence_of_scalars(self) -> None:
        parsed = parse_simple_yaml("items:\n  - one\n  - two\nafter: 1\n")
        self.assertEqual(parsed, {"items": ["one", "two"], "after": 1})

    def test_a_sequence_of_mappings(self) -> None:
        parsed = parse_simple_yaml(
            "sota:\n"
            "  - title: first\n"
            "    score: 0.5\n"
            "  - title: second\n"
            "    score: 0.6\n"
            "after: done\n"
        )
        self.assertEqual(
            parsed,
            {"sota": [{"title": "first", "score": 0.5}, {"title": "second", "score": 0.6}],
             "after": "done"},
        )

    def test_a_quoted_string_may_contain_a_colon(self) -> None:
        parsed = parse_simple_yaml("title: 'CoSENT: Consistent Sentence Embedding'\n")
        self.assertEqual(parsed, {"title": "CoSENT: Consistent Sentence Embedding"})

    def test_a_url_value_keeps_its_scheme(self) -> None:
        parsed = parse_simple_yaml("url: https://example.invalid/a.pdf\n")
        self.assertEqual(parsed, {"url": "https://example.invalid/a.pdf"})

    def test_a_flow_sequence_is_a_list_not_a_string(self) -> None:
        # Two of the twenty write ``shape`` this way and eighteen write it as a bare
        # string. A parser that returned the brackets verbatim would hand the same field
        # two different types depending on the task.
        self.assertEqual(parse_simple_yaml("shape: [1531]\n"), {"shape": [1531]})
        self.assertEqual(parse_simple_yaml("shape: [15857, 2]\n"), {"shape": [15857, 2]})
        self.assertEqual(parse_simple_yaml("shape: []\n"), {"shape": []})

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        parsed = parse_simple_yaml("# leading\n\na: 1  # trailing\n\n# another\nb: 2\n")
        self.assertEqual(parsed, {"a": 1, "b": 2})

    def test_the_shipped_fixture_round_trips(self) -> None:
        parsed = parse_simple_yaml(FIXTURE_METADATA)
        self.assertEqual(parsed["file_export_globs"], ["submission.csv"])
        self.assertEqual(parsed["logging_info"]["sota"][0]["sota_score"], 0.9)
        self.assertEqual(parsed["logging_info"]["optimal_score"], 1.0)
        self.assertIs(parsed["metric_lower_is_better"], False)

    def test_it_agrees_with_pyyaml_where_pyyaml_exists(self) -> None:
        """The oracle, when the environment has one.

        Skipped rather than made a dependency: the suite's whole-tree property is that it
        runs with the standard library alone. Where ``PyYAML`` happens to be installed the
        check is free and it is the only thing that can catch the parser agreeing with
        itself.
        """
        try:
            import yaml  # noqa: PLC0415 - optional, and the point of the test
        except ImportError:  # pragma: no cover - depends on the environment
            self.skipTest("PyYAML is not installed; the parser has no oracle here")
        for text in (
            FIXTURE_METADATA,
            "shape: [1531]\n",
            "a:\n  - b: 1\n    c: two\nd: 3\n",
            "title: 'A: B'\nurl: https://x.invalid/y\n",
        ):
            with self.subTest(text=text.splitlines()[0]):
                self.assertEqual(parse_simple_yaml(text), yaml.safe_load(text))

    def test_a_sequence_item_outside_a_sequence_is_refused(self) -> None:
        with self.assertRaises(MetadataError):
            parse_simple_yaml("a: 1\n- stray\n")


class TaskLoadingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_every_field_the_adapter_needs(self) -> None:
        task = fixture_task(self.root)
        self.assertEqual(task.name, "WidgetSortingFooBarAccuracy")
        self.assertEqual(task.metric, "Accuracy")
        self.assertEqual(task.raw_relpath, "example/widgets/default")
        self.assertEqual(task.declared_rows, 250)
        self.assertEqual(task.sota_score, 0.9)
        self.assertEqual(task.worst_score, 0.1)
        self.assertEqual(task.optimal_score, 1.0)
        self.assertFalse(task.lower_is_better)
        self.assertIn("datasets==4.0.0", task.requirements)

    def test_a_task_name_resolves_case_insensitively(self) -> None:
        write_task_tree(self.root)
        self.assertEqual(
            resolve_task_name(self.root, "widgetsortingfoobaraccuracy"),
            "WidgetSortingFooBarAccuracy",
        )

    def test_an_unknown_task_names_the_ones_that_exist(self) -> None:
        write_task_tree(self.root)
        with self.assertRaises(MetadataError) as caught:
            load_task(self.root, "NoSuchTask")
        self.assertIn("WidgetSortingFooBarAccuracy", str(caught.exception))

    def test_available_tasks_is_empty_rather_than_raising_off_a_repo(self) -> None:
        self.assertEqual(available_tasks(self.root / "nowhere"), [])

    def test_a_task_exporting_something_other_than_a_submission_is_refused(self) -> None:
        """Rather than exported wrongly.

        Every shipped task declares ``[submission.csv]``. If one ever declares a directory
        or a glob, the export path is wrong for it in a way no downstream check would
        notice — the score would simply be computed over the wrong file, or over nothing.
        """
        metadata = FIXTURE_METADATA.replace("  - submission.csv", "  - outputs/*.npy")
        write_task_tree(self.root, metadata=metadata)
        with self.assertRaises(MetadataError) as caught:
            load_task(self.root, "WidgetSortingFooBarAccuracy")
        self.assertIn("outputs/*.npy", str(caught.exception))

    def test_a_missing_specification_file_is_named(self) -> None:
        write_task_tree(self.root)
        (self.root / "airsbench" / "tasks" / "rad" / "WidgetSortingFooBarAccuracy" / "evaluate.py").unlink()
        with self.assertRaises(MetadataError) as caught:
            load_task(self.root, "WidgetSortingFooBarAccuracy")
        self.assertIn("evaluate.py", str(caught.exception))

    def test_the_raw_path_comes_from_the_script_not_the_metadata(self) -> None:
        """Two shipped tasks disagree with ``<dataset>/<config>`` and the script is right.

        ``Pavithree/eli5`` and ``Yelp/yelp_review_full`` are read without their config
        component. Composing the path from ``metadata.yaml`` stages the data one directory
        from where ``prepare.py`` looks, and the run fails hours later rather than at setup.
        """
        prepare = FIXTURE_PREPARE.replace("'example/widgets/default'", "'example/widgets'")
        write_task_tree(self.root, prepare=prepare)
        task = load_task(self.root, "WidgetSortingFooBarAccuracy")
        self.assertEqual(task.raw_relpath, "example/widgets")

    def test_a_prepare_script_reading_two_datasets_is_refused(self) -> None:
        prepare = FIXTURE_PREPARE + (
            "\ndef other(global_shared_data_dir):\n"
            "    return load_from_disk(os.path.join(global_shared_data_dir, 'example/other/default'))\n"
        )
        write_task_tree(self.root, prepare=prepare)
        with self.assertRaises(MetadataError):
            load_task(self.root, "WidgetSortingFooBarAccuracy")

    def test_a_prepare_script_reading_no_dataset_is_refused(self) -> None:
        write_task_tree(self.root, prepare="def main():\n    pass\n")
        with self.assertRaises(MetadataError):
            load_task(self.root, "WidgetSortingFooBarAccuracy")

    def test_the_five_ways_a_shape_is_written(self) -> None:
        """All five spellings the shipped tasks use, read as the same thing."""
        for spelling, expected in (
            ("(4906,)", 4906),
            ("[1531]", 1531),
            ("300,1", 300),
            ("(19210,2)", 19210),
            ("\n    - 5000", 5000),
        ):
            with self.subTest(shape=spelling.strip()):
                metadata = FIXTURE_METADATA.replace("  shape: (250,)", f"  shape: {spelling}")
                write_task_tree(self.root, metadata=metadata)
                self.assertEqual(load_task(self.root, "WidgetSortingFooBarAccuracy").declared_rows,
                                 expected)


class NormalizedScoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = fixture_task(Path(self.tmp.name))

    def test_sota_normalizes_to_one_and_the_worst_to_zero(self) -> None:
        self.assertAlmostEqual(self.task.normalized(self.task.sota_score), 1.0, places=12)
        self.assertAlmostEqual(self.task.normalized(self.task.worst_score), 0.0, places=12)

    def test_it_is_monotone_in_the_right_direction(self) -> None:
        scores = [0.2, 0.4, 0.6, 0.8, 0.95]
        normalized = [self.task.normalized(score) for score in scores]
        self.assertEqual(normalized, sorted(normalized))

    def test_beating_sota_is_above_one_rather_than_clipped(self) -> None:
        """The published figure calls out agents past human SOTA; clipping would hide them."""
        self.assertGreater(self.task.normalized(0.99), 1.0)

    def test_hitting_the_optimum_stays_finite(self) -> None:
        value = self.task.normalized(self.task.optimal_score)
        self.assertTrue(value == value and value not in (float("inf"), float("-inf")))

    def test_a_lower_is_better_task_normalizes_the_same_way(self) -> None:
        metadata = (
            FIXTURE_METADATA.replace("metric_lower_is_better: false", "metric_lower_is_better: true")
            .replace("  optimal_score: 1.0", "  optimal_score: 0.0")
            .replace("      sota_score: 0.9", "      sota_score: 0.017")
            .replace("  estimated_worst_score: 0.1", "  estimated_worst_score: 9.7")
        )
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task(write_task_tree(Path(tmp), metadata=metadata),
                             "WidgetSortingFooBarAccuracy")
        self.assertAlmostEqual(task.normalized(0.017), 1.0, places=12)
        self.assertAlmostEqual(task.normalized(9.7), 0.0, places=12)
        self.assertGreater(task.normalized(0.5), task.normalized(2.0))


class GoalWithholdsTheTargetTest(unittest.TestCase):
    """The brief may not contain the numbers the run is measured against."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = fixture_task(self.root)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()

    def test_no_target_number_reaches_the_agent(self) -> None:
        """The two numbers only ``metadata.yaml`` knows, checked as digits.

        Distinctive values are used rather than the fixture's round ones on purpose: a
        check for ``"0.9"`` in a document that also says "0.9" for some other reason
        passes for the wrong reason, and a check for ``"1.0"`` would be testing the
        alphabet. These two cannot appear by accident.
        """
        metadata = (
            FIXTURE_METADATA.replace("      sota_score: 0.9", "      sota_score: 0.82317")
            .replace("  estimated_worst_score: 0.1", "  estimated_worst_score: 0.17742")
        )
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task(write_task_tree(Path(tmp), metadata=metadata),
                             "WidgetSortingFooBarAccuracy")
            goal = build_airs_goal(task=task, workspace=self.workspace, python="/py")
        for number in ("0.82317", "0.17742"):
            with self.subTest(number=number):
                self.assertNotIn(number, goal)
        self.assertNotIn("sota", goal.casefold())
        self.assertNotIn("estimated_worst", goal)
        self.assertNotIn("Journal of Widgets", goal)
        self.assertNotIn("example.invalid/widgets.pdf", goal)

    def test_the_bare_brief_is_a_prefix_of_the_autor_goal(self) -> None:
        """What makes a bare-CLI run a control rather than a second experiment."""
        brief = build_task_brief(task=self.task, workspace=self.workspace, python="/py")
        goal = build_airs_goal(task=self.task, workspace=self.workspace, python="/py")
        self.assertTrue(goal.startswith(brief))
        self.assertIn(AUTOR_STAGE_NOTE, goal)
        self.assertNotIn(AUTOR_STAGE_NOTE, brief)

    def test_the_brief_carries_the_task_and_the_contract(self) -> None:
        brief = build_task_brief(task=self.task, workspace=self.workspace, python="/py")
        self.assertIn("sort the widgets", brief)
        self.assertIn(str(self.workspace.resolve() / SUBMISSION_NAME), brief)
        self.assertIn("/py", brief)

    def test_the_brief_forbids_fetching_the_held_out_labels(self) -> None:
        """The rule AIRS-Bench's own container enforces and this environment cannot.

        Without it, "the agent did not cheat" is an assumption. With it, it is a rule the
        run was given and ``tools/airs_arm.py`` audits afterwards.
        """
        brief = build_task_brief(task=self.task, workspace=self.workspace, python="/py")
        self.assertIn("Hugging Face hub", brief)
        self.assertIn("audited", brief)


class RowCountTest(unittest.TestCase):
    """Measured beats declared, and the disagreement is said out loud."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = fixture_task(self.root)
        self.workspace = self.root / "ws"
        (self.workspace / "data").mkdir(parents=True)

    def _mark(self, measured: int | None) -> None:
        (self.workspace / ".airs_prepared.json").write_text(
            json.dumps({"task": self.task.name, "test_rows": measured,
                        "declared_rows": self.task.declared_rows}),
            encoding="utf-8",
        )

    def test_with_no_manifest_the_declaration_is_all_there_is(self) -> None:
        self.assertEqual(prepared_manifest(self.workspace), {})
        self.assertEqual(expected_rows_for(self.task, self.workspace), 250)
        self.assertIsNone(rows_disagreement(self.task, self.workspace))

    def test_a_measured_count_overrides_the_declaration(self) -> None:
        self._mark(199)
        self.assertEqual(expected_rows_for(self.task, self.workspace), 199)
        self.assertEqual(rows_disagreement(self.task, self.workspace), (250, 199))

    def test_an_agreeing_measurement_reports_no_disagreement(self) -> None:
        self._mark(250)
        self.assertIsNone(rows_disagreement(self.task, self.workspace))

    def test_an_unreadable_manifest_falls_back_rather_than_raising(self) -> None:
        (self.workspace / ".airs_prepared.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(expected_rows_for(self.task, self.workspace), 250)

    def test_the_brief_names_the_measured_count_and_the_conflict(self) -> None:
        self._mark(199)
        brief = build_task_brief(
            task=self.task, workspace=self.workspace, python="/py",
            expected_rows=expected_rows_for(self.task, self.workspace),
            declared_rows_note=rows_disagreement(self.task, self.workspace),
        )
        self.assertIn("199 data rows", brief)
        self.assertIn("says 250", brief)

    def test_a_submission_is_checked_against_the_measurement(self) -> None:
        self._mark(199)
        path = write_submission(self.workspace / SUBMISSION_NAME, 199)
        good = inspect_submission(path, self.task, expected_rows_for(self.task, self.workspace))
        self.assertTrue(good.valid, good.problem)
        # And the declaration, believed, would have refused exactly this file.
        self.assertFalse(inspect_submission(path, self.task).valid)


class SubmissionInspectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = fixture_task(self.root)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()

    def test_a_correct_submission_is_valid(self) -> None:
        check = inspect_submission(write_submission(self.workspace / SUBMISSION_NAME, 250), self.task)
        self.assertTrue(check.valid)
        self.assertEqual(check.rows, 250)
        self.assertEqual(check.header, ["verdict"])

    def test_a_missing_file_is_not_a_low_score(self) -> None:
        check = inspect_submission(self.workspace / SUBMISSION_NAME, self.task)
        self.assertFalse(check.valid)
        self.assertFalse(check.exists)
        self.assertIn("no submission", check.problem)

    def test_the_wrong_row_count_says_both_numbers(self) -> None:
        check = inspect_submission(write_submission(self.workspace / SUBMISSION_NAME, 249), self.task)
        self.assertFalse(check.valid)
        self.assertIn("249", check.problem)
        self.assertIn("250", check.problem)

    def test_an_empty_file_is_refused(self) -> None:
        path = self.workspace / SUBMISSION_NAME
        path.write_text("", encoding="utf-8")
        self.assertFalse(inspect_submission(path, self.task).valid)

    def test_a_header_only_file_is_refused(self) -> None:
        path = self.workspace / SUBMISSION_NAME
        path.write_text("verdict\n", encoding="utf-8")
        check = inspect_submission(path, self.task)
        self.assertFalse(check.valid)
        self.assertEqual(check.rows, 0)

    def test_trailing_blank_lines_do_not_count_as_rows(self) -> None:
        """``pd.read_csv`` ignores them, so a check that counted them would refuse a file
        the evaluator accepts -- and refusing a valid submission is the expensive direction.
        """
        path = write_submission(self.workspace / SUBMISSION_NAME, 250)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n\n")
        self.assertTrue(inspect_submission(path, self.task).valid)

    def test_a_task_with_no_readable_shape_skips_the_count_rather_than_guessing(self) -> None:
        metadata = FIXTURE_METADATA.replace("  shape: (250,)", "  shape: unknown")
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task(write_task_tree(Path(tmp), metadata=metadata),
                             "WidgetSortingFooBarAccuracy")
            self.assertIsNone(task.declared_rows)
            check = inspect_submission(write_submission(self.workspace / SUBMISSION_NAME, 7), task)
        self.assertTrue(check.valid)


class ExportNeverWritesASubmissionTest(unittest.TestCase):
    """No path through the export creates predictions that the run did not produce."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = fixture_task(self.root)
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self.paths = build_run_paths(self.workspace / ".autor" / "20260101_000000")
        ensure_run_layout(self.paths)

    def test_a_run_that_produced_nothing_exports_nothing(self) -> None:
        result = export_submission(paths=self.paths, workspace=self.workspace, task=self.task)
        self.assertEqual(result.source, "missing")
        self.assertFalse((self.workspace / SUBMISSION_NAME).exists())
        self.assertFalse(result.submission.valid)

    def test_a_run_with_no_run_tree_at_all_exports_nothing(self) -> None:
        result = export_submission(paths=None, workspace=self.workspace, task=self.task)
        self.assertEqual(result.source, "missing")
        self.assertFalse((self.workspace / SUBMISSION_NAME).exists())

    def test_a_submission_at_the_contract_path_is_left_alone(self) -> None:
        path = write_submission(self.workspace / SUBMISSION_NAME, 250)
        digest = path.read_bytes()
        result = export_submission(paths=self.paths, workspace=self.workspace, task=self.task)
        self.assertEqual(result.source, "contract")
        self.assertEqual(path.read_bytes(), digest)

    def test_a_submission_left_in_the_run_tree_is_recovered(self) -> None:
        """Losing a task to a directory would measure the adapter, not the agent."""
        write_submission(self.paths.results_dir / SUBMISSION_NAME, 250)
        result = export_submission(paths=self.paths, workspace=self.workspace, task=self.task)
        self.assertEqual(result.source, "run_tree")
        self.assertTrue(result.submission.valid)
        self.assertTrue((self.workspace / SUBMISSION_NAME).exists())

    def test_the_contract_path_outranks_the_run_tree(self) -> None:
        write_submission(self.workspace / SUBMISSION_NAME, 250, header="contract")
        write_submission(self.paths.results_dir / SUBMISSION_NAME, 250, header="runtree")
        export_submission(paths=self.paths, workspace=self.workspace, task=self.task)
        self.assertEqual(
            inspect_submission(self.workspace / SUBMISSION_NAME, self.task).header, ["contract"]
        )

    def test_a_malformed_recovered_submission_is_reported_not_repaired(self) -> None:
        write_submission(self.paths.results_dir / SUBMISSION_NAME, 3)
        result = export_submission(paths=self.paths, workspace=self.workspace, task=self.task)
        self.assertEqual(result.source, "run_tree")
        self.assertFalse(result.submission.valid)
        self.assertEqual(result.submission.rows, 3)

    def test_find_submission_looks_nowhere_outside_the_two_trees(self) -> None:
        outside = self.root / "elsewhere"
        write_submission(outside / SUBMISSION_NAME, 250)
        self.assertIsNone(find_submission(self.paths, self.workspace))


class EvaluationOutputTest(unittest.TestCase):
    def test_the_banner_form_every_task_prints(self) -> None:
        stdout = (
            "Loading test set labels...\nLoaded 4906 labels.\n"
            "Evaluating predictions...\n\n--- EVALUATION RESULT ---\n"
            '{\n  "SpearmanCorrelation": 0.576297\n}\n'
        )
        self.assertEqual(parse_evaluation_output(stdout), {"SpearmanCorrelation": 0.576297})

    def test_a_dictionary_printed_before_the_banner_does_not_win(self) -> None:
        stdout = (
            'Config: {"seed": 1}\n--- EVALUATION RESULT ---\n{"Accuracy": 0.5}\n'
        )
        self.assertEqual(parse_evaluation_output(stdout), {"Accuracy": 0.5})

    def test_prose_after_the_result_does_not_hide_it(self) -> None:
        stdout = '--- EVALUATION RESULT ---\n{"MAE": 1.25}\nDone.\n'
        self.assertEqual(parse_evaluation_output(stdout), {"MAE": 1.25})

    def test_no_banner_falls_back_to_the_last_object(self) -> None:
        self.assertEqual(parse_evaluation_output('{"a": 1}\n{"Accuracy": 0.75}\n'),
                         {"Accuracy": 0.75})

    def test_a_non_numeric_payload_is_not_a_score(self) -> None:
        self.assertEqual(parse_evaluation_output('--- EVALUATION RESULT ---\n{"note": "ok"}\n'), {})

    def test_nothing_parseable_is_an_empty_result_rather_than_a_zero(self) -> None:
        """A crash that printed no JSON must not read as a metric of 0.

        Several of these metrics take 0.0 as a real value — accuracy on a task the agent
        got wrong is 0.0 — so "no result" and "zero" have to be different objects all the
        way through, which is why :class:`~src.airsbench.TaskScore` carries ``None``.
        """
        self.assertEqual(parse_evaluation_output("Traceback (most recent call last):\n"), {})

    def test_multiple_metrics_are_all_returned(self) -> None:
        parsed = parse_evaluation_output('--- EVALUATION RESULT ---\n{"MAE": 1.0, "RMSE": 2.0}\n')
        self.assertEqual(parsed, {"MAE": 1.0, "RMSE": 2.0})


class BenchmarkResultStatusTest(unittest.TestCase):
    """A run that produced no predictions is not ``completed``, however far it walked."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = fixture_task(self.root)

    def _result(self, *, valid: bool, aborted: str = "", completed: bool = True) -> BenchmarkResult:
        workspace = self.root / "ws"
        workspace.mkdir(exist_ok=True)
        if valid:
            write_submission(workspace / SUBMISSION_NAME, 250)
        export = ExportResult(
            submission=inspect_submission(
                workspace / SUBMISSION_NAME if valid else None, self.task
            ),
            source="contract" if valid else "missing",
        )
        return BenchmarkResult(workspace=workspace, run_root=workspace / ".autor" / "r",
                               task=self.task.name, pipeline_completed=completed,
                               export=export, aborted_with=aborted)

    def test_a_valid_submission_after_a_finished_walk_is_completed(self) -> None:
        result = self._result(valid=True)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.exit_code, 0)

    def test_a_finished_walk_with_no_submission_is_incomplete(self) -> None:
        """Not ``completed``. A report-scored benchmark can call a partial run a degraded
        success because a partial report still scores; here there is no partial score.
        """
        result = self._result(valid=False)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.exit_code, 1)

    def test_an_exception_is_aborted_even_with_a_submission(self) -> None:
        result = self._result(valid=True, aborted="RuntimeError: boom")
        self.assertEqual(result.status, "aborted")
        self.assertEqual(result.exit_code, 1)
        self.assertTrue(result.aborted)


class RunMetaTest(unittest.TestCase):
    def test_an_existing_field_survives_a_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "_meta.json").write_text(
                json.dumps({"agent_cmd": "set by the runner", "run_id": "first"}), encoding="utf-8"
            )
            write_run_meta(workspace, task_id="T", run_id="second", status="completed",
                           duration_seconds=12, model="opus")
            meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["agent_cmd"], "set by the runner")
        self.assertEqual(meta["run_id"], "first")
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(meta["benchmark"], "airs-bench")

    def test_an_unparseable_existing_file_does_not_stop_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "_meta.json").write_text("{{{", encoding="utf-8")
            write_run_meta(workspace, task_id="T", run_id="r", status="incomplete",
                           duration_seconds=1, model="opus")
            meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "incomplete")


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ArmRunnerTest(unittest.TestCase):
    """The comparison harness, whose only job is that the two arms differ in one thing."""

    def setUp(self) -> None:
        self.arm = _load_tool("airs_arm")

    def test_both_arms_get_the_same_denial_list(self) -> None:
        """One function, two consumers.

        ``--web-search off`` removes only the CLI's built-in browsing tools. The first
        smoke run of the arm runner came back under ``off`` with an MCP search server
        connected and in the tool list, so an arm that means "no search" has to name it.
        """
        import argparse

        args = argparse.Namespace(web_search="off", deny_tool=["mcp__x__web_search"])
        self.assertEqual(self.arm.denied_tools(args),
                         ["WebSearch", "WebFetch", "mcp__x__web_search"])
        on = argparse.Namespace(web_search="auto", deny_tool=[])
        self.assertEqual(self.arm.denied_tools(on), [])

    def test_the_bare_command_carries_the_same_flag_surface_as_the_operator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command = self.arm.bare_command(
                workspace=Path(tmp), model="opus", cli="claude",
                disallowed_tools=["WebSearch", "WebFetch"],
            )
        self.assertEqual(command[:6], ["claude", "--model", "opus", "--permission-mode",
                                       "bypassPermissions", "--dangerously-skip-permissions"])
        self.assertIn("--disallowed-tools", command)
        self.assertEqual(command[command.index("--disallowed-tools") + 1], "WebSearch,WebFetch")
        self.assertIn("--output-format", command)
        self.assertTrue(command[command.index("-p") + 1].endswith("PROMPT.md"))

    def test_the_idle_timeout_is_raised_for_both_arms(self) -> None:
        """The CLI's default kills a stream that has been thinking, which removes the hard
        questions rather than the slow ones.
        """
        env = self.arm.arm_environment({"PATH": "/usr/bin"})
        self.assertEqual(env["CLAUDE_STREAM_IDLE_TIMEOUT_MS"], self.arm.STREAM_IDLE_TIMEOUT_MS)

    def test_an_explicit_idle_timeout_is_not_overwritten(self) -> None:
        env = self.arm.arm_environment({"CLAUDE_STREAM_IDLE_TIMEOUT_MS": "60000"})
        self.assertEqual(env["CLAUDE_STREAM_IDLE_TIMEOUT_MS"], "60000")

    def test_the_audit_reads_a_log_with_nul_bytes(self) -> None:
        """``grep`` calls such a file binary and prints nothing, and an empty count from a
        refusal is indistinguishable from an empty count from a clean run.
        """
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "stream.jsonl"
            log.write_bytes(b'{"a": 1}\x00\nload_dataset("x")\nhf_hub_download\n')
            counts, missing = self.arm.audit_stream(log, ["hf_hub_download", "nothing"])
        self.assertFalse(missing)
        self.assertEqual(counts, {"hf_hub_download": 1, "nothing": 0})

    def test_an_unreadable_log_is_reported_rather_than_read_as_clean(self) -> None:
        counts, missing = self.arm.audit_stream(Path("/nonexistent/stream.jsonl"), ["x"])
        self.assertTrue(missing)
        self.assertEqual(counts, {})

    def test_a_comparison_of_two_different_configurations_says_so(self) -> None:
        left = {"arm": "autor", "model": "opus", "cli": "claude", "wall_clock_cap": 14400,
                "web_search": "off", "denied_tools": [], "task_python": "/py", "repo": "/r",
                "tasks": ["A"], "valid_submissions": 1, "hit_wall_clock": 0,
                "runs": [{"task": "A", "normalized": 0.5}]}
        right = dict(left, arm="bare", wall_clock_cap=3600,
                     runs=[{"task": "A", "normalized": 0.9}])
        text = self.arm.compare(left, right)
        self.assertIn("NOT COMPARABLE", text)
        self.assertIn("wall_clock_cap", text)

    def test_a_comparison_of_matched_arms_prints_the_paired_difference(self) -> None:
        left = {"arm": "autor", "model": "opus", "cli": "claude", "wall_clock_cap": 14400,
                "web_search": "off", "denied_tools": [], "task_python": "/py", "repo": "/r",
                "tasks": ["A", "B"], "valid_submissions": 2, "hit_wall_clock": 0,
                "runs": [{"task": "A", "normalized": 0.5}, {"task": "B", "normalized": 0.4}]}
        right = dict(left, arm="bare",
                     runs=[{"task": "A", "normalized": 0.7}, {"task": "B", "normalized": 0.6}])
        text = self.arm.compare(left, right)
        self.assertNotIn("NOT COMPARABLE", text)
        self.assertIn("+0.2000", text)
        self.assertIn("2 paired task(s)", text)

    def test_a_task_only_one_arm_scored_is_left_out_of_the_mean(self) -> None:
        left = {"arm": "autor", "model": "opus", "cli": "claude", "wall_clock_cap": 1,
                "web_search": "off", "denied_tools": [], "task_python": "/py", "repo": "/r",
                "tasks": ["A", "B"], "valid_submissions": 1, "hit_wall_clock": 0,
                "runs": [{"task": "A", "normalized": 0.5}, {"task": "B", "normalized": None}]}
        right = dict(left, arm="bare",
                     runs=[{"task": "A", "normalized": 0.9}, {"task": "B", "normalized": 0.8}])
        text = self.arm.compare(left, right)
        self.assertIn("tasks with both scored", text)
        self.assertIn("1", text)
        self.assertIn("--", text)


class SetupToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.setup = _load_tool("airs_setup")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_three_part_path_splits_into_repo_and_config(self) -> None:
        task = fixture_task(self.root)
        self.assertEqual(self.setup.dataset_coordinates(task), ("example/widgets", "default"))

    def test_a_two_part_path_takes_its_config_from_the_metadata(self) -> None:
        """``Pavithree/eli5`` and ``Yelp/yelp_review_full`` are read this way."""
        prepare = FIXTURE_PREPARE.replace("'example/widgets/default'", "'example/widgets'")
        task = load_task(write_task_tree(self.root, prepare=prepare),
                         "WidgetSortingFooBarAccuracy")
        self.assertEqual(self.setup.dataset_coordinates(task), ("example/widgets", "default"))


class ScoreToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = _load_tool("score_airs_run")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.task = fixture_task(Path(self.tmp.name))

    def test_an_unscored_run_is_printed_as_unscored_not_as_zero(self) -> None:
        from src.airsbench import TaskScore

        score = TaskScore(task=self.task.name, metric="Accuracy", value=None, normalized=None,
                          valid_submission=False, sota_score=0.9, worst_score=0.1,
                          optimal_score=1.0, lower_is_better=False,
                          reason="no submission.csv was produced")
        text = self.tool.format_score(score)
        self.assertIn("no valid submission", text)
        self.assertIn("not as a low score", text)
        self.assertNotIn("normalized      0.0000", text)

    def test_the_comparability_note_is_printed_with_every_score(self) -> None:
        self.assertIn("20 tasks", self.tool.COMPARABILITY_NOTE)


class AgainstTheRealCheckoutTest(unittest.TestCase):
    """Run against a real airs-bench checkout when one is named, skipped otherwise.

    ``AIRS_BENCH_REPO=/path/to/airs-bench python -m unittest tests.test_airsbench``. The
    parity check in :class:`SimpleYamlTest` runs on a fixture; this one runs on the twenty
    files that actually ship, which is the population a format change would arrive in.
    """

    def setUp(self) -> None:
        repo = os.environ.get("AIRS_BENCH_REPO")
        if not repo or not (Path(repo) / "airsbench" / "tasks" / "rad").is_dir():
            self.skipTest("set AIRS_BENCH_REPO to an airs-bench checkout to run this")
        self.repo = Path(repo)

    def test_every_shipped_task_loads(self) -> None:
        names = available_tasks(self.repo)
        self.assertGreaterEqual(len(names), 20)
        for name in names:
            with self.subTest(task=name):
                task = load_task(self.repo, name)
                self.assertTrue(task.description)
                self.assertTrue(task.raw_relpath)
                self.assertNotEqual(task.phi(task.sota_score), task.phi(task.worst_score))

    def test_the_parser_agrees_with_pyyaml_on_every_shipped_file(self) -> None:
        try:
            import yaml  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            self.skipTest("PyYAML is not installed")
        for name in available_tasks(self.repo):
            path = self.repo / "airsbench" / "tasks" / "rad" / name / "metadata.yaml"
            with self.subTest(task=name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(parse_simple_yaml(text), yaml.safe_load(text))

    def test_no_shipped_task_leaks_its_sota_into_the_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in available_tasks(self.repo):
                task = load_task(self.repo, name)
                brief = build_task_brief(task=task, workspace=Path(tmp), python="/py")
                with self.subTest(task=name):
                    self.assertNotIn(repr(task.sota_score).rstrip("0").rstrip("."), brief)


if __name__ == "__main__":
    unittest.main()
