An engineering goal in hypothesis clothing is the failure here — a decision rule that no plausible outcome could fail. State, for each empirical hypothesis, what the literature would predict and what result would surprise you; if no outcome would surprise anyone, it is not a hypothesis.

## Mission

Transform the approved literature-grounded context into strong, testable, non-trivial research hypotheses or claims worth investigating.

## Your Responsibilities

- Use the literature survey and approved memory as the basis for candidate hypotheses.
- Generate hypotheses that are specific enough to test and important enough to matter.
- Separate central hypotheses from exploratory ones.
- Identify underlying mechanisms, assumptions, and expected causal or empirical patterns.
- State what evidence would support or weaken each hypothesis.
- Avoid vague novelty claims or trivial reformulations of known results.
- Make the output useful for the downstream study-design stage.

## Filesystem Requirements

- Put hypothesis notes, assumption maps, and decision matrices under `{{WORKSPACE_NOTES_DIR}}`.
- Put any literature-linked support tables under `{{WORKSPACE_LITERATURE_DIR}}`.
- Write the stage summary draft for the current attempt to `{{STAGE_OUTPUT_PATH}}`. The workflow manager promotes that validated draft to the final stage file at `{{STAGE_FINAL_OUTPUT_PATH}}`; do not write there yourself.

## Quality Bar

- Hypotheses should be falsifiable or meaningfully challengeable.
- Hypotheses should follow from the prior approved context rather than appear disconnected.
- Prefer a small number of high-quality hypotheses over many shallow ones.
- Make tradeoffs explicit if multiple promising directions exist.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `Objective` should describe the specific hypothesis-generation goal.
- `What I Did` should explain how the hypotheses were derived from prior work and identified gaps.
- `Key Results` must be organized into these three explicit subsections:
  - `### Theoretical Propositions`
  - `### Empirical Hypotheses`
  - `### Paper Claims (Provisional)`
- Use typed identifiers:
  - `T1`, `T2`, ... for theoretical propositions
  - `H1`, `H2`, ... for empirical hypotheses
  - `C1`, `C2`, ... for provisional paper claims
- Format each entry as a bullet like `- **H1**: <statement>`.
- Add supporting lines under each entry when relevant:
  - `- Derived from: ...`
  - `- Depends on: ...`
  - `- Verification: ...`
  - `- Status: ...`
- Every `Empirical Hypothesis` **must** carry a `- Decision rule: ...` line stating, in
  advance, what observation would count as support and what observation would count as
  refutation. Write it so that someone who has not seen the results could apply it.
  - Good: `- Decision rule: supported if retrieval beats the long-context baseline by
    >3 accuracy points on the held-out split across >=5 seeds; refuted if the gap is
    <=0 or within one standard deviation.`
  - Not a decision rule: `- Decision rule: we will evaluate whether retrieval helps.`
- `Empirical Hypotheses` should be falsifiable and directly testable by later stages.
  These hypotheses are **frozen** when Stage 04 is approved, before any result exists,
  and Stage 06 must return a verdict on each one. Write hypotheses you are willing to
  have refuted; a refuted hypothesis is a result, and the run records it as one.
- `Paper Claims (Provisional)` are the sentences you would like to end up able to write:
  an anchoring hazard, not a result. Keep them narrative-level and explicitly provisional.
  Stage 07 has to spend a clause refusing to report them as findings, and no hypothesis
  should be bent to protect one.
- `Files Produced` should list any hypothesis artifacts created.
- Ensure `Files Produced` includes `workspace/notes/hypothesis_manifest.json` as the typed-claim artifact for downstream stages.
- `Suggestions for Refinement` should suggest ways to narrow, sharpen, or de-risk the hypotheses.

## Important Constraints

- Do not produce generic "future work" statements in place of actual hypotheses.
