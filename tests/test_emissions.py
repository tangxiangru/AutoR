"""An action that leaves the run is held until the stage that asked for it is approved.

The division these tests hold is between an *acquisition*, which installs a record the run
owns and can withdraw, and an *emission*, which puts data where other parties can read it
and no inverse takes back. :mod:`src.effects` can undo the first. The only thing that makes
the second recoverable is not having performed it yet.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.emissions import (
    STATUS_DISCARDED,
    STATUS_RELEASED,
    STATUS_WITHHELD,
    discard_from,
    load_emissions,
    pending,
    release,
    withhold,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout

STAGE_02, STAGE_04, STAGE_05, STAGE_08 = STAGES[1], STAGES[3], STAGES[4], STAGES[7]


class EmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)

    def test_a_registered_intent_is_withheld_and_nothing_says_otherwise(self) -> None:
        emission = withhold(self.paths, STAGE_08, "pull_request", "open a PR with the report")

        self.assertEqual(emission.status, STATUS_WITHHELD)
        self.assertTrue(emission.withheld)
        self.assertEqual([item.emission_id for item in pending(self.paths)], [emission.emission_id])

    def test_intents_survive_a_reload_from_disk(self) -> None:
        withhold(self.paths, STAGE_08, "quota", "spend the judge budget", {"calls": 40})

        reloaded = load_emissions(self.paths)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].payload["calls"], 40)

    def test_releasing_a_stage_settles_only_that_stage(self) -> None:
        withhold(self.paths, STAGE_04, "network", "fetch a corpus")
        withhold(self.paths, STAGE_08, "pull_request", "open a PR")

        released = release(self.paths, STAGE_08, "stage approved")

        self.assertEqual([item.stage for item in released], [STAGE_08.slug])
        self.assertEqual(released[0].status, STATUS_RELEASED)
        self.assertEqual([item.stage for item in pending(self.paths)], [STAGE_04.slug])

    def test_a_rollback_discards_the_range_and_leaves_earlier_intents_standing(self) -> None:
        withhold(self.paths, STAGE_02, "network", "fetch a corpus")
        withhold(self.paths, STAGE_05, "leaderboard", "post the score")

        discarded = discard_from(self.paths, STAGE_04, "rolled back")

        self.assertEqual([item.stage for item in discarded], [STAGE_05.slug])
        self.assertEqual(discarded[0].status, STATUS_DISCARDED)
        self.assertEqual([item.stage for item in pending(self.paths)], [STAGE_02.slug])

    def test_a_settled_intent_is_not_settled_twice(self) -> None:
        """The record of having released something must not be overwritten by a later
        rollback claiming it was discarded. It was performed; that is history now."""

        withhold(self.paths, STAGE_05, "leaderboard", "post the score")
        release(self.paths, STAGE_05)

        discard_from(self.paths, STAGE_04, "rolled back")

        self.assertEqual([item.status for item in load_emissions(self.paths)], [STATUS_RELEASED])

    def test_an_unclassified_kind_is_still_held(self) -> None:
        """Refusing it would push the caller back to emitting directly, which is the
        behaviour this module exists to replace."""

        emission = withhold(self.paths, STAGE_05, "carrier_pigeon", "send the draft")
        self.assertTrue(emission.withheld)
        self.assertEqual(len(pending(self.paths)), 1)


if __name__ == "__main__":
    unittest.main()
