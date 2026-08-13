"""A plan that every arm would fail admission on must not freeze.

`ArmSpec` carries the commit twice. `sha` is what the worktree gets checked out to and
what reaches the run command; `label` is what `_revision_matches_arm` compares the
recorded revision against, because `RunRecord` has no revision field and the label is
the only carrier. Two fields, one fact, and the gate reads the one not called `sha`.

So this plan is the obvious way to write an on/off trial:

    "control":   {"label": "off", "sha": "621566b", ...},
    "treatment": {"label": "on",  "sha": "47f3fbf", ...}

and it froze, launched, and had **every arm refused** by `revision_matches_arm` after
the runs were spent. Measured on the dry-run path before this guard existed: twelve
runs, twelve refusals, zero pairs. The exclusion lines in the report name the clause,
not the cause, so the reader sees `revision_matches_arm` twelve times and no
indication that the plan was the problem.

A real trial costs days of serialized live runs. The check costs a string comparison
and runs before the first launch.
"""

from __future__ import annotations

import unittest

from src.rcb_trial import ArmEvidence, RunEnvironment, TrialPlan, _revision_matches_arm


def plan_payload(*, control_label: str, treatment_label: str) -> dict:
    return {
        "capability": "whatever",
        "bench": "/bench",
        "tasks": ["Astronomy_000"],
        "control": {"label": control_label, "sha": "621566b", "worktree": "/w/control"},
        "treatment": {"label": treatment_label, "sha": "47f3fbf", "worktree": "/w/treatment"},
    }


class AMislabelledArmIsRefusedAtFreezeTests(unittest.TestCase):
    def test_the_on_off_labelling_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            TrialPlan.from_dict(plan_payload(control_label="off", treatment_label="on"))
        self.assertIn("621566b", str(caught.exception))

    def test_the_refusal_says_what_would_have_happened(self) -> None:
        """Naming the clause is not enough; the reader has to know the cost."""
        with self.assertRaises(ValueError) as caught:
            TrialPlan.from_dict(plan_payload(control_label="off", treatment_label="on"))
        message = str(caught.exception)
        self.assertIn("revision_matches_arm", message)
        self.assertIn("discarded", message)

    def test_a_label_that_is_the_commit_freezes(self) -> None:
        plan = TrialPlan.from_dict(
            plan_payload(control_label="621566b", treatment_label="47f3fbf")
        )
        self.assertEqual(plan.control.label, "621566b")

    def test_a_short_label_against_a_full_sha_freezes(self) -> None:
        """The prefix relation both ways, matching what the clause allows."""
        payload = plan_payload(control_label="621566b", treatment_label="47f3fbf")
        payload["control"]["sha"] = "621566b" + "0" * 33
        self.assertEqual(TrialPlan.from_dict(payload).control.label, "621566b")

    def test_an_empty_label_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            TrialPlan.from_dict(plan_payload(control_label="", treatment_label="47f3fbf"))

    def test_an_empty_sha_is_refused(self) -> None:
        payload = plan_payload(control_label="621566b", treatment_label="47f3fbf")
        payload["treatment"]["sha"] = ""
        with self.assertRaises(ValueError):
            TrialPlan.from_dict(payload)


class TheFreezeCheckMatchesTheAdmissionClauseTests(unittest.TestCase):
    """The guard is only worth anything if it applies the clause's own relation.

    A freeze check that were stricter would refuse plans that would in fact have run;
    one that were looser would let through the twelve-refusals case it exists to stop.
    Both are asserted against `_revision_matches_arm` itself rather than against a
    restatement of it.
    """

    def evidence(self, *, arm: str, revision: str) -> ArmEvidence:
        return ArmEvidence(
            task_id="Astronomy_000",
            arm=arm,
            run_id="r1",
            workspace="/w",
            env=RunEnvironment(),
            items=(),
            published_total=0.0,
            facts={
                "revision_at_launch": revision,
                "revision_at_finish": revision,
                "worktree_dirty": False,
            },
        )

    def test_a_label_the_freeze_accepts_is_one_the_clause_accepts(self) -> None:
        TrialPlan.from_dict(plan_payload(control_label="621566b", treatment_label="47f3fbf"))
        self.assertTrue(
            _revision_matches_arm(self.evidence(arm="621566b", revision="621566b8e1"))
        )

    def test_a_label_the_freeze_refuses_is_one_the_clause_refuses(self) -> None:
        with self.assertRaises(ValueError):
            TrialPlan.from_dict(plan_payload(control_label="off", treatment_label="on"))
        self.assertFalse(
            _revision_matches_arm(self.evidence(arm="off", revision="621566b8e1"))
        )


if __name__ == "__main__":
    unittest.main()
