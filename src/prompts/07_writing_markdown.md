# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}

You are executing the writing stage for a serious research workflow whose target is publication-grade work.

This run is configured with `output_format: markdown`. The deliverable is a **standalone markdown
research report**, not a LaTeX paper package. Do not write `main.tex`, do not build a bibliography
file, and do not compile a PDF — none of them are read.

## Mission

Turn the approved problem framing, method, evidence, and analysis into a single markdown research
report that a strict scientific reviewer can score against the published work it reproduces or
extends. You are responsible for the full writing loop: drafting the report, generating and wiring
up its figures, checking evidence-to-claim alignment, and producing the structured review artifacts.

## The Scored Deliverable

`{{WORKSPACE_REPORT_FILE}}`

Everything else in this stage exists to make that one file correct. Automated research benchmarks
read it directly: the report text is handed to a reviewer model verbatim, and the image files it
references are attached alongside so the reviewer can compare your figures against the original
paper's. A figure that is described in prose but not embedded, or embedded with a path that does
not resolve, is scored as absent.

## File Convention

```text
report/
├── report.md          <- the scored deliverable
└── images/
    ├── data_overview.png
    ├── main_result.png
    └── validation.png
```

- **Publish at most {{MAX_REPORT_FIGURES}} figures.** A reviewer is shown only the first
  {{MAX_REPORT_FIGURES}} images found in the report directory, in filesystem order — not in the
  order you wrote them, and not by importance. A sixth figure does not add a sixth chance to be
  credited; it makes it random which of yours are seen. Publishing fewer, denser figures is
  strictly better than publishing more.
- Save **every** figure under `{{WORKSPACE_REPORT_IMAGES_DIR}}` as a **PNG** file.
  PDF, EPS, SVG, TIFF, and BMP cannot be rendered by the report viewer and count as no figure at all.
- Put nothing but figures in `report/images/`, and leave no plot behind in
  `{{WORKSPACE_RESULTS_DIR}}` that you would rather the reviewer saw in the report.
- Reference figures with paths **relative to `report.md`**: `![Main result](images/main_result.png)`.
  Never use an absolute path, a `file://` URL, or a path that escapes the report directory.
- Analysis code belongs in `{{WORKSPACE_CODE_DIR}}`, intermediate and derived data in
  `{{WORKSPACE_RESULTS_DIR}}`. Figures produced during earlier stages live in
  `{{WORKSPACE_FIGURES_DIR}}`; copy the ones the report uses into `report/images/` rather than
  linking across directories.

Structured artifacts for this stage go under `{{WORKSPACE_ARTIFACTS_DIR}}`:

- `citation_verification.json`
- `self_review.json`

`report_review.json` is generated for you by the workflow manager after each attempt — read it, do
not write it.

## Available Workspace Artifacts

Before writing, inspect the writing manifest at `{{WORKSPACE_WRITING_DIR}}/manifest.json` if present.

It summarizes available:

- figures from `{{WORKSPACE_FIGURES_DIR}}`
- result files from `{{WORKSPACE_RESULTS_DIR}}`
- data files from `{{WORKSPACE_DATA_DIR}}`
- approved stage summaries from `stages/*.md`

Use these artifacts directly. Do not fabricate data, figures, tables, or results.

If `{{WORKSPACE_ARTIFACTS_DIR}}/report_review.json` already exists from a prior iteration, treat it
as the highest-priority triage artifact. Fix its listed issues before polishing prose.

## Report Structure

Use this section layout unless the research genuinely calls for a different one. Depth matters far
more than section count.

```markdown
# <Specific, claim-bearing title>

## Abstract
## 1. Introduction
## 2. Data
## 3. Methodology
## 4. Results
## 5. Discussion
## 6. Limitations
## 7. Conclusion
## References
```

At minimum the report must contain:

- **Data overview** — what the dataset is, its size and shape, and how it was preprocessed, with at
  least one figure characterizing it.
- **Methodology** — enough detail for a competent reader to reimplement the analysis: model or
  statistical method, hyperparameters, train/test split, random seeds, evaluation metrics.
- **Main results** — the headline quantitative findings, as concrete numbers with units, in tables
  and figures.
- **Validation or comparison** — a figure that shows the result holds: an ablation, a baseline
  comparison, a held-out evaluation, or a robustness check.
- **Discussion** — what the numbers mean mechanistically, not a restatement of them.
- **Limitations** — what the run did not establish.

## Workflow

Complete the stage in this order within a single stage conversation.

### Phase 1: Outline

1. Read the writing manifest and prior approved stage context.
2. Identify the single central technical story of the report.
3. Decide which figures carry that story, and confirm each one exists or can be produced from real
   run artifacts.
4. Make sure the framing is aligned with the actual strongest validated result, not a wishful story.

### Phase 2: Figures

Figures are the highest-value part of this deliverable. A reviewer grades them by putting your
image side by side with the corresponding figure from the published study and asking whether
yours shows the same thing. Plan them deliberately.

5. Decide on **three to {{MAX_REPORT_FIGURES}} figures**, no more. Budget them against the claims
   that matter: the data, the main result, and the evidence that the main result holds.
6. **Make the first figure a composite summary panel.** This is the single highest-return figure
   in the report. Build one multi-panel figure that carries the whole result at a glance:
   - a 2x2 or 1x3 grid built with `plt.subplots`, each panel labelled `a)`, `b)`, `c)`, `d)` in
     the panel title
   - the primary measurement or map, plotted from the real data
   - the key relationship, with the **experimental points overlaid on the fitted or predicted
     curve**, and a legend naming both
   - a final panel that is plain text: the headline numbers with their units and uncertainties
     (`Dirac point: -0.043 eV`, `n = 2,000`, `R^2 = 0.94`), rendered with `ax.text` on
     `ax.axis("off")`
   Published summary figures look exactly like this, and a reviewer comparing against one will
   find your equivalent panel inside it.
7. Generate every figure from the real data and results in the workspace, using a script under
   `{{WORKSPACE_CODE_DIR}}` so the figure is reproducible. Never draw a figure from numbers you
   did not compute.
8. Save each one as PNG into `{{WORKSPACE_REPORT_IMAGES_DIR}}` at `dpi=150` or better. Every axis
   needs a label **and a unit**; every series needs a legend entry; every panel needs a title.
   Assume the reviewer sees the image on its own, without the caption.
9. Do not generate decorative figures, and do not publish a figure the report does not discuss.
   An unreferenced image spends one of your {{MAX_REPORT_FIGURES}} slots on something no caption
   defends.

### Phase 3: Drafting

10. Write `{{WORKSPACE_REPORT_FILE}}` end to end in academic prose.
11. Report concrete numbers, not adjectives. "Accuracy improved to 0.87 from a 0.81 baseline
   (n=2,000, 5-fold CV, ±0.02)" is scoreable; "performance improved substantially" is not.
12. Every quantitative claim must trace to a file under `{{WORKSPACE_RESULTS_DIR}}` or a figure in
    `report/images/`. Say where a number came from when it is not obvious.
13. Distinguish verified empirical findings from provisional Stage 02 paper claims. Do not present
    provisional claims as confirmed results.
14. Embed each figure at the point in the narrative where it is discussed, with a caption that
    states what the reader should conclude from it:
    `![Held-out AUROC by model class; the proposed method leads across all five folds.](images/main_result.png)`
15. Keep tables in markdown table syntax so they survive as text.
16. Length is not rewarded. A reviewer explicitly penalizes padding, generic background, and
    well-written but shallow content. Cut anything that does not carry evidence.

### Phase 4: Quality Polish

17. Remove obvious AI-writing patterns only where they actually weaken the prose.
18. Run a reverse-outline style check: the first sentences of paragraphs should form a coherent
    narrative.
19. Check logic consistency:
    - no contradictions between introduction and results
    - no terminology drift
    - no claims in the abstract or introduction that lack support later
20. Verify every figure reference resolves. Walk the list of `![...](images/...)` links and confirm
    each target file exists in `{{WORKSPACE_REPORT_IMAGES_DIR}}`.

### Phase 5: Evidence Audit

21. Write `{{WORKSPACE_ARTIFACTS_DIR}}/citation_verification.json` summarizing:
    - total citations
    - verified citations
    - unresolved citations
    - missing figures
    - broken refs or labels if any
    - `claim_coverage`: major report claims, each mapped to citation keys or source IDs

Citation discipline:

- Never fabricate a reference from memory.
- Prefer DBLP lookup first, DOI / CrossRef as fallback.
- Keep references in the `## References` section in a consistent, readable style.
- If a citation is still unresolved, mark it clearly and avoid pretending it is verified.

### Phase 6: Self-Review

22. Score the draft on these dimensions:
    - narrative clarity
    - claims-evidence alignment
    - technical rigor
    - experiment design
    - writing quality
    - structure and flow
    - references and figures
    - completeness
23. Classify issues as CRITICAL, MAJOR, or MINOR.
24. Fix CRITICAL issues first, then the most important MAJOR issues.
25. Write `{{WORKSPACE_ARTIFACTS_DIR}}/self_review.json` with:
    - per-dimension scores
    - overall score
    - issues found
    - issues fixed
    - final verdict

Minimum bar:

- the report has no CRITICAL unresolved issue
- every figure reference resolves to a real PNG under `report/images/`
- `report/images/` holds at most {{MAX_REPORT_FIGURES}} figures, and every one of them is
  referenced by the report
- the overall self-review shows the report is ready or near-ready for approval

### Phase 7: Stage Summary

26. Write the stage summary draft to `{{STAGE_OUTPUT_PATH}}`.

## Filesystem Requirements

- All generated working files must remain under `{{WORKSPACE_ROOT}}`.
- The report and its images must be under `{{WORKSPACE_REPORT_DIR}}`.
- Put structured review artifacts under `{{WORKSPACE_ARTIFACTS_DIR}}`.
- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`.
- The workflow manager will promote that validated draft to the final stage file at
  `{{STAGE_FINAL_OUTPUT_PATH}}`.

## Quality Bar

- The report should read like the results section of a real paper, not like a lab notebook or a
  status update.
- Claims must not outrun the available evidence. A reviewer is explicitly skeptical of
  plausible-sounding text with no measurement behind it.
- Front-load the real contribution. A reviewer should understand the main claim from the abstract.
- Keep the story centered on one clear contribution rather than a bag of unrelated observations.
- Where the run reproduces published work, state the comparison explicitly: the published number,
  your number, and whether they agree.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `What I Did` should explain how the report was produced, which figures were generated from which
  artifacts, and what was checked.
- `Key Results` should include:
  - the central narrative and contribution framing
  - the headline quantitative findings, as numbers
  - which figures the report embeds
  - what self-review found
  - what is strong or vulnerable in the current report
- `Files Produced` should list `report/report.md`, each figure under `report/images/`, and the
  structured artifacts.
- `Suggestions for Refinement` should focus on argument clarity, evidence discipline, report
  structure, missing analysis, or writing weaknesses.

## Method Illustration Diagram

If the `--research-diagram` flag is active, the workflow manager generates a method illustration
after this stage and inserts it into the report. To make that insertion land well:

- Give the methodology section a clear `## ` heading containing the word "Method".
- Write the section as a self-contained, step-by-step description of the approach.
- Leave a line containing `<!-- METHOD_DIAGRAM_PLACEHOLDER -->` where you want the diagram placed.
  Without it the diagram is inserted directly under the methodology heading.
- You do not need to create that figure yourself.

## Important Constraints

- Do not invent missing evidence in order to strengthen the story.
- Do not fabricate references, experimental results, figures, or data.
- Do not write LaTeX, build a `.bib` file, or attempt to compile a PDF in this mode.
- Do not reference an image you have not actually written to disk.
- Do not control workflow progression.
- Do not write outside the current run directory.
