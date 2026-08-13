"""The frozen preregistration, checked against something the agent did not write.

Before the stamp existed, ``validate_preregistration`` compared the *manifest's*
digest to the recorded ``source_digest`` and never recomputed the digest of the
frozen file. Measured on a run built by this fixture, three edits passed with
zero problems: rewriting a hypothesis statement in ``preregistration.json``,
deleting ``hypothesis_manifest.json`` so the one comparison had nothing to
compare, and deleting the frozen file so the next freeze wrote a fresh record
with ``amendments: []`` and a post-results date.

Each of those is a test below, and each is asserted at the level of *which*
comparison catches it — because a single "something is wrong" assertion cannot
tell an implementation with three comparisons from one with the easiest one.
The bypass the self-digest alternative dies on has its own test: an edit that
also recomputes the digest field, which is available to the agent because
``format_preregistration_for_prompt`` renders the digest into the prompt.
"""

from __future__ import annotations

import hashlib
import json
import unittest

from src.preregistration import (
    PREREGISTRATION_RECOVERY,
    _self_digest,
    amend_preregistration,
    freeze_preregistration,
    load_preregistration,
    preregistration_stamp_path,
    preregistration_tamper_findings,
    recorded_preregistration_repairs,
    recorded_preregistration_stamp,
    validate_preregistration,
)
from src.stage_graph import GUARDS, GraphState
from src.utils import STAGES, validate_stage_artifacts

from tests.test_preregistration import PreregistrationTestCase


STAGE_05 = next(stage for stage in STAGES if stage.number == 5)


class StampedRunTestCase(PreregistrationTestCase):
    """A run whose hypotheses AutoR froze and stamped, as Stage 04 approval does."""

    def setUp(self) -> None:
        super().setUp()
        self.write_manifest()
        frozen = freeze_preregistration(self.paths)
        assert frozen is not None
        self.frozen = frozen

    def read_frozen(self) -> dict:
        return json.loads(self.paths.preregistration.read_text(encoding="utf-8"))

    def write_frozen(self, payload: dict) -> None:
        self.paths.preregistration.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

    def rewrite_a_statement(self, *, recompute_digest: bool = False) -> None:
        """The move the whole module exists to catch, with and without the forgery."""
        payload = self.read_frozen()
        for entry in payload["hypotheses"]:
            if entry["id"] == "H1":
                entry["statement"] = "Retrieval changes accuracy by some amount."
                entry["decision_rule"] = "supported if anything moved"
        if recompute_digest:
            canonical = json.dumps(
                payload["hypotheses"], sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            payload["digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.write_frozen(payload)


class TheStampIsOutsideTheWorkspaceTest(StampedRunTestCase):
    def test_the_stamp_is_written_under_the_run_root_and_not_under_workspace(self) -> None:
        """A stamp in `workspace/notes/` would be a receipt the payer prints."""
        path = preregistration_stamp_path(self.paths)

        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.paths.run_root)
        self.assertNotIn(self.paths.workspace_root, path.parents)

    def test_the_stamp_holds_the_record_and_not_only_a_hash_of_it(self) -> None:
        """Without the hypotheses there is nothing to restore a deleted file from."""
        stamped = recorded_preregistration_stamp(self.paths)

        assert stamped is not None
        self.assertEqual(stamped.digest, self.frozen.digest)
        self.assertEqual(stamped.frozen_at, self.frozen.frozen_at)
        self.assertEqual(
            [item.statement for item in stamped.hypotheses],
            [item.statement for item in self.frozen.hypotheses],
        )

    def test_a_clean_run_reports_nothing(self) -> None:
        """Control: the comparisons have to be silent on the untouched case."""
        self.assertEqual(preregistration_tamper_findings(self.paths), [])
        self.assertEqual(validate_preregistration(self.paths), [])

    def test_the_frozen_file_round_trips_to_the_digest_it_states(self) -> None:
        """Control for the first comparison: it must not fire on JSON re-encoding."""
        reloaded = load_preregistration(self.paths)
        assert reloaded is not None
        self.assertEqual(_self_digest(reloaded), reloaded.digest)


class ThreeComparisonsTest(StampedRunTestCase):
    """One comparison catches one of the three ways the record can be rewritten."""

    def test_a_rewritten_statement_is_caught_by_the_files_own_digest(self) -> None:
        self.rewrite_a_statement()

        findings = preregistration_tamper_findings(self.paths)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("hypotheses in it hash to", findings[0])

    def test_a_rewrite_that_recomputes_the_digest_is_caught_by_the_stamp(self) -> None:
        """The three-line bypass of a self-digest: the digest lives in the file."""
        self.rewrite_a_statement(recompute_digest=True)

        findings = preregistration_tamper_findings(self.paths)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("AutoR froze", findings[0])

    def test_a_truncated_amendment_ledger_is_caught_by_its_length(self) -> None:
        """Deleting the row that says the hypotheses moved leaves both digests intact."""
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")
        amended = amend_preregistration(self.paths, "Stage 02 re-run after rollback.")
        assert amended is not None
        self.assertEqual(len(amended.amendments), 1)

        payload = self.read_frozen()
        payload["amendments"] = []
        self.write_frozen(payload)

        findings = preregistration_tamper_findings(self.paths)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("amendment(s); AutoR recorded 1", findings[0])

    def test_no_single_comparison_catches_all_three(self) -> None:
        """The point of three. Each edit is invisible to the other two comparisons.

        Asserted as a matrix rather than three separate "something fired"
        checks, because an implementation that ran only the cheapest comparison
        and reported it three times would pass those.
        """
        digest_of = {}
        for label, mutate in (
            ("statement", lambda: self.rewrite_a_statement()),
            ("statement+digest", lambda: self.rewrite_a_statement(recompute_digest=True)),
            ("ledger", self._truncate_a_ledger),
        ):
            with self.subTest(edit=label):
                self.setUp()
                mutate()
                findings = preregistration_tamper_findings(self.paths)
                self.assertEqual(len(findings), 1, findings)
                digest_of[label] = findings[0]
        self.assertEqual(len(set(digest_of.values())), 3, digest_of)

    def _truncate_a_ledger(self) -> None:
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")
        amend_preregistration(self.paths, "Stage 02 re-run after rollback.")
        payload = self.read_frozen()
        payload["amendments"] = []
        self.write_frozen(payload)

    def test_the_stage_gate_reports_the_tamper(self) -> None:
        """The comparisons only matter if Stage 05's gate calls them."""
        self.rewrite_a_statement()

        problems = validate_stage_artifacts(STAGE_05, self.paths)
        self.assertTrue(
            any("not the set the file says was frozen" in problem for problem in problems),
            problems,
        )


class TheRefusalPointsSomewhereThatWorksTest(StampedRunTestCase):
    def test_the_refusal_does_not_send_the_run_to_amend_preregistration(self) -> None:
        """It returns the record unchanged when the manifest has not moved.

        A refusal naming a step that cannot clear it is permanent, and the
        cheapest move left to a permanently-refused agent is to delete the file
        and re-freeze — the escape these comparisons exist to close.
        """
        self.rewrite_a_statement()
        problems = validate_preregistration(self.paths)
        self.assertTrue(problems)

        for problem in problems:
            self.assertNotIn("amend_preregistration", problem)
            self.assertNotIn("amend the preregistration", problem)
        self.assertIn(PREREGISTRATION_RECOVERY, problems[0])

        before = load_preregistration(self.paths)
        assert before is not None
        amend_preregistration(self.paths, "trying to clear the refusal")
        after = load_preregistration(self.paths)
        assert after is not None
        self.assertEqual(after.to_dict(), before.to_dict())
        self.assertTrue(validate_preregistration(self.paths))

    def test_the_step_the_refusal_names_clears_it(self) -> None:
        """`freeze_preregistration` is the hook that runs before every attempt."""
        self.rewrite_a_statement(recompute_digest=True)
        self.assertTrue(validate_preregistration(self.paths))

        freeze_preregistration(self.paths)

        self.assertEqual(validate_preregistration(self.paths), [])
        restored = load_preregistration(self.paths)
        assert restored is not None
        self.assertIn("8 points", restored.hypotheses[1].statement)

    def test_the_repair_survives_in_the_stamp(self) -> None:
        """Writing the copy back is what destroys the evidence it was needed."""
        self.rewrite_a_statement()
        freeze_preregistration(self.paths)

        repairs = recorded_preregistration_repairs(self.paths)
        self.assertEqual(len(repairs), 1, repairs)
        self.assertIn("hash to", repairs[0]["found"])
        self.assertTrue(repairs[0]["repaired_at"])

    def test_an_untouched_run_records_no_repair(self) -> None:
        """Control: the freeze hook runs before every attempt from Stage 05 on."""
        for _ in range(3):
            freeze_preregistration(self.paths)
        self.assertEqual(recorded_preregistration_repairs(self.paths), [])


class TheResetPathTest(StampedRunTestCase):
    """Deleting the frozen file used to produce a clean record for a new set."""

    def test_the_restoration_does_not_go_back_to_the_manifest(self) -> None:
        """The stamp is the record, not a hash of one that has to be re-derived.

        Asserted with the manifest removed, because a restoration that reads it
        is a re-derivation wearing the stamp's name — and it would agree with
        the stamp on every field except the two the reset was for, the date and
        the ledger.
        """
        self.paths.hypothesis_manifest.unlink()
        self.paths.preregistration.unlink()

        restored = freeze_preregistration(self.paths)

        assert restored is not None
        self.assertEqual(restored.to_dict(), self.frozen.to_dict())
        self.assertEqual(load_preregistration(self.paths).to_dict(), self.frozen.to_dict())

    def test_a_reset_cannot_swap_the_hypothesis_set(self) -> None:
        """The headline reset: delete the freeze, rewrite Stage 02, re-freeze."""
        self.write_manifest(statement="Retrieval changes accuracy in some direction.")
        self.paths.preregistration.unlink()

        refrozen = freeze_preregistration(self.paths)

        assert refrozen is not None
        self.assertIn("8 points", refrozen.hypotheses[1].statement)
        self.assertEqual(refrozen.digest, self.frozen.digest)
        # And the manifest rewrite is now what it always was: an unrecorded change.
        self.assertTrue(
            any("no amendment was recorded" in problem for problem in validate_preregistration(self.paths)),
            validate_preregistration(self.paths),
        )

    def test_a_reset_cannot_wipe_the_amendment_ledger(self) -> None:
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")
        amend_preregistration(self.paths, "Stage 02 re-run after rollback.")
        self.paths.preregistration.unlink()

        refrozen = freeze_preregistration(self.paths)

        assert refrozen is not None
        self.assertEqual(len(refrozen.amendments), 1)
        self.assertEqual(refrozen.amendments[0]["reason"], "Stage 02 re-run after rollback.")

    def test_the_deletion_is_recorded_rather_than_absorbed(self) -> None:
        self.paths.preregistration.unlink()
        freeze_preregistration(self.paths)

        repairs = recorded_preregistration_repairs(self.paths)
        self.assertEqual(len(repairs), 1, repairs)
        self.assertIn("is gone", repairs[0]["found"])

    def test_a_missing_file_is_not_reported_as_a_run_that_never_froze(self) -> None:
        """The two states need different messages: one of them has a record."""
        self.paths.preregistration.unlink()

        problems = validate_preregistration(self.paths)

        self.assertEqual(len(problems), 1, problems)
        self.assertIn("still holds that record", problems[0])
        self.assertNotIn("never fixed before results existed", problems[0])
        self.assertIn(PREREGISTRATION_RECOVERY, problems[0])


class TheManifestIsNotOptionalTest(StampedRunTestCase):
    def test_deleting_the_manifest_no_longer_silences_the_comparison(self) -> None:
        """`hypothesis_manifest_digest` returns "" for a manifest that is gone.

        The falsy digest used to skip the source comparison rather than fail it,
        so removing the source was the way to make a rewrite of it unprovable.
        """
        self.paths.hypothesis_manifest.unlink()

        problems = validate_preregistration(self.paths)

        self.assertTrue(any("hypothesis_manifest.json is gone" in p for p in problems), problems)

    def test_the_manifest_that_is_present_and_unchanged_reports_nothing(self) -> None:
        """Control: the new branch must not fire on every ordinary run."""
        self.assertEqual(validate_preregistration(self.paths), [])


class TheAmendmentReadsTheStampTest(StampedRunTestCase):
    def test_an_amendment_moves_the_stamp_with_the_file(self) -> None:
        """Otherwise the first legitimate revision would look like a tamper."""
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")
        amended = amend_preregistration(self.paths, "Stage 02 re-run after rollback.")

        assert amended is not None
        stamped = recorded_preregistration_stamp(self.paths)
        assert stamped is not None
        self.assertEqual(stamped.digest, amended.digest)
        self.assertEqual(len(stamped.amendments), 1)
        self.assertEqual(preregistration_tamper_findings(self.paths), [])

    def test_a_forged_source_digest_cannot_launder_a_rewrite_into_an_amendment(self) -> None:
        """`source_digest` decides whether an amendment re-freezes at all.

        Read from the workspace copy, a rewritten file supplies its own answer:
        set it to anything, and the next Stage 02 re-run re-freezes and files
        an amendment, blessing the rewrite as AutoR's own record.
        """
        payload = self.read_frozen()
        payload["source_digest"] = "0" * 64
        self.write_frozen(payload)

        amended = amend_preregistration(self.paths, "Stage 02 was re-run.")

        assert amended is not None
        self.assertEqual(amended.amendments, [])
        self.assertEqual(amended.digest, self.frozen.digest)


class ARunWithNoStampIsAdoptedTest(PreregistrationTestCase):
    """A run frozen by an AutoR that predates the stamp must not be refused."""

    def setUp(self) -> None:
        super().setUp()
        self.write_manifest()
        freeze_preregistration(self.paths)
        preregistration_stamp_path(self.paths).unlink()

    def test_the_unstamped_run_passes_and_is_adopted_on_the_next_freeze(self) -> None:
        self.assertEqual(validate_preregistration(self.paths), [])

        freeze_preregistration(self.paths)

        self.assertIsNotNone(recorded_preregistration_stamp(self.paths))
        self.assertEqual(recorded_preregistration_repairs(self.paths), [])

    def test_the_comparison_that_needs_no_stamp_still_runs(self) -> None:
        """Losing the stamp costs two of three comparisons, not all three."""
        payload = json.loads(self.paths.preregistration.read_text(encoding="utf-8"))
        payload["hypotheses"][1]["statement"] = "Retrieval changes accuracy by some amount."
        self.paths.preregistration.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )

        findings = preregistration_tamper_findings(self.paths)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("hash to", findings[0])


class TheWritingEdgeReadsTheStampTest(StampedRunTestCase):
    """`_guard_validity_chain` counts hypotheses out of the file being checked."""

    def _guard(self):
        return GUARDS["validity_chain"](self.paths, GraphState())

    def test_the_edge_into_writing_closes_while_the_frozen_set_disagrees(self) -> None:
        self.write_outcomes()
        (self.paths.figures_dir / "f1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertTrue(self._guard().ok, self._guard().reason)

        self.rewrite_a_statement(recompute_digest=True)

        result = self._guard()
        self.assertFalse(result.ok)
        self.assertIn("AutoR stamped outside the workspace", result.reason)

    def test_dropping_a_hypothesis_from_the_frozen_file_does_not_open_the_edge(self) -> None:
        """Shrinking the population is how a file-read guard is talked past."""
        (self.paths.figures_dir / "f1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        payload = self.read_frozen()
        payload["hypotheses"] = [
            entry for entry in payload["hypotheses"] if entry["type"] != "empirical"
        ]
        self.write_frozen(payload)

        result = self._guard()
        self.assertFalse(result.ok, result.reason)


class ThePromptSentenceIsTrueTest(StampedRunTestCase):
    """Stage 05 tells the agent the frozen file is checked. It has to be.

    The prompt said "checks it for tampering" while no comparison recomputed the
    frozen file's digest, which made the sentence a deterrent rather than a
    description. A prompt claim that is not backed by a refusal teaches the
    agent that the claims in the prompt are not backed by refusals.
    """

    PROMPT = "src/prompts/05_experimentation.md"

    def _prompt_text(self) -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / self.PROMPT).read_text(encoding="utf-8")

    def test_the_prompt_promises_a_copy_outside_the_workspace_and_there_is_one(self) -> None:
        self.assertIn("outside the workspace", self._prompt_text())
        self.assertNotIn(self.paths.workspace_root, preregistration_stamp_path(self.paths).parents)

    def test_the_prompt_promises_restoration_rather_than_re_derivation(self) -> None:
        self.assertIn("restored, not re-derived", self._prompt_text())

        self.write_manifest(statement="Retrieval changes accuracy in some direction.")
        self.paths.preregistration.unlink()
        restored = freeze_preregistration(self.paths)

        assert restored is not None
        self.assertEqual(restored.digest, self.frozen.digest)

    def test_the_prompt_names_the_manifest_it_now_refuses_to_lose(self) -> None:
        self.assertIn("hypothesis_manifest.json", self._prompt_text())


if __name__ == "__main__":
    unittest.main()
