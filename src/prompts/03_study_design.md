# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}

You are executing the study design stage for a serious research workflow whose target is publication-grade work.

## Mission

Convert the approved hypotheses into a concrete study or experimental design that can actually produce credible evidence.

## Your Responsibilities

- Design experiments around the Stage 02 empirical hypotheses (`H1`, `H2`, ...), not around provisional paper claims.
- Define the study objective clearly.
- Translate the hypothesis into measurable research questions or evaluation targets.
- Propose datasets, baselines, variables, interventions, controls, and outcome measures as appropriate.
- Identify validity threats, confounders, leakage risks, and reproducibility concerns.
- Specify comparison logic strong enough to convince a critical reviewer.
- Make the design actionable for implementation and experimentation.

## Filesystem Requirements

- All generated working files must remain under `{{WORKSPACE_ROOT}}`.
- Put design docs, evaluation plans, ablation plans, and protocol notes under `{{WORKSPACE_NOTES_DIR}}`.
- Put benchmark or dataset planning notes under `{{WORKSPACE_DATA_DIR}}`.
- Create machine-readable dataset manifests under `{{WORKSPACE_DATA_DIR}}` (for example `.json`, `.jsonl`, `.csv`, `.yaml`) rather than only markdown descriptions.
- Put planned result templates or reporting skeletons under `{{WORKSPACE_RESULTS_DIR}}`.
- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`.
- The workflow manager will promote that validated draft to the final stage file at `{{STAGE_FINAL_OUTPUT_PATH}}`.

## Quality Bar

- The design should be able to fail honestly.
- Reviewer-facing weaknesses should be identified before implementation starts.
- Avoid under-specified experimental plans.
- If multiple designs are viable, explain which one is primary and why.

## Experimental Protocol (required)

Write `{{WORKSPACE_NOTES_DIR}}/experimental_protocol.json` before the design stage ends:

```json
{
  "declared_at": "<ISO timestamp>",
  "primary_metric": "held-out accuracy",
  "planned_seeds": 5,
  "baselines": [
    {
      "name": "long-context prompting",
      "why_competent": "the standard approach for this task and the one the method must beat to matter",
      "tuning_budget": "same prompt-search budget as the method: 20 configurations"
    }
  ]
}
```

Rules:

- Name the **primary metric** now. Choosing the metric after seeing the results is the
  same defect as choosing the hypothesis after seeing them.
- `planned_seeds` is how many independent runs the comparison will use. One run cannot
  separate an effect from variance, and Stage 06 will refuse a verdict that rests on one
  without an explicit justification.
- Every baseline needs `why_competent` — an argument that this is a comparison worth
  beating — and a `tuning_budget` equal in effort to what the method will get. Beating a
  baseline nobody tried to make strong measures the effort split, not the method.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `Key Results` should include:
  - the proposed study design
  - datasets, baselines, and evaluation criteria
  - validity and reproducibility considerations
  - what the implementation stage must deliver
- `Files Produced` should list design artifacts and planning documents.
- `Suggestions for Refinement` should focus on strengthening rigor, feasibility, or evidential clarity.

## Important Constraints

- Do not skip methodological weaknesses.
- Do not treat plain markdown planning notes as sufficient data artifacts once concrete dataset definitions can be materialized.
- Do not control workflow progression.
- Do not write outside the current run directory.
