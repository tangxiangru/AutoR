Your reader is a model. It receives `{{WORKSPACE_REPORT_FILE}}` verbatim plus the first
{{JUDGE_VISIBLE_FIGURES}} images in `report/images/`, and reads it for an answer to each thing the task
asked for — one judgement per asked-for thing. A thing the task named and the report never mentions
is the cheapest thing there is to lose: a complete answer to a nearby question is worth less than a
partial answer to the one that was asked. Length is not rewarded; a figure that is described but not
embedded does not exist. Below 1200 characters the report is refused outright — that is a floor of
substance, not a word count: a report with no methodology, results and discussion has not been
written.

Before you decide what the report leads with, read `the-supplied-item-is-the-graded-unit` and
`draw-the-source-figure-panel-for-panel`: one is about the object the task actually shipped keeping
its own named section, the other about every result the source drew getting a panel of yours.
`paper-writing`, `result-table` and `citation-discipline` are named at the phases they belong to,
below.

## What This Report Must Answer

Read `# What the Task Asks For` in your context — the numbered list of what the task statement
demanded — together with the `task_outputs` block of `report_plan.json`. Before you write a word of
prose, write down, for each numbered demand, which section of this report answers it and which
number, equation, table or figure that section carries. That list is the report's outline, and it is
also `{{WORKSPACE_ARTIFACTS_DIR}}/deliverables_coverage.json`: draft it now as the outline, and fill
in each `where` once the section exists.

- **Answer in the task's own terms.** If the task says "construct the Hamiltonian", the report
  contains a Hamiltonian, under a heading a reader scanning for one will find. Do not translate a
  demand into the adjacent thing this run happened to do well.
- **If the task names an object as an output — a derivation, an equation, a table, a sequence, a
  structure — the report shows that object at least once.** A rate computed over it, a figure about
  it, or a pointer to the file holding it is a summary of the deliverable, not the deliverable. When
  the object is large, show its final form in the body and put the full working in an appendix
  section of this same file.
- **A demand the run cannot answer from its evidence is still owed its place.** Write what was asked,
  what the run established that bears on it, and what is missing — in that order, in the section a
  reader looks in for the answer. Do not compute, estimate, or narrate a number the run did not
  produce and cannot cite: an invented number is worse than a gap.
- **A published value is not an invented one.** Where the deliverable is out of this run's reach
  entirely — a wet-lab measurement, licensed hardware, a six-week experiment — the field's own answer
  is still reportable, and reporting it beats leaving the section empty. Give the value, name whose
  it is, style it in any figure as an external reference rather than as one of your series, and never
  count it as validation of your own pipeline. Then state what this run *does* establish about it and
  the distance between the two. Read the `a-value-you-did-not-measure-still-has-a-source` skill; the
  labelling is what separates a citation from a fabrication, and getting it right is worth a section
  that would otherwise score as absent.
- **Where the run's strongest result is not what the task asked for, both go in, in that order.** The
  task's answers take the title, the abstract and the opening of Results, and they get the figures;
  the run's other findings follow them. A report whose abstract is about the run rather than about
  the question has answered the wrong document.
- **Never open the report with what the run did not do.** An absence belongs in the section it bears
  on and in `## 6. Limitations` — never in the title, the abstract, or the first paragraph. The first
  thing a reader meets is the best answer this run can give to the question it was asked.

## Mission

Answer the task's questions in a single markdown research report, grounded in what this run actually
established, that a strict scientific reviewer can check line by line against the evidence on disk.
You are responsible for the full writing loop: mapping the task's demands onto sections, drafting the
report, generating and wiring up its figures, checking evidence-to-claim alignment, and producing the
structured review artifacts.

## Your Responsibilities

- Cover every numbered demand in `# What the Task Asks For`, each in its own place in the report, and
  record the mapping in `{{WORKSPACE_ARTIFACTS_DIR}}/deliverables_coverage.json`.
- Draft `{{WORKSPACE_REPORT_FILE}}` end to end, leading with those answers and the objects and numbers
  that carry them.
- Generate the report's figures from real run artifacts, and wire them in so every reference resolves.
- Distinguish verified empirical findings from provisional Stage 02 paper claims. Do not present provisional claims as confirmed results.
- Trace every number in the report to a file the run actually produced, or — for a value taken from
  the literature — to the source it is attributed to.
- Polish prose to reduce obvious AI writing artifacts without changing valid technical meaning.
- Produce the structured review artifacts this stage is gated on.

## Filesystem Requirements

- The report and its images must be under `{{WORKSPACE_REPORT_DIR}}`.
- Put structured review artifacts under `{{WORKSPACE_ARTIFACTS_DIR}}`.
- Put analysis and figure-generation code under `{{WORKSPACE_CODE_DIR}}`, and intermediate or derived data under `{{WORKSPACE_RESULTS_DIR}}`.
- Figures produced during earlier stages live in `{{WORKSPACE_FIGURES_DIR}}`; copy the ones the report uses into `report/images/` rather than linking across directories.
- `{{WORKSPACE_ARTIFACTS_DIR}}/report_review.json` is generated for you by the workflow manager after each attempt — read it, do not write it. When one is already there from a prior attempt it is the highest-priority triage artifact: fix its listed issues before polishing prose.
- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`. It is a separate file from the report; writing one does not satisfy the other.

## Quality Bar

- The report should read like the results section of a real paper, not like a lab notebook or a status update.
- Claims must not outrun the available evidence. The reviewer is explicitly skeptical of plausible-sounding text with no measurement behind it.
- Front-load the real contribution: the best answer this run can give to what the task asked. The reviewer should understand from the abstract what was asked and what this run answers. Where the run's strongest validated result is something the task did not ask for, it comes second, in its own subsection.
- Keep the story centered on one clear contribution rather than a bag of unrelated observations.
- Where the run reproduces published work, state the comparison explicitly: the published number, your number, and whether they agree.

## What Gets Read First

A reader — human or automated — forms a verdict on the result before reaching the
methodology. Where the deliverable is graded, that is not a metaphor: a grader scoring a
figure may be shown the picture and only the opening of the report, while a grader scoring a
written result sees all of it. Write for that.

- The headline numbers go in the Abstract and again in Results, with units, not only in a
  table further down.
- The figure ranked first in `report_plan.json` is discussed early. If it is only referenced
  in a late section, the argument for it lands where nobody is reading.
- Long methodology belongs after the result it produced, not before it.
- **Every quantity you declared in `headline_numbers` is stated, with its value and unit,
  before the methodology.** Those are the results this run nominated as its headline findings
  back at Stage 03, before any of them existed. A declared headline that first appears in a
  table on page four was mis-ranked by its own author, and the stage gate now says so.
- **Every term a figure has to be read against appears before the methodology too** — the
  symbol, the source's equation number, the published target value, the definition of the axis.
  A reader who forms a verdict on a picture from the opening of the report never reaches the
  section that would have told them what they were looking at. Where the run reproduces
  published work, read the `use-the-sources-own-names` skill: the source's name for a quantity
  is the only handle a reader has for finding your verification of it.
- **The opening is where the result goes, not where the shortfall goes.** A run whose report
  begins with what it could not establish has spent the only paragraphs some readers see on the
  weakest thing it has to say. The shortfall is owed its section; it is not owed the opening.

This is the ordinary shape of a well-written paper; the grading only makes the cost of
getting it wrong concrete.

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
- **Discussion** — what the numbers mean mechanistically, not a restatement of them. Where the
  run settled a methodological question, argue it here: the alternative that was rejected, the
  reason, and what would overturn the answer. A discussion that only restates the results is
  the most commonly wasted section in an AI-written report.
- **Limitations** — what the run did not establish. This section, and not the title or the abstract,
  is where an absence is stated.

## File Convention

```text
report/
├── report.md          <- the scored deliverable
└── images/
    ├── data_overview.png
    ├── main_result.png
    └── validation.png
```

- **{{MAX_REPORT_FIGURES}} figures is a ceiling, and it is not a target.** Publish the figures the
  report argues from and stop. A study that settles three questions publishes three; padding to
  the ceiling adds nothing and costs the reader. What decides the score is whether the key
  quantities were produced and shown, not how many panels surround them.
- **Only the first {{JUDGE_VISIBLE_FIGURES}} images reach the reviewer**, found in filesystem
  order — not in the order you wrote them, and not by importance. Past
  {{JUDGE_VISIBLE_FIGURES}} it is directory order, not your report, that chooses what is seen, so
  a figure beyond that does not add a further chance to be credited: it makes it arbitrary which
  of yours are. Well inside the limit this costs you nothing, which is the normal case and the
  one to aim for. Fewer, denser figures are still better on their own merits — a composite panel
  carrying three claims beats three panels carrying one each, because the reader forms a verdict
  from what is in front of them, not from how many files you wrote.
- Save **every** figure under `{{WORKSPACE_REPORT_IMAGES_DIR}}` as a **PNG**. PDF, EPS, SVG, TIFF,
  and BMP cannot be rendered by the report viewer and count as no figure at all.
- Put nothing but figures in `report/images/`, and leave no plot behind in
  `{{WORKSPACE_RESULTS_DIR}}` that you would rather the reviewer saw in the report.
- Reference figures with paths **relative to `report.md`**: `![Main result](images/main_result.png)`.
  Never use an absolute path, a `file://` URL, or a path that escapes the report directory.

Structured artifacts for this stage go under `{{WORKSPACE_ARTIFACTS_DIR}}`:

- `deliverables_coverage.json` — the answer-by-answer map from `# What the Task Asks For` to where in
  the report each demand is answered. Draft it first, as the report's outline; fill in each `where`
  once the section exists.
- `citation_verification.json`
- `claim_provenance.json`
- `self_review.json`

## Workflow

Complete the stage in this order within a single stage conversation.

### Phase 1: Outline

0. **Read the `publish-what-the-run-already-computed` skill and run its sweep first.** The outline
   is decided here, and the objects it leaves out do not come back. Every object the task named as
   an output that this run wrote to disk gets a body subsection before any other section is planned.
1. Read the injected `## Writing Manifest` and the prior approved stage context. It lists the figures, result files, data files, and approved stage summaries available to you — use them directly rather than inventing equivalents.
2. Identify the single central technical story of the report.
3. Read the injected `# Report Plan`; the figure set was chosen at Stage 03 against the claims it carries. Your job is to publish it, not to re-choose it.
4. Check the framing against the task's demands first and the run's strongest validated result
   second: the answers to what was asked lead, and the run's other findings follow them. Neither may
   outrun the evidence on disk — a framing the artifacts do not support is not available at either
   position.

### Phase 2: Figures

Figures are the highest-value part of this deliverable. The reviewer grades them by putting your
image side by side with the corresponding figure from the published study and asking whether yours
shows the same thing. They were chosen at Stage 03; this phase produces them.

**Read the `the-canonical-figure` skill before you draw.** A diagnostic plot of your own pipeline
and the source study's result plot are different objects, and only one of them is being compared to
anything. **Read the `result-table` skill** before you build the results table, and
**read `the-unit-of-analysis`** before you pool anything into a single number: a criterion
written about per-stratum behaviour is not answered by an average over the strata.

5. **Publish the planned figures in slot order, at most {{MAX_REPORT_FIGURES}} and preferably far
   fewer — the first {{JUDGE_VISIBLE_FIGURES}} are what a reviewer sees.** Every slot you
   do not publish needs `dropped_because` in `report_plan.json` and a sentence in `Key Results`;
   a slot you publish that the plan does not name will be flagged in `report_review.json`.
   Dropping is for a figure the results made impossible, not for one you ran out of time for:
   the plan's claims still have to be carried, and a report that ends up below three figures is
   one where the data, the main result and the evidence it holds are not all shown.
   **A figure the opening of the report never explains is a figure a grader sees without a
   caption.** A reader forming a verdict on a picture may have only the picture and the first
   pages of the prose, so the count that matters is not how many figures you published but how
   many of them are introduced and interpreted before the methodology. Publishing a further
   figure that is first discussed on page five adds an image to the pile and no argument to it.
   Three figures each explained in the opening beat ten of which two are.
6. **Make the first figure a composite summary panel.** This is the single highest-return figure
   in the report, and it is slot 1's default role. Build one multi-panel figure that carries the
   whole result at a glance:
   - a 2x2 or 1x3 grid built with `plt.subplots`, each panel labelled `a)`, `b)`, `c)`, `d)` in
     the panel title
   - the primary measurement or map, plotted from the real data
   - the key relationship, with the **experimental points overlaid on the fitted or predicted
     curve**, and a legend naming both
   - a final panel that is plain text: the plan's `headline_numbers` with their units and
     uncertainties (`Dirac point: -0.043 eV`, `n = 2,000`, `R^2 = 0.94`), rendered with
     `ax.text` on `ax.axis("off")`
   Published summary figures look exactly like this, and a reviewer comparing against one will
   find your equivalent panel inside it.
7. Generate every figure from the real data and results in the workspace, using a script under
   `{{WORKSPACE_CODE_DIR}}` so the figure is reproducible. Never draw a figure from numbers you
   did not compute.
8. Save each one as PNG into `{{WORKSPACE_REPORT_IMAGES_DIR}}` at `dpi=150` or better. Every axis
   needs a label **and a unit**; every series needs a legend entry; every panel needs a title.
   Assume the reviewer sees the image on its own, without the caption.
9. Do not generate decorative figures, and do not publish a figure the report does not discuss.
   An unreferenced image can take one of the {{JUDGE_VISIBLE_FIGURES}} places a reviewer looks at,
   and spend it on something no caption defends. Time spent on a figure nobody asked for is time
   not spent producing the quantity the task did ask for.

### Phase 3: Drafting

10. Write `{{WORKSPACE_REPORT_FILE}}` end to end in academic prose.
11. **State the headline numbers, with their units, in the report's first section.** What
    argues for the figures has to come before anything long.
12. Report concrete numbers, not adjectives. "Accuracy improved to 0.87 from a 0.81 baseline
    (n=2,000, 5-fold CV, ±0.02)" is scoreable; "performance improved substantially" is not.
13. Every quantitative claim must trace to a file under `{{WORKSPACE_RESULTS_DIR}}`, to a figure in
    `report/images/`, or to a cited publication. Say where a number came from when it is not
    obvious, and mark a literature value as one at the point it appears.
14. Embed each figure at the point in the narrative where it is discussed, with a caption that
    states what the reader should conclude from it:
    `![Held-out AUROC by model class; the proposed method leads across all five folds.](images/main_result.png)`
15. Keep tables in markdown table syntax so they survive as text.
16. Keep every reference in the `## References` section in a consistent, readable style.
17. Cut anything that does not carry evidence. Padding, generic background, and well-written but
    shallow content are explicitly penalized.

### Phase 4: Quality Polish

Read the `paper-writing` skill before this phase.

18. Remove AI-writing patterns where they actually weaken the prose.
19. Run a reverse-outline check: the first sentences of paragraphs should form a coherent narrative.
20. Check logic consistency — no contradiction between introduction and results, no terminology
    drift, no claim in the abstract or introduction that lacks support later.
21. Verify every figure reference resolves. Walk the list of `![...](images/...)` links and confirm
    each target file exists in `{{WORKSPACE_REPORT_IMAGES_DIR}}`.

### Phase 5: Evidence Audit

Read the `evidence-not-assertion` skill before this phase, and `citation-discipline` for any
reference you are about to record.

22. Write `{{WORKSPACE_ARTIFACTS_DIR}}/citation_verification.json`. The gate reads this file and
    refuses the stage without it; its required fields and schema are in
    `## Required Artifacts (schemas)` at the end of this file. Record verified and unresolved
    citations, missing figures, and broken refs or labels.

### Phase 6: Argue the Discussion

Read the `answer-the-why-not-only-the-what` skill before this phase.

If a `Reasoning This Run Already Settled` section appears in your context, the run argued
those points and recorded the arguments instead of publishing them. Work the ones that bear
on a claim the report makes into Discussion:

- **A settled question** becomes *"we chose X over Y because Z"* — a sentence a reader can
  disagree with. Reproducing the panel's transcript is not that.
- **A falsifier** becomes *"this would be overturned by W"*, attached to the claim it
  qualifies. State it for each main claim, whether or not a panel supplied one.
- **A hypothesis generated and not pursued** belongs in Discussion or Limitations only when
  the report can say what ruling it out or in would take. An inventory of everything anyone
  proposed adds length without adding an argument.

Two guards. Nothing from that section goes before the Results — the opening of the report is
where the headline numbers have to be. And silence beats padding: a settled point that bears
on nothing the report claims is better left out than discussed.

### Phase 7: Self-Review

23. Score the draft on narrative clarity, claims-evidence alignment, technical rigor, experiment
    design, writing quality, structure and flow, references and figures, and completeness.
24. Classify each issue as CRITICAL, MAJOR, or MINOR. Fix the CRITICAL ones first, then the most
    important MAJOR ones.
25. Write `{{WORKSPACE_ARTIFACTS_DIR}}/self_review.json` with per-dimension scores, an overall
    score, issues found, issues fixed, and a final verdict.

Minimum bar:

- no CRITICAL issue is left unresolved
- every figure reference resolves to a real PNG under `report/images/`
- `report/images/` holds at most {{MAX_REPORT_FIGURES}} figures, and every one of them is
  referenced by the report
- the overall self-review shows the report is ready or near-ready for approval

### Phase 8: Stage Summary

26. Write the stage summary draft to `{{STAGE_OUTPUT_PATH}}`.
27. Read the `record-what-you-learned` skill and act on it. This is the last stage that runs in this
    configuration, so a note not written here is never written: the pool the next run in this field
    inherits stays empty.

## Claim Provenance (required)

Every claim the report makes must be traceable to what the run actually established. Write
`{{WORKSPACE_ARTIFACTS_DIR}}/claim_provenance.json`; the gate refuses the stage without it, and its
schema and rules are in `## Required Artifacts (schemas)` at the end of this file.

## Method Illustration Diagram

If the `--research-diagram` flag is active, the workflow manager generates a method illustration
after this stage and inserts it into the report — you do not create that figure yourself. To make
that insertion land well:

- Give the methodology section a clear `## ` heading containing the word "Method".
- Write the section as a self-contained, step-by-step description of the approach.
- Leave a line containing `<!-- METHOD_DIAGRAM_PLACEHOLDER -->` where you want the diagram placed.
  Without it the diagram is inserted directly under the methodology heading.

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

## Important Constraints

- Do not invent missing evidence in order to strengthen the story.
- Do not fabricate references, experimental results, figures, tables, or data.
- Do not write LaTeX, build a `.bib` file, or attempt to compile a PDF: this run is in `markdown` mode and none of them are read.
- Do not reference an image you have not actually written to disk.
- Do not leave placeholder text in `report.md`. A bracketed stub — `[TODO ...]`, `[pending ...]`,
  `[placeholder ...]`, `[in progress ...]`, `[to be determined ...]`, `[to be populated ...]` —
  fails the report gate outright, however finished the rest of the file is.
- Do not hand-write `report_review.json`. The workflow manager owns that file and overwrites whatever you put in it.

## Required Artifacts (schemas)

Both files are gated: the stage is refused without them. They are here, at the end, because they are
the form of the record and not the substance of the report — write the report first.

### `citation_verification.json`

The gate reads this file, so it needs a non-empty `overall_status`, an integer `total_citations`, and
a non-empty `claim_coverage` list in which **every** entry has a non-empty `claim` and at least one
`citation_keys` or `source_ids` value.

```json
{
  "overall_status": "verified | partial",
  "total_citations": 18,
  "verified_citations": 17,
  "unresolved_citations": ["smith2024unfetchable"],
  "missing_figures": [],
  "broken_refs": [],
  "claim_coverage": [
    {
      "claim": "a major claim as it appears in the report",
      "citation_keys": ["vaswani2017attention"],
      "source_ids": ["S3"]
    }
  ]
}
```

Citation discipline: never fabricate a reference from memory; prefer a DBLP lookup first and
DOI / CrossRef as fallback; if a citation stays unresolved, mark it as unresolved rather than
pretending it is verified.

### `claim_provenance.json`

```json
{
  "claims": [
    {
      "claim": "the sentence as it appears in the report",
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
  no hypothesis, and the report must present it as exploratory in its own prose —
  not just in this file.
- Every claim needs at least one `evidence` path that exists in the run.
- If a preregistered hypothesis was refuted, say so in the report. A write-up that
  quietly drops its own refuted prediction is the failure this file exists to catch.
