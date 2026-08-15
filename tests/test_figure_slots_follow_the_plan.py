"""Which five figures reach the judge, when the report names none of them.

ResearchClawBench shows the judge at most `MAX_REPORT_FIGURES` images and scores ~61% of the
benchmark's weight against them. When the report references its figures, `collect_figures` publishes
those and this branch never runs. When it references none -- a synthesized or assembled
report -- the slots were filled in `_figure_candidates` order, which resolves to filename
order. One benchmark run reached that branch holding 426 candidate PNGs, so five were
published because their names sorted first.

The run already ranks its figures: `report_plan.json` commits each slot to a filename and
the claim it settles, written before any of the results existed. It is the only ranking in
the run that means anything, and the export ignored it.

Rare, and worth fixing anyway: measured over 40 scored runs the unreferenced branch decided
the slots exactly once. Choosing five of 426 by filename is wrong at any frequency, and the
fix cannot make a run worse -- with no plan the order is unchanged.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.rcb import collect_figures, ensure_workspace_layout
from src.utils import MAX_REPORT_FIGURES, build_run_paths, ensure_run_layout


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "0557bfabd40000000049454e44ae426082"
)


class PlannedRankTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.paths = build_run_paths(root / "run_0001")
        ensure_run_layout(self.paths)
        self.workspace = root / "ws"
        ensure_workspace_layout(self.workspace)

    def _filler(self, extra: int = 2) -> list[str]:
        """Enough figures to contest the slots, whatever the ceiling is.

        These tests used to hardcode six names against a ceiling of five. That pinned the
        constant rather than the behaviour, so raising the ceiling to match the benchmark's
        own `generated_images[:15]` broke six tests that were not about the ceiling at all.
        """
        return [f"f{i:03d}.png" for i in range(MAX_REPORT_FIGURES + extra)]

    def _figures(self, *names: str) -> None:
        self.paths.figures_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (self.paths.figures_dir / name).write_bytes(PNG)

    def _plan(self, *filenames: str, dropped: tuple[str, ...] = ()) -> None:
        figures = [
            {
                "slot": index,
                "filename": name,
                "supports": [f"H{index}"],
                "shows": f"claim {index}",
                "if_supported": "a",
                "if_refuted": "b",
                "source_artifact": f"outputs/{index}.json",
                "dropped_because": "superseded" if name in dropped else "",
            }
            for index, name in enumerate(filenames, start=1)
        ]
        self.paths.report_plan.parent.mkdir(parents=True, exist_ok=True)
        self.paths.report_plan.write_text(
            json.dumps({"declared_at": "2026-08-11T00:00:00", "digest": "d",
                        "no_figures_because": "", "task_outputs": [], "figures": figures}),
            encoding="utf-8",
        )

    def _publish(self) -> list[str]:
        return collect_figures(self.paths, self.workspace, report_text="")

    def test_the_plans_top_five_win_over_the_alphabet(self) -> None:
        """The exact failure: a main-result figure whose name sorts last is dropped."""
        filler = self._filler()
        self._figures(*filler, "zz_main_result.png")
        planned = ["zz_main_result.png", *filler[-(MAX_REPORT_FIGURES - 1):]]
        self._plan(*planned)
        # collect_figures returns a sorted listing of what it published, so membership is the
        # assertion: the ranking decides which survive, not what order they appear in.
        self.assertEqual(set(self._publish()), set(planned))

    def test_the_planned_figure_is_not_pruned_off_disk(self) -> None:
        """Losing the slot also deleted the file: the prune enforces the budget on disk."""
        filler = self._filler()
        self._figures(*filler, "zz_main_result.png")
        self._plan("zz_main_result.png", *filler[-(MAX_REPORT_FIGURES - 1):])
        self._publish()
        self.assertTrue((self.workspace / "report" / "images" / "zz_main_result.png").exists())

    def test_a_run_with_no_plan_is_unchanged(self) -> None:
        """The fix cannot make a run worse than it was."""
        filler = self._filler()
        self._figures(*filler)
        self.assertEqual(self._publish(), sorted(filler)[:MAX_REPORT_FIGURES])

    def test_an_unreadable_plan_is_unchanged(self) -> None:
        filler = self._filler()
        self._figures(*filler)
        self.paths.report_plan.parent.mkdir(parents=True, exist_ok=True)
        self.paths.report_plan.write_text("{not json", encoding="utf-8")
        self.assertEqual(self._publish(), sorted(filler)[:MAX_REPORT_FIGURES])

    def test_unplanned_figures_fill_the_slots_a_thin_plan_leaves(self) -> None:
        """A run whose plan names two figures must still publish five."""
        filler = self._filler()
        self._figures(*filler, "zz_main.png")
        self._plan("zz_main.png", filler[-1])
        published = self._publish()
        self.assertEqual(len(published), MAX_REPORT_FIGURES)
        # Both planned figures survive; the remaining three slots go to unplanned ones. The
        # sentinel has to sit above every real slot or the plan's *last* figure ties with
        # the unplanned pool and loses the tie to the alphabet.
        self.assertIn("zz_main.png", published)
        self.assertIn(filler[-1], published)

    def test_a_dropped_slot_is_not_reinstated_at_export(self) -> None:
        """`dropped_because` records a decision; ranking it last would quietly undo it."""
        # A dropped slot must not be reinstated, and with a ceiling that can exceed the
        # candidate pool it must also not simply arrive as an unplanned filler -- so the pool
        # is kept larger than the ceiling.
        filler = self._filler(extra=3)
        self._figures(*filler, "zz_dropped.png")
        self._plan("zz_dropped.png", filler[-1], dropped=("zz_dropped.png",))
        published = self._publish()
        self.assertIn(filler[-1], published)
        self.assertNotIn("zz_dropped.png", published)

    def test_the_plan_wins_on_a_case_mismatch(self) -> None:
        """The plan names an intended file; the code that drew it chose the real name."""
        self._figures(*self._filler(), "Zz_Main_Result.png")
        self._plan("zz_main_result.PNG", "e.png")
        self.assertIn("Zz_Main_Result.png", self._publish())

    def test_a_plan_naming_files_that_do_not_exist_changes_nothing(self) -> None:
        filler = self._filler()
        self._figures(*filler)
        self._plan("never_drawn.png", "also_missing.png")
        self.assertEqual(self._publish(), sorted(filler)[:MAX_REPORT_FIGURES])

    def test_a_referenced_report_still_outranks_the_plan(self) -> None:
        """The report saying which figures it argues with is better evidence than a plan."""
        self._figures(*self._filler(), "zz_main.png", "b.png", "c.png")
        self._plan("zz_main.png")
        published = collect_figures(
            self.paths, self.workspace, report_text="![one](images/b.png)\n![two](images/c.png)"
        )
        self.assertEqual(published, ["b.png", "c.png"])


if __name__ == "__main__":
    unittest.main()
