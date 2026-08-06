---
name: result-table
description: Use when turning measured results into a table or figure for the paper — building a LaTeX or markdown results table from workspace/results/*.json, deciding what uncertainty to report, choosing which baselines and ablations belong in the main table, or writing a caption that stands alone.
---

# Results tables

By Stage 06 the run has machine-readable results under `workspace/results/`
and an `experiment_manifest.json` indexing them with schema metadata. The table
in the paper must be derived from those files, not retyped. A number that
appears in the manuscript and nowhere in `workspace/results/` is unsupported,
and it is the single easiest thing for a reviewer to catch.

## Build the table from the artifacts

1. Read `workspace/results/experiment_manifest.json` for the result artifacts
   and their schemas.
2. Generate the table with a script written to `workspace/code/`, not by hand.
   A regenerable table survives a Stage 06 rerun; a hand-typed one silently
   goes stale the moment a result changes.
3. Write the generated table to a file the manuscript inputs
   (`workspace/writing/tables.tex`, or an inline markdown table in the report),
   so the paper and the artifact cannot drift.

## What goes in the main table

The main table answers the paper's one claim. Everything else goes to the
appendix.

- **Rows**: the methods being compared, with the proposed method last so the
  eye lands on it after the baselines.
- **Columns**: the metrics the claim is about. Adding metrics the claim does
  not concern dilutes it and invites reviewers to find a column where you lose.
- **Baselines**: the strongest available, not the most convenient. A table
  whose baselines are weak reads as a weak result regardless of the margin.
- **Ablations**: in the main table only if the claim is about the mechanism.

## Reporting uncertainty

State what the spread means, every time. `0.74 ± 0.03` is meaningless without
knowing whether that is a standard deviation, a standard error, or a confidence
interval, and over how many seeds.

- Give **n** (seeds or folds) in the caption or a column.
- Say which dispersion measure you used. NeurIPS and ICML both ask for this
  explicitly — see the `venue-checklist` skill.
- A single run has no error bar. Report it as a single run and say so; do not
  present it in a format that implies replication.
- Bold the best result only if the margin exceeds the spread. Bolding a
  within-noise win is the most common quiet overclaim in a results table.

## Captions that stand alone

Reviewers read figures and tables before the body. The caption must carry:
what is being compared, on what data, with what metric, over how many runs, and
what the reader should conclude. "Table 2: Results." fails all five.

Good: *"Table 2: Accuracy on the held-out split of BENCHMARK, mean ± standard
deviation over 5 seeds. Retrieval recovers 12 points that long-context
prompting loses when the relevant evidence is diffuse."*

## Figures

The same rules apply, plus:

- In markdown output mode, figures must be `.png` (or another renderable
  raster format) under `report/images/` and embedded with a
  report-relative path — `![Caption](images/name.png)`. A `.pdf` figure shows
  the report viewer nothing, and the Stage 07 gate rejects it.
- In LaTeX mode, figures live in `workspace/figures/` and are included with a
  path relative to `main.tex`.
- Every figure referenced in prose must exist, and every figure that exists
  should be referenced. An unreferenced figure is either dead weight or a
  missing paragraph.

## Before you finish

- Every number in the table traces to a file under `workspace/results/`.
- The dispersion measure and the number of runs are stated.
- Nothing is bolded that is within noise.
- Each caption is readable with the body text covered up.
