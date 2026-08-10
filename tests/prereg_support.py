"""Minimal valid scientific-validity artifacts for tests that build a run by hand.

From Stage 05 on, a complete run carries a frozen preregistration; from Stage 06
a verdict on every hypothesis in it; from Stage 07 a provenance record for every
claim. Tests that assert "a complete package passes" have to build those too,
or they are asserting that an incomplete package passes.

Kept in one place so the definition of "complete" lives in one place.
"""

from __future__ import annotations

import json

from src.preregistration import freeze_preregistration, load_preregistration
from src.utils import RunPaths, write_text


HYPOTHESIS_ID = "H1"


def write_hypothesis_manifest(paths: RunPaths) -> None:
    write_text(
        paths.hypothesis_manifest,
        json.dumps(
            {
                "generated_at": "2026-04-08T00:00:00",
                "theoretical_propositions": [
                    {
                        "id": "T1",
                        "type": "theoretical",
                        "statement": "The effect has a mechanism the design can isolate.",
                    }
                ],
                "empirical_hypotheses": [
                    {
                        "id": HYPOTHESIS_ID,
                        "type": "empirical",
                        "statement": "The treatment raises accuracy over the baseline.",
                        "decision_rule": (
                            "supported if the treatment exceeds the baseline by more than 2 "
                            "accuracy points on the held-out split; refuted otherwise."
                        ),
                    }
                ],
                "paper_claims": [
                    {
                        "id": "C1",
                        "type": "paper_claim",
                        "statement": "The treatment is a practical improvement.",
                    }
                ],
            }
        ),
    )


def write_experimental_protocol(paths: RunPaths, *, planned_seeds: int = 5) -> None:
    write_text(
        paths.experimental_protocol,
        json.dumps(
            {
                "declared_at": "2026-04-08T00:00:00",
                "primary_metric": "held-out accuracy",
                "planned_seeds": planned_seeds,
                "baselines": [
                    {
                        "name": "standard baseline",
                        "why_competent": "the established approach the method has to beat to matter",
                        "tuning_budget": "the same search budget the method receives",
                    }
                ],
            }
        ),
    )


def write_report_plan(
    paths: RunPaths,
    *,
    filename: str = "accuracy.png",
    source_artifact: str = "results/metrics.json",
    figures=None,
    headline_numbers=None,
) -> None:
    """One planned figure, one headline number: the smallest plan the gate accepts.

    Deliberately one entry rather than five. The fixture is read by everyone who
    adds a test, and a five-entry fixture would teach the ceiling as a target
    exactly the way a five-entry prompt example would.

    ``filename`` defaults to the figure the run fixtures in this suite publish,
    so the Stage 07 coverage check sees a plan the package actually delivered.
    """
    write_text(
        paths.report_plan,
        json.dumps(
            {
                "figures": figures
                if figures is not None
                else [
                    {
                        "slot": 1,
                        "filename": filename,
                        "supports": [HYPOTHESIS_ID],
                        "shows": (
                            "Held-out accuracy (%) for the treatment and the baseline, "
                            "five seeds, band = stderr."
                        ),
                        "if_supported": "the treatment's bar clears the baseline's error band",
                        "if_refuted": "the two bars overlap within their error bands",
                        "source_artifact": source_artifact,
                        "dropped_because": "",
                    }
                ],
                "headline_numbers": headline_numbers
                if headline_numbers is not None
                else [
                    {
                        "quantity": "held-out accuracy, treatment vs baseline",
                        "unit": "percentage points",
                        "source_artifact": source_artifact,
                    }
                ],
            }
        ),
    )


def write_round_decision(paths: RunPaths, *, decision: str = "converged", **overrides) -> None:
    payload = {
        "decision": decision,
        "rationale": "The evidence settles the preregistered question for this round.",
        "what_we_learned": "The treatment clears the decision rule the round declared in advance.",
        "what_changes_next": "",
        "negative_result": False,
    }
    payload.update(overrides)
    write_text(paths.round_decision, json.dumps(payload))


def close_round(paths: RunPaths, **kwargs) -> None:
    """Declare and close a round, as Stage 06 approval would."""
    from src.research_rounds import record_round

    write_round_decision(paths, **kwargs)
    record_round(paths, acted_on=True)


def write_validity_chain(
    paths: RunPaths,
    *,
    evidence: str = "results/metrics.json",
    close_first_round: bool = True,
) -> None:
    """Freeze hypotheses, adjudicate them, and trace one claim to the verdict.

    ``evidence`` is a workspace-relative path. It is created if the caller has
    not already written it, because the gates reject a verdict or a claim that
    cites a file that does not exist — a rejection covered by its own test
    rather than by every fixture tripping over it.

    The figure plan is part of the same chain: it is declared at Stage 03, one
    stage before the freeze, and its single slot is drawn from the same evidence
    artifact the verdict cites.
    """
    evidence_path = paths.workspace_root / evidence
    if not evidence_path.exists():
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        write_text(evidence_path, json.dumps({"baseline": 0.61, "treatment": 0.74}))

    write_hypothesis_manifest(paths)
    write_experimental_protocol(paths)
    write_report_plan(paths, source_artifact=evidence)
    prereg = freeze_preregistration(paths)
    if prereg is None:  # pragma: no cover - only if the manifest write failed
        raise AssertionError("preregistration did not freeze from the test manifest")

    write_text(
        paths.hypothesis_outcomes,
        json.dumps(
            {
                "generated_at": "2026-04-08T00:00:00",
                "preregistration_digest": prereg.digest,
                "outcomes": [
                    {
                        "id": identifier,
                        "verdict": "supported",
                        "rationale": "The measured gap clears the preregistered decision rule.",
                        "evidence": [evidence],
                        "statistics": {
                            "n_seeds": 5,
                            "dispersion": 0.011,
                            "dispersion_type": "std",
                        },
                    }
                    for identifier in prereg.adjudicated_ids
                ],
                "exploratory_findings": [],
            }
        ),
    )
    write_text(
        paths.claim_provenance,
        json.dumps(
            {
                "claims": [
                    {
                        "claim": "The treatment raises accuracy over the baseline.",
                        "status": "confirmatory",
                        "hypothesis_id": HYPOTHESIS_ID,
                        "evidence": [evidence],
                    }
                ]
            }
        ),
    )
    # A run that reaches Stage 07 has closed at least one round. Tests that
    # drive rounds themselves opt out.
    if close_first_round:
        close_round(paths)


def reload_preregistration(paths: RunPaths):
    return load_preregistration(paths)
