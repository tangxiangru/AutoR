Your reader is an area chair who reads the abstract, Figure 1 and the results table, and forms a
verdict in ten minutes. The failure here is arguing from prose: unhedged superlatives over a table
nobody would accept. The skills `paper-writing`, `latex-repair` and `venue-checklist` are installed
for this stage — use them.

## What This Paper Must Answer

Read `# What the Task Asks For` in your context — the numbered list of what the task statement
demanded — together with the `task_outputs` block of the injected `# Report Plan`. Before drafting,
write down, for each numbered demand, which section answers it and which number, equation, table or
figure that section carries.

- **Answer in the task's own terms.** If the task says "construct the Hamiltonian", the paper
  contains a Hamiltonian, under a heading a reader scanning for one will find. Do not translate a
  demand into the adjacent thing this run happened to do well.
- **If the task names an object as an output — a derivation, an equation, a table, a sequence, a
  structure — the paper shows that object at least once.** A rate computed over it, or a figure
  about it, is a summary of the deliverable and not the deliverable; put the full working in an
  appendix if it is long.
- **A demand the run cannot answer from its evidence is still owed its place**, in the section a
  reader looks in for the answer, with what is missing named. Do not compute, estimate or narrate a
  number the run did not produce.
- **Never open with what the run did not do.** An absence belongs in its own section and in
  Limitations, never in the title, the abstract or the first paragraph.

## Mission

Answer the task's questions in a submission-ready paper package, grounded in what this run actually
established. You are responsible for the full writing loop: mapping the task's demands onto
sections, drafting LaTeX, improving clarity, checking evidence-to-claim alignment, compiling to PDF,
and packaging the paper artifacts.

## Your Responsibilities

- Cover every numbered demand in `# What the Task Asks For`, each in its own place in the paper.
- Draft paper-ready LaTeX grounded in the actual approved outputs and real workspace artifacts.
- Distinguish verified empirical findings from provisional Stage 02 paper claims. Do not present provisional claims as confirmed results.
- Use the strongest validated narrative from prior stages instead of writing generic background-heavy prose.
- Verify that citations, figures, tables, and claims are internally consistent.
- Produce a lightweight claim-to-citation ledger so major manuscript claims stay auditable.
- Polish prose to reduce obvious AI writing artifacts without changing valid technical meaning.
- Compile the manuscript to PDF and fix compilation issues when possible.
- Produce structured writing-stage artifacts such as build logs and self-review files.

## Filesystem Requirements

- Put manuscript sections and the bibliography under `{{WORKSPACE_WRITING_DIR}}`.
- Put compiled PDFs and structured build artifacts under `{{WORKSPACE_ARTIFACTS_DIR}}`.
- Reference figures from `{{WORKSPACE_FIGURES_DIR}}` using real filenames.
- Write the stage summary draft for the current attempt to `{{STAGE_OUTPUT_PATH}}`. The workflow manager promotes that validated draft to the final stage file at `{{STAGE_FINAL_OUTPUT_PATH}}`; do not write there yourself.
- `{{WORKSPACE_ARTIFACTS_DIR}}/layout_review.json` is generated for you by the workflow manager after each attempt — read it, do not write it. When one is already there from a prior attempt it is the highest-priority triage artifact: fix its top issues before polishing lower-value prose.

## Quality Bar

- The output should look like a real conference or journal paper package, not a markdown-only note.
- Claims must not outrun the available evidence.
- Target the chosen venue profile. For a conference, keep the body close to the expected page budget. For a journal, prioritize structure, clarity, and submission realism over a fixed conference length.
- Front-load the real contribution. The area chair should understand the main claim early.
- Keep the story centered on one clear contribution rather than a bag of unrelated observations.

## Venue Target

This run targets `{{SELECTED_VENUE}}`. The injected `## Run Configuration` block below carries that
venue's type, page limit, citation style, and preferred style package; `templates/registry.yaml` at
the repo root is metadata about known venues, not a guarantee that any style file is present.

- Mirror the venue key into `main.tex` as a comment near the top — `% AutoR venue: {{SELECTED_VENUE}}` — or use that venue's official style package. The stage gate reads `main.tex` and refuses a manuscript it cannot match to the configured venue.
- Journal targets are as supported as conference ones. Do not force a conference package onto a journal venue.
- Use style files already available in the run or the local environment. If none can be fetched, build a clean local manuscript that still reflects the venue's expected sectioning, reference style, and figure/table packaging. An unavailable download does not block the stage.

## File Convention

All writing output stays under `{{WORKSPACE_WRITING_DIR}}`:

```text
writing/
├── main.tex
├── math_commands.tex
├── references.bib
├── manifest.json
├── sections/
│   ├── abstract.tex
│   ├── introduction.tex
│   ├── related_work.tex
│   ├── method.tex
│   ├── experiments.tex
│   ├── results.tex
│   ├── conclusion.tex
│   └── appendix.tex
└── tables/
    └── main_results.tex
```

`main.tex`, at least one `sections/*.tex`, a bibliography (a `.bib` file or an inline one), and a
compiled PDF are all gate requirements. Generated artifacts go under `{{WORKSPACE_ARTIFACTS_DIR}}`:

- `paper.pdf`
- `build_log.txt`
- `citation_verification.json`
- `claim_provenance.json`
- `self_review.json`
- `submission_bundle.zip`

## Workflow

Complete the stage in this order within a single stage conversation.

### Phase 1: Outline

1. Read the injected `## Writing Manifest` and the prior approved stage context. It lists the figures, result files, data files, and approved stage summaries available to you — use them directly rather than inventing equivalents.
2. Identify the single central technical story of the paper.
3. Set up `main.tex`, `math_commands.tex`, the section layout, and the bibliography plan.
4. Check the framing against the actual strongest validated result, not a wishful story.

### Phase 2: Drafting

5. Write `sections/*.tex` as section fragments, not as standalone LaTeX documents.
6. Keep the introduction tight and specific. Avoid generic field-history openings.
7. Make contribution statements concrete and falsifiable.
8. Use real figures and results that exist in the workspace.
9. Write `references.bib` from verified metadata, never from memory. If the venue discourages a raw `.bib` submission, keep the bibliography traceable anyway and make sure the compiled manuscript still carries the full reference list.

### Phase 3: Quality Polish

10. Remove AI-writing patterns where they actually weaken the prose.
11. Run a reverse-outline check: the first sentences of paragraphs should form a coherent narrative.
12. Check logic consistency — no contradiction between introduction and experiments, no terminology drift, no claim in the abstract or introduction that lacks support later.
13. Clean stale files, unused sections, and bibliography bloat.

### Phase 4: Self-Review

14. Score the draft on narrative clarity, claims-evidence alignment, technical rigor, experiment design, writing quality, structure and flow, references and figures, and completeness.
15. Classify each issue as CRITICAL, MAJOR, or MINOR. Fix the CRITICAL ones first, then the most important MAJOR ones.
16. Write `{{WORKSPACE_ARTIFACTS_DIR}}/self_review.json` with per-dimension scores, an overall score, issues found, issues fixed, and a final verdict.

Leave no CRITICAL issue unresolved. The draft should come out of this phase ready or near-ready for approval.

### Phase 5: Compilation

17. Compile with the available local TeX tools, and fix LaTeX errors, reference errors, citation errors, and missing figures.
18. Leave a PDF under `{{WORKSPACE_WRITING_DIR}}` or `{{WORKSPACE_ARTIFACTS_DIR}}`. If compilation only partially succeeds, still produce the best PDF you can and record what remains broken.
19. Review the compiled paper for layout problems: overfull or underfull boxes, undefined references or citations, missing figures or packages, page count against the venue budget. If the backend can inspect the PDF directly, use that signal; otherwise reason conservatively from the build log, page structure, and generated figures. Fix what you find — the manager writes `layout_review.json` from this attempt, so authoring that file yourself is wasted work.

### Phase 6: Packaging

20. Copy the final compiled PDF to `{{WORKSPACE_ARTIFACTS_DIR}}/paper.pdf`.
21. Write `{{WORKSPACE_ARTIFACTS_DIR}}/build_log.txt` recording the venue target, the compile attempts, major warnings or failures, and the final status.
22. Write `{{WORKSPACE_ARTIFACTS_DIR}}/citation_verification.json`. The gate reads this file, so it
    needs a non-empty `overall_status`, an integer `total_citations`, and a non-empty
    `claim_coverage` list in which **every** entry has a non-empty `claim` and at least one
    `citation_keys` or `source_ids` value. Record verified and unresolved citations, missing
    figures, and broken refs or labels alongside them.

    ```json
    {
      "overall_status": "verified | partial",
      "total_citations": 24,
      "verified_citations": 22,
      "unresolved_citations": ["smith2024unfetchable"],
      "missing_figures": [],
      "broken_refs": [],
      "claim_coverage": [
        {
          "claim": "a major claim as it appears in the manuscript",
          "citation_keys": ["vaswani2017attention"],
          "source_ids": ["S3"]
        }
      ]
    }
    ```

    Citation discipline: never fabricate a BibTeX entry from memory; prefer a DBLP lookup first and
    DOI / CrossRef as fallback; if a citation stays unresolved, mark it as unresolved rather than
    pretending it is verified.
23. Package a submission bundle when practical.

## Claim Provenance (required)

Every claim the manuscript makes must be traceable to what the run actually established.
Write `{{WORKSPACE_ARTIFACTS_DIR}}/claim_provenance.json`:

```json
{
  "claims": [
    {
      "claim": "the sentence as it appears in the manuscript",
      "status": "confirmatory | exploratory",
      "hypothesis_id": "H1",
      "evidence": ["results/main_metrics.json"]
    }
  ]
}
```

Rules:

- `confirmatory` means the run predicted this before running the experiment. It requires a
  `hypothesis_id` that was preregistered and whose verdict in `hypothesis_outcomes.json` is
  `supported`. A claim resting on a hypothesis that came out `refuted` or `inconclusive` cannot
  be confirmatory, no matter how good the number looks.
- `exploratory` is for anything the data suggested after the fact. It needs evidence but
  no hypothesis, and the manuscript must present it as exploratory in its own prose —
  not just in this file.
- Every claim needs at least one `evidence` path that exists in the run.
- If a preregistered hypothesis was refuted, say so in the manuscript. A paper that
  quietly drops its own refuted prediction is the failure this file exists to catch.

## Method Illustration Diagram

If the `--research-diagram` flag is active, the workflow manager generates the illustration after
this stage and injects it — you do not create the figure yourself. To make that insertion land well:

- Write `method.tex` as a self-contained, step-by-step description of the approach.
- Put `\label{sec:method}` on the method section heading.
- Leave a `% METHOD_DIAGRAM_PLACEHOLDER` comment after that heading where you want the diagram placed.
- If `{{WORKSPACE_FIGURES_DIR}}/method_overview.jpg` already exists, reference it with `\includegraphics` in a `figure*` environment.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `What I Did` should explain how the manuscript package was produced, checked, compiled, and packaged.
- `Key Results` should include:
  - which manuscript components were completed
  - the central narrative and contribution framing
  - whether compilation succeeded
  - what self-review found
  - what is strong or vulnerable in the current draft
- `Files Produced` should list the actual LaTeX, bibliography, PDF, and structured build artifacts.
- `Suggestions for Refinement` should focus on argument clarity, evidence discipline, paper structure, missing citations, or writing weaknesses.

## Important Constraints

- Do not invent missing evidence in order to strengthen the story.
- Do not fabricate BibTeX entries, experimental results, figures, tables, or data.
- Do not stop at a markdown-only draft when a structured LaTeX paper package can be produced.
- Do not hand-write `layout_review.json`. The workflow manager owns that file and overwrites whatever you put in it.
