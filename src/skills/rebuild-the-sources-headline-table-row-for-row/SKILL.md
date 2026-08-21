---
name: rebuild-the-sources-headline-table-row-for-row
description: Use at literature survey when the source's central result is a table of many benchmarks crossed with many methods, at study design to fix the row and column set and budget any data the supplied archive does not ship, and at analysis to render it. Covers transcribing the published table as the target skeleton, where the missing rows come from, shipping a table-shaped exhibit rather than a chart over the subset you ran, and marking cells you could not fill.
benchmarks: researchclawbench
stages: 01_literature_survey, 03_study_design, 06_analysis
---

# The source's headline table is a graded exhibit: rebuild it row for row

Many papers put their central claim in one table: every benchmark the study ran
down the rows, every method it compares across the columns, one value per cell
with its dispersion. That table is the object a reader lays beside your work.

The reproduction that loses runs a subset of the rows, a subset of the columns,
and then draws a grouped bar chart of whatever it managed. Read next to the
source's table, that chart answers nothing. The reader cannot find the row they
care about, cannot see the method pair the claim is about, and cannot tell a cell
you ran out of time for from a cell you never considered. The work behind the
chart may be sound and the exhibit still registers as absent.

## 1. Transcribe the published table at literature stage

Write `notes/source_tables.json`, one entry per table the task points at:

- the exact row labels in the source's order, and the exact column labels, in the
  source's own names rather than your renaming;
- every published cell value with its dispersion and units;
- which column is the proposed method, which is the conventional counterpart it is
  compared against, and how the source pairs them;
- the caption's protocol: split, number of repeats, model-selection rule.

Read this off the rendered table in the results section. A table quoted in an
abstract, a summary paragraph or an older preprint routinely carries fewer rows
and fewer columns than the published one.

That transcription is now two things at once: the skeleton of your results table,
and the cell list your campaign has to cover. Both are defined by the source, not
by what happens to be in the supplied folder.

## 2. Count the rows the archive does not ship

The supplied data folder is an input, not the row set. Diff the source's row
labels against the files you were handed. For every row with no file: find it in
the authors' release, in the benchmark suite the source names, or in the standard
public distribution, and budget the download and preprocessing at design time,
before any analysis code exists. These rows are usually the cheapest cells in the
grid, because the featuriser already exists.

A row that was one download away is the most expensive kind of absence: the reader
sees a short table and cannot tell availability from choice.

If a row genuinely cannot be obtained, it still appears, carrying the published
values and a marker saying it was not reproduced and why. Do not shorten the
table to the rows you have. `earth-comparator-set-lives-outside-the-supplied-archive`
makes this argument for comparator methods; here it applies to the rows.

## 3. The column set is the source's method list

Columns are the method families whose difference the claim is about: the proposed
method and its conventional counterpart, once per backbone or base family. A
column that profiles more expensive per run than the others is still a column, and
it runs at pass-1 fidelity like everything else.

Never ship an exhibit with a header, legend entry or hatched slot for a method
that produced no number. Either it has a value at whatever fidelity you could
afford, or the cell carries the published value marked as not reproduced, with one
sentence saying why. A labelled empty slot reads as a run that mistook an
intention for a result.

## 4. Ship it as a table, in the source's shape

- Same row order, same column order, same labels.
- Each cell carries **both** numbers: your value with its dispersion and the n it
  came from, and the published value beside or beneath it.
- Each cell carries a provenance marker: reproduced at your fidelity, reduced-N,
  published only, or not run.
- Render it as a raster image under `report/images/` in addition to printing it in
  the body. When the source's exhibit is a table, the table is graded as a
  picture, and a markdown table inside the prose is not one.
- Generate it with a script from your results file so it cannot drift.

A chart over the subset you ran can sit beside it. It cannot replace it.
`draw-the-source-figure-panel-for-panel` covers giving every source *figure* a
panel; the inversion here is that when the source's result is a table, a chart is
not a substitute for the table.

## 5. Order the prose the way the table reads

Go cell by cell and write the per-row verdict: does the sign of the source's
difference reproduce, and does the magnitude fall inside your interval. Group the
cells where it reproduces and state them first, then the cells where it does not,
with the evidence.

This is sequencing, not softening. A results section whose every heading is a way
the published claim fails leaves the reader unable to establish whether the
phenomenon appeared at all, even when the same numbers in the other order would
show that it did in some cells. Where a cell disagrees, `close-the-gap-to-the-published-number`
applies before you write it up as a finding.

## Checklist

- [ ] `notes/source_tables.json` exists with the full row and column labels and
      every published cell value.
- [ ] Rows the archive does not ship are listed with an acquisition path and a
      fetch budget, at design time, not in Limitations.
- [ ] The campaign's cell list equals rows x columns of the transcribed table.
- [ ] Every cell of the shipped exhibit has a value and a provenance marker; no
      blank labelled slots anywhere in table or figure.
- [ ] Published and reproduced values appear in the same cell.
- [ ] The exhibit exists as a rendered image, generated by script.
- [ ] Every row has a one-line verdict in the prose, reproducing cells first.

Related: `information-fill-the-whole-results-grid` for the completeness argument,
and `price-the-grid-in-wall-clock-and-fill-it-breadth-first` for affording the
cells. What is here and not there: the row and column set comes from the source's
published table including rows the archive omits, and the exhibit is shipped in
the table's own shape.
