"""Deleting both copies and re-freezing was still the reset, and three docs said it was not.

#203 added a stamp outside `workspace/` and closed "delete `preregistration.json` and
re-freeze". Review of that branch demonstrated the next `rm`:

    rm runs/<id>/preregistration_stamp.json
    rm workspace/notes/preregistration.json
    # rewrite Stage 02, re-freeze

which reproduced the original hole verbatim. Measured against `origin/main` with #203
merged: `re-freeze: 5357f8be | amendments: 0 | validate: CLEAN`. A different hypothesis
set, an empty amendment ledger, a `frozen_at` after the results existed, every validator
green. One extra `rm`, in a directory the operator already runs in with
`bypassPermissions` at `cwd=paths.run_root`.

Meanwhile `docs/framework.md`, `README.md` and — worst — `src/prompts/05_experimentation.md`
told the agent the deletion route was shut.

The third witness is a line in the run log, which is append-only and written by the
manager. It does not make the hole unreachable: everything under `run_root` is writable
by the party the gate constrains, so a reset now also has to truncate the log. What it
buys is that the cheapest escape stops being cheap and stops being silent, and that is
what the docs now say instead.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.prereg_support import write_hypothesis_manifest
from src.preregistration import (
    freeze_preregistration,
    preregistration_stamp_path,
    preregistration_tamper_findings,
    recorded_preregistration_repairs,
    validate_preregistration,
    witnessed_freeze_digests,
)
from src.utils import build_run_paths, ensure_run_layout, write_text


class ResetTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "runs" / "r1")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_hypothesis_manifest(self.paths)
        self.frozen = freeze_preregistration(self.paths)
        assert self.frozen is not None

    @property
    def frozen_file(self) -> Path:
        return self.paths.notes_dir / "preregistration.json"

    def rewrite_stage_02(self) -> None:
        manifest = json.loads(self.paths.hypothesis_manifest.read_text(encoding="utf-8"))
        manifest["empirical_hypotheses"][0]["decision_rule"] = "supported if it goes up at all"
        write_text(self.paths.hypothesis_manifest, json.dumps(manifest, indent=2))


class DeletingBothCopiesDoesNotBuyAFreshFreezeTests(ResetTestCase):
    def test_the_freeze_is_witnessed_in_the_run_log(self) -> None:
        self.assertEqual(witnessed_freeze_digests(self.paths), [self.frozen.digest])

    def test_deleting_both_and_re_freezing_is_refused(self) -> None:
        preregistration_stamp_path(self.paths).unlink()
        self.frozen_file.unlink()
        self.rewrite_stage_02()

        self.assertIsNone(freeze_preregistration(self.paths))

    def test_the_stage_is_then_refused_rather_than_passing_clean(self) -> None:
        """Refusing to re-derive is only worth anything if a gate then fires."""
        preregistration_stamp_path(self.paths).unlink()
        self.frozen_file.unlink()
        self.rewrite_stage_02()
        freeze_preregistration(self.paths)

        self.assertTrue(validate_preregistration(self.paths))

    def test_a_genuine_first_freeze_is_untouched(self) -> None:
        """The witness must not turn a run that never froze into a refusal."""
        fresh = build_run_paths(Path(self._tmp.name) / "runs" / "r2")
        ensure_run_layout(fresh)
        write_text(fresh.user_input, "goal")
        write_hypothesis_manifest(fresh)

        self.assertIsNotNone(freeze_preregistration(fresh))

    def test_deleting_only_the_file_still_restores_it(self) -> None:
        """#203's guarantee has to survive this change, not be replaced by it."""
        self.frozen_file.unlink()
        self.rewrite_stage_02()

        restored = freeze_preregistration(self.paths)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.digest, self.frozen.digest)


class AMissingStampDoesNotBrickTheRunTests(ResetTestCase):
    """Adopting a self-inconsistent record made every later attempt fail forever.

    Delete the stamp, then edit a statement *without* recomputing the digest. Before
    this change `freeze_preregistration` adopted the broken record, stamped it, and
    "repaired" it by writing it back over itself — appending an identical row to the
    stamp's repair list on every attempt, unbounded, while the recovery text told the
    agent that AutoR writes its own copy back, which in exactly that state it did not.
    Measured on `origin/main`: three attempts, two repair rows, findings never clear.
    """

    def break_the_file_in_place(self) -> None:
        preregistration_stamp_path(self.paths).unlink()
        payload = json.loads(self.frozen_file.read_text(encoding="utf-8"))
        payload["hypotheses"][0]["statement"] = "rewritten"
        write_text(self.frozen_file, json.dumps(payload, indent=2))

    def test_a_self_inconsistent_record_is_not_adopted(self) -> None:
        self.break_the_file_in_place()
        for _ in range(3):
            freeze_preregistration(self.paths)

        self.assertEqual(recorded_preregistration_repairs(self.paths), [])

    def test_it_is_still_reported_as_tampering(self) -> None:
        """Not adopting it must not mean not noticing it."""
        self.break_the_file_in_place()
        freeze_preregistration(self.paths)

        self.assertTrue(preregistration_tamper_findings(self.paths))


class TheRecoveryTextDoesNotPromiseWhatTheCodeStopsDoingTests(ResetTestCase):
    def test_it_says_the_restore_holds_only_while_a_copy_survives(self) -> None:
        from src.preregistration import PREREGISTRATION_RECOVERY

        self.assertIn("While AutoR still holds its own copy", PREREGISTRATION_RECOVERY)
        self.assertIn("once both are gone", PREREGISTRATION_RECOVERY)

    def test_it_still_names_the_rollback_rather_than_the_amend_call(self) -> None:
        """The escape it must not relocate to."""
        from src.preregistration import PREREGISTRATION_RECOVERY

        self.assertIn("rollback to Stage 02", PREREGISTRATION_RECOVERY)
        self.assertNotIn("amend_preregistration", PREREGISTRATION_RECOVERY)


if __name__ == "__main__":
    unittest.main()
