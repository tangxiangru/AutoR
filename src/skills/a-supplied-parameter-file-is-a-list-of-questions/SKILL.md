---
name: a-supplied-parameter-file-is-a-list-of-questions
description: Use at study design, analysis and writing when the task ships a small file of named constants, ranges, entity tables, case lists or run settings. Covers treating each entry as a question your run must answer in the file's own labels and units — including entries your own audit shows are wrong — and why an agreement count is not an answer.
stages: 03_study_design, 06_analysis, 07_writing
---

# A shipped parameter file is a list of questions, not a source to trust or discard

A small file in `data/` that reads like a dump of settings — named constants,
per-case or per-transition values, acceptance windows, a table of entity pairs,
a list of starting configurations, precomputed summary counts — is not raw data
and it is not documentation. It is the list of quantities somebody expects your
report to contain, written in that person's own labels. Reproducing more of the
upstream source than the file covers does not answer them.

This is the row-level companion to `the-supplied-item-is-the-graded-unit`. That
skill is about one named *object* keeping its own subsection and its own numbers.
This one is about a file whose every entry is a separate claim, where the unit is
the entry, and about what to do with entries your own audit shows are wrong.
`run-the-conditions-the-source-ran` indexes the *source paper's* named
experiments; the conditions in this file are ones the run may already have
dismissed, which is exactly why that skill does not fire on them.

## What goes wrong

A run opens the shipped file, recomputes each block, and finds several blocks
wrong: a compatibility or property column that recomputation contradicts and that
in places carries the wrong sign; a named composite whose size is not admissible
under the theory; a summary-statistics block whose counts reproduce the weights
printed beside them to the digit, with no sampling noise in any cell. The run
concludes the file is a generated companion rather than the study's data, refuses
to anchor on it, goes upstream to the real source's data release, and reproduces
that — more of the paper than any comparator recovers.

Its report then contains no value from any block of the shipped file. The
per-case optima the file names are never printed. The entity pairs it names are
recomputed under a better convention, disagreed with, and published as different
numbers under different labels. The starting configurations it names are audited
and never run. The whole file gets one paragraph in Methods.

Every particular of that audit was correct. Two different questions had been
collapsed into one. *Is this value correct?* is an audit, and the audit answered
it. *What is this value?* is a result, and nothing answered it. A comparator that
does weaker science, runs the same audit, reaches the same verdicts, and still
tabulates its own value beside each supplied one beats that run on every
requirement written from the file's contents.

## What to produce

**Stage 03 — parse the file into a claim ledger.** With code, not by eye, write
`notes/supplied_claims.json`, one row per *entry*, not per block:

| field | content |
|---|---|
| `block` | the block or section name as written in the file |
| `label` | the entry's own key, verbatim — the case name, the pair, the step type |
| `supplied` | the value as shipped, with its unit if one is stated |
| `kind` | `constant` / `range` / `sequence` / `case` / `condition` |
| `counterpart` | which planned computation of yours produces the same quantity |
| `mine` | blank until Stage 06 |
| `verdict` | blank until Stage 06 |

A block with no counterpart in your plan is a hole in the plan. Add the
computation, or write one sentence saying why that quantity is out of scope. Do
not leave a row unpaired.

**Stage 03 — the `case` and `condition` rows are experiments.** A seed structure,
a named composite, a run sequence, a temperature-and-rate setting is a condition
to execute, not a number to check. Put one row in the experiment grid per such
entry, before any variant of your own is costed. Where the entry as written is
unphysical, run it as written *and* run the corrected version, and report the
pair; that is a stronger result than the correction alone.

**Stage 06 — fill `mine` with a value, never with an error.** The counterpart
goes in the same unit and under the same label as the supplied entry. A residual,
a pass/fail, a tolerance flag, a rank or a count is not a counterpart. If your
quantity is only defined under a convention different from the file's, give it
under both.

**Stage 07 — the ledger is a Results table.** Columns: label, supplied, this run,
verdict. One row per entry, in the file's own order, placed where the
corresponding science is discussed. A data-provenance appendix is not that place;
a reader looking for a quantity looks in the section about that quantity.

## The aggregate clause

"N of M published values reproduced to within eps" is a statement about your
implementation. It is worth reporting and it says nothing about the system. It
may sit beside the table of values; it may not stand in for it. When the design
document names the primary metric as a fraction, a coverage, a hit rate or a
worst-family score, that framing propagates into every downstream deliverable —
the figure manifest, the results table, the abstract — and by Stage 07 no
sentence in the report states a value at all. Name the metric as a fraction if
you want one; name the values themselves as deliverables in the same paragraph.

Every constant that survives the audit should then appear *inside* the figure
that shows the matching result, as a labelled reference line or an annotated
point carrying its numeral, under the file's own name for it.

## When the supplied value is wrong

Print both, state the discrepancy and its size, and still give your value in the
supplied entry's own labels and units. "Contradicted" is a verdict on a row, not
permission to delete the row. If the only occurrence of a quantity in your report
is inside a list of blocks you rejected, the quantity is missing from your
report.

## Before you finish

- Every row of `supplied_claims.json` has a non-empty `mine`.
- Every `condition` row has a run, or one sentence saying why not.
- Grep the report for each `label`. Zero hits is an unanswered question.
- No quantity the task's output list names exists in the report only as a
  fraction-reproduced or a residual.
