---
name: publish-what-the-run-already-computed
description: Use at Stage 06 and again before the report is finalised, when deciding which of the run's results enter the deliverable. Sweeps the run's own outputs for quantities it computed and never published, and covers the three shapes that sweep finds — the diagnostic never persisted, the column requested and dropped, the feasibility measurement discarded — and what to promote out of an appendix.
---

# The most expensive result is the one you computed and did not show

The work was done. The compute was spent. The number is on disk. And the report
does not contain it — because the report's contents were chosen by the run's own
hypothesis structure, and a quantity produced in service of a hypothesis but not
adjudicating one has no section to live in.

This skill is the sweep that finds those. It is about the run's *outputs*;
`the-supplied-item-is-the-graded-unit` is about the *inputs* — the named objects
in `data/` — and covers printing those objects rather than pointing at them. Run
both. This one catches what that one cannot: a quantity nothing shipped and
nothing asked for by name, which the run computed anyway because the analysis
needed it.

## The sweep

Before you fix a section order or polish a sentence, do this once:

1. List every file the run wrote under the results and outputs directories, with
   what it *holds* — not the path, the content: "per-epoch pre-training loss",
   "sequence identity per aligned chain pair", "the 497-row permutation-importance
   table", "seconds per optimiser step for the long-range and short-range heads".
2. Against each, write the section of the report where it appears. Grep the
   report for a number out of the file; if none is there, the entry is empty.
3. For every empty entry, ask: **would a reader checking the task's outputs, or
   the source study's own results, look for this?** If yes, it goes in the body
   before you do anything else. If no, it may stay unpublished.

The sweep takes minutes and it is the highest-yield thing available at this point
in the run, because everything it finds is already paid for.

## The three shapes it finds

**The diagnostic that was never persisted.** A training routine accumulates loss
per epoch, returns it, and writes it to no artifact — so the convergence curve the
source study made its case with is absent from a run that had the numbers in
memory. Any quantity the source plots is worth persisting the moment it is
computed, even when your own argument does not need it. This one is the most
expensive because it is unrecoverable by Stage 07: there is nothing on disk to
promote.

**The column that was requested and dropped.** A tool is asked for an extra field,
the field lands in a CSV, and the report quotes everything from that CSV except
that column. If some part of the run thought to ask for it, some part of the run
thought it mattered.

**The measurement taken for a feasibility check.** Cost, timing and scaling
numbers get produced to decide whether something is affordable, then discarded
once the decision is made — on a report that trained a hundred models and says
nothing about what any of them cost.

## Promote out of the appendix

An object tabulated in an appendix and never analysed is half-published. Where a
table has structure worth a statistic — nine superposition vectors have a
dispersion, a set of per-pair scores has a distribution — computing it is a
handful of lines and turns a dump into a result.

## What this is not

Not a licence to publish everything. Bulk arrays, intermediate caches and per-row
dumps belong exactly where they are. The test is whether a reader would look for
it: an object the task named, or a quantity the source study reports, belongs in
the body; everything else is judged on whether it carries an argument.

See also `cover-what-the-task-named` for building the list this sweep checks
against, `the-supplied-item-is-the-graded-unit` for the shipped objects, and
`result-table` for the shape a promoted object takes in the body.
