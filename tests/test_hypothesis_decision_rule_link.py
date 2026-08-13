"""The Stage 02 link in the validity chain, as a gate and as a graded criterion.

`02_hypothesis_generation.md` tells the agent that every empirical hypothesis **must**
carry a `- Decision rule: ...` line. `write_hypothesis_manifest` parsed the field and
nothing read it: measured on this tree before the change, `validate_stage_artifacts`
returned **no problem** at Stages 02, 03 and 04 for a manifest whose one empirical
hypothesis carried an empty `decision_rule`, and the first refusal came from
`validate_preregistration` at Stage 05 — after Stage 04's approval had frozen that set,
where the only repair is a rollback across three stages of work.

That is the shape the `validate_report_plan` call site already names, one stage
earlier: *"the Stage 03 prompt asks for it and the gate first fires at Stage 05, so a
Stage 03 that skipped it is approved and the failure surfaces two stages later, where
the only repair is a rollback."*
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.hypothesis_manifest import (
    build_hypothesis_manifest,
    hypotheses_without_decision_rule,
    validate_hypothesis_decision_rules,
    write_hypothesis_manifest,
)
from src.preregistration import freeze_preregistration, validate_preregistration
from src.rubric import score_stage
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    validate_stage_artifacts,
    validate_stage_markdown,
    write_text,
)

STAGE = {stage.number: stage for stage in STAGES}

RULE = (
    "supported if retrieval-on exceeds retrieval-off by more than 8 accuracy points on "
    "the held-out split across >=5 seeds; refuted if the gap is <=0."
)


def typed_stage_02(*, rule: str | None = RULE, derived_from: bool = False) -> str:
    """A Stage 02 draft in the shape the prompt asks for.

    `derived_from` defaults off because the prompt lists that field under "Add
    supporting lines under each entry **when relevant**" — a draft that omits it
    followed the prompt, and a gate that refuses it would be inventing a requirement.
    """
    lines = ["- **H1**: Retrieval augmentation raises long-context accuracy."]
    if derived_from:
        lines.append("  - Derived from: the Stage 01 survey of retrieval baselines.")
    lines.append("  - Depends on: T1")
    if rule is not None:
        lines.append(f"  - Decision rule: {rule}")
    hypothesis = "\n".join(lines)
    return (
        "# Stage 02: Hypothesis Generation\n\n"
        "## Objective\n\nDerive testable hypotheses from the survey.\n\n"
        "## Previously Approved Stage Summaries\n\nNone yet.\n\n"
        "## What I Did\n\nTurned `workspace/literature/claims.json` into typed claims.\n\n"
        "## Key Results\n\n"
        "### Theoretical Propositions\n"
        "- **T1**: Attention bottlenecks cause long-context degradation.\n\n"
        "### Empirical Hypotheses\n"
        f"{hypothesis}\n\n"
        "### Paper Claims (Provisional)\n"
        "- **C1**: Retrieval is a practical long-context fix.\n\n"
        "## Files Produced\n\n- `workspace/notes/hypothesis_manifest.json`\n\n"
        "## Decision Ledger\n\n"
        "- Open Questions: whether retrieval costs too much latency.\n"
        "- Locked Decisions: long-context QA is the evaluation target.\n"
        "- Assumptions: the base model is held fixed across arms.\n"
        "- Rejected Alternatives: full retraining, which the budget cannot cover.\n"
        "## Suggestions for Refinement\n\n1. a\n2. b\n3. c\n\n"
        "## Your Options\n\n"
        "1. Use suggestion 1\n2. Use suggestion 2\n3. Use suggestion 3\n"
        "4. Refine with your own feedback\n5. Approve and continue\n6. Abort\n"
    )


def manifest_payload(*, rule: str) -> dict:
    return {
        "generated_at": "2026-08-13T00:00:00",
        "theoretical_propositions": [
            {"id": "T1", "type": "theoretical", "statement": "A mechanism exists.", "decision_rule": ""}
        ],
        "empirical_hypotheses": [
            {
                "id": "H1",
                "type": "empirical",
                "statement": "Retrieval raises accuracy.",
                "decision_rule": rule,
            }
        ],
        "paper_claims": [
            {"id": "C1", "type": "paper_claim", "statement": "Retrieval is practical."}
        ],
    }


class DecisionRuleLinkTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def write_manifest(self, *, rule: str) -> None:
        write_text(self.paths.hypothesis_manifest, json.dumps(manifest_payload(rule=rule), indent=2))

    def problems(self, number: int) -> list[str]:
        return validate_stage_artifacts(STAGE[number], self.paths)

    def rule_problems(self, number: int) -> list[str]:
        return [item for item in self.problems(number) if "decision rule" in item.lower()]


class TheGateRefusesAtTheStageThatWroteThemTests(DecisionRuleLinkTestCase):
    def test_stage_02_refuses_an_empirical_hypothesis_with_no_decision_rule(self) -> None:
        self.write_manifest(rule="")
        found = self.rule_problems(2)
        self.assertEqual(len(found), 1, self.problems(2))
        self.assertIn("H1", found[0])

    def test_stage_02_accepts_the_same_manifest_once_the_rule_is_there(self) -> None:
        self.write_manifest(rule=RULE)
        self.assertEqual(self.rule_problems(2), [])

    def test_the_refusal_lands_three_stages_before_the_gate_that_used_to_be_first(self) -> None:
        """What the fix buys, stated as a comparison rather than as an adjective.

        `validate_preregistration` is the gate that caught this, and it is wired from
        Stage 05. It reads the *frozen* record — which Stage 04's approval writes from
        this very manifest, empty rule and all — so the run carried the defect through
        design and implementation, froze it, and only then heard about it, at the one
        point where the repair is a rollback across three stages.
        """
        self.write_manifest(rule="")
        frozen = freeze_preregistration(self.paths)
        assert frozen is not None
        self.assertEqual(
            [item.decision_rule for item in frozen.hypotheses if item.claim_type == "empirical"],
            [""],
            "Stage 04 froze the defect, which is what makes Stage 05 too late",
        )

        late = "has no decision rule"
        self.assertTrue(any(late in item for item in validate_preregistration(self.paths)))
        self.assertFalse(any(late in item for item in self.problems(4)))
        self.assertTrue(any(late in item for item in self.problems(5)))
        self.assertTrue(self.rule_problems(2))

    def test_the_requirement_is_cumulative_like_every_other_artifact_gate(self) -> None:
        self.write_manifest(rule="")
        for number in (2, 3, 4, 5, 6, 7, 8):
            self.assertTrue(self.rule_problems(number), msg=f"stage {number:02d} let it through")

    def test_stage_01_is_not_asked_for_hypotheses_it_has_not_generated_yet(self) -> None:
        self.write_manifest(rule="")
        self.assertEqual(self.rule_problems(1), [])

    def test_a_theoretical_proposition_carries_no_decision_rule_and_that_is_correct(self) -> None:
        """Only `empirical_hypotheses` are adjudicated. A proposition and a paper claim
        are not things a result can refute, and demanding a rule for them would push
        the agent to write one that no outcome could fail."""
        self.write_manifest(rule=RULE)
        payload = json.loads(self.paths.hypothesis_manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["theoretical_propositions"][0]["decision_rule"], "")
        self.assertEqual(payload["paper_claims"][0].get("decision_rule", ""), "")
        self.assertEqual(self.rule_problems(2), [])

    def test_derived_from_is_not_required_with_it(self) -> None:
        """The prompt lists `Derived from` under "when relevant", and the repo's own
        Stage 02 fixtures omit it. A gate that required it would refuse a draft that
        did what it was told."""
        markdown = typed_stage_02(derived_from=False)
        manifest = write_hypothesis_manifest(self.paths, markdown)
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest.empirical_hypotheses[0].derived_from, "")
        self.assertEqual(validate_stage_markdown(markdown, stage=STAGE[2], paths=self.paths), [])
        self.assertEqual(self.rule_problems(2), [])

    def test_a_manifest_nobody_can_parse_is_a_problem_and_not_a_crash(self) -> None:
        """`workspace/` is written by the party this gate constrains."""
        write_text(self.paths.hypothesis_manifest, "{not json at all")
        problems = validate_hypothesis_decision_rules(self.paths)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("hypothesis_manifest.json", problems[0])

    def test_an_absent_manifest_is_not_this_gates_business(self) -> None:
        """Stage 02's markdown contract already requires the typed subsections, and
        `validate_preregistration` says something better about a missing manifest than
        this could. Two gates reporting one absence is noise, not defence."""
        self.assertFalse(self.paths.hypothesis_manifest.exists())
        self.assertEqual(validate_hypothesis_decision_rules(self.paths), [])

    def test_the_gate_and_the_rubric_share_one_spelling_of_the_rule(self) -> None:
        manifest = build_hypothesis_manifest(typed_stage_02(rule=None))
        assert manifest is not None
        self.assertEqual(
            hypotheses_without_decision_rule(manifest.empirical_hypotheses), ["H1"]
        )
        self.assertEqual(
            hypotheses_without_decision_rule(
                build_hypothesis_manifest(typed_stage_02()).empirical_hypotheses  # type: ignore[union-attr]
            ),
            [],
        )


class TheGradedTwinReadsTheDraftTests(DecisionRuleLinkTestCase):
    def link(self, number: int, markdown: str):
        score = score_stage(paths=self.paths, stage=STAGE[number], markdown=markdown)
        return score.by_key["reproducibility"]

    def test_stage_02_is_graded_on_the_draft_and_not_on_the_file_on_disk(self) -> None:
        """A reverted polish round leaves the loser's manifest at
        `notes/hypothesis_manifest.json`. Reading it would grade the wrong document —
        in whichever direction the loser happened to differ."""
        self.write_manifest(rule=RULE)
        weak = self.link(2, typed_stage_02(rule=None))
        self.assertIn("falsifiable hypothesis set", weak.shortfall)
        self.assertIn("H1", weak.shortfall)

    def test_a_good_draft_is_not_docked_for_the_manifest_a_lost_round_left_behind(self) -> None:
        """The mirror. Both directions matter: one grades a draft for work it did not
        do, the other refuses a draft the work it did."""
        self.write_manifest(rule="")
        strong = self.link(2, typed_stage_02())
        self.assertNotIn("falsifiable hypothesis set", strong.shortfall)

    def test_a_stage_02_draft_with_no_hypotheses_at_all_does_not_borrow_the_old_ones(self) -> None:
        self.write_manifest(rule=RULE)
        empty = self.link(2, typed_stage_02().replace("### Empirical Hypotheses", "### Nothing"))
        self.assertIn("falsifiable hypothesis set", empty.shortfall)

    def test_stage_03_reads_the_manifest_because_its_draft_carries_none(self) -> None:
        markdown = typed_stage_02().replace("Stage 02: Hypothesis Generation", "Stage 03: Study Design")
        self.write_manifest(rule="")
        self.assertIn("falsifiable hypothesis set", self.link(3, markdown).shortfall)
        self.write_manifest(rule=RULE)
        self.assertNotIn("falsifiable hypothesis set", self.link(3, markdown).shortfall)

    def test_the_hypothesis_set_is_not_graded_twice_from_stage_04(self) -> None:
        """`>= 2` would spend two of this criterion's links on one artifact.

        From Stage 04 the same set is measured by the frozen-preregistration link, and
        `validate_preregistration` — the gate — checks the rules there. A run would
        otherwise look more reproducible for having declared its hypotheses twice.
        """
        markdown = typed_stage_02().replace("Stage 02: Hypothesis Generation", "Stage 04: Implementation")
        self.write_manifest(rule="")
        without = self.link(4, markdown)
        self.write_manifest(rule=RULE)
        self.assertEqual(self.link(4, markdown).score, without.score)
        self.assertNotIn("falsifiable hypothesis set", without.shortfall)

    def test_a_hand_corrupted_manifest_costs_the_criterion_and_does_not_end_the_run(self) -> None:
        """`score_stage` has no `try` around it, and the operator runs with
        `bypassPermissions` at `cwd=run_root`: `workspace/notes/` is written by the
        party this criterion measures. A `json.loads` here would turn a malformed file
        into a crash that loses the run rather than a score that loses points."""
        write_text(self.paths.hypothesis_manifest, '{"empirical_hypotheses": [')
        markdown = typed_stage_02().replace("Stage 02: Hypothesis Generation", "Stage 03: Study Design")
        self.assertIn("falsifiable hypothesis set", self.link(3, markdown).shortfall)

    def test_a_manifest_whose_hypothesis_list_is_not_a_list_is_survivable(self) -> None:
        write_text(self.paths.hypothesis_manifest, json.dumps({"empirical_hypotheses": "H1"}))
        markdown = typed_stage_02().replace("Stage 02: Hypothesis Generation", "Stage 03: Study Design")
        self.assertIn("falsifiable hypothesis set", self.link(3, markdown).shortfall)


if __name__ == "__main__":
    unittest.main()
