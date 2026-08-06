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


def write_validity_chain(paths: RunPaths, *, evidence: str = "results/metrics.json") -> None:
    """Freeze hypotheses, adjudicate them, and trace one claim to the verdict.

    ``evidence`` is a workspace-relative path. It is created if the caller has
    not already written it, because the gates reject a verdict or a claim that
    cites a file that does not exist — a rejection covered by its own test
    rather than by every fixture tripping over it.
    """
    evidence_path = paths.workspace_root / evidence
    if not evidence_path.exists():
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        write_text(evidence_path, json.dumps({"baseline": 0.61, "treatment": 0.74}))

    write_hypothesis_manifest(paths)
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


def reload_preregistration(paths: RunPaths):
    return load_preregistration(paths)
