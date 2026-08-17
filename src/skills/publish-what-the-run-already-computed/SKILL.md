---
name: publish-what-the-run-already-computed
description: Use at Stage 06 and before finalising the report, when deciding which of the run's results enter the deliverable. Covers the sweep that finds objects and numbers the run computed and never published, why the report's contents get chosen by the run's own hypotheses instead of by the task, and what to promote out of an appendix.
---

# The most expensive result is the one you computed and did not show

There is a failure that costs more than any experiment that went wrong, and it
leaves no trace in the logs: the run produces exactly the object the task asked
for, writes it to a file, and then does not put it in the report. The work was
done. The compute was spent. The deliverable is on disk. The reader is told a
summary statistic about it instead.

It happens because the report gets its contents from the run's own hypothesis
structure — the questions the run decided to ask — rather than from the task's
list of outputs. Every section then answers a hypothesis, and an object that was
produced in service of a hypothesis but is not itself a hypothesis has no section
to live in. It ends in `outputs/`, or in an appendix table nobody analyses.

## The sweep

Before you fix a section order or polish a sentence, do this once:

1. List every file the run wrote under the results and outputs directories, with
   what it holds — not the path, the *content*: "the final derived Hamiltonian for
   the shipped system", "per-epoch pre-training loss", "sequence identity per
   aligned chain pair", "the 497-row permutation-importance table".
2. Against each, write the section of the report where it appears. Grep the report
   for a number out of the file; if no number from it is in the report, the entry
   is empty.
3. For every empty entry, answer one question: **is this one of the objects the
   task named as an output?** If yes, it goes in the body, in its own subsection,
   before you do anything else. If no, it may stay unpublished.

The sweep takes minutes and it is the highest-yield thing available at this point
in the run, because everything it finds is already paid for.

## The three shapes it finds

**The object reduced to a statistic.** The task asks for derived Hamiltonians;
the run derives one hundred and sixty-nine of them and reports the fraction that
graded correct. The percentage is a measurement *about* the deliverable. It is not
the deliverable. Show at least one instance of the object in full, in the body, in
the form the task named — the equation, the table, the sequence, the structure —
and put the aggregate next to it.

**The diagnostic that was never drawn.** A training routine accumulates loss per
epoch, returns it, and writes it nowhere; the convergence curve the source paper
made its case with is then absent from a run that had the data in memory. Any
quantity the source study plots is a quantity worth persisting the moment it is
computed, even when your own argument does not need it.

**The column that was requested and dropped.** A tool is asked for an extra field,
the field lands in a CSV, and the report quotes everything from that CSV except
that column. If you asked a tool for it, some part of the run thought it mattered.

## Promote out of the appendix

An object tabulated in an appendix and never analysed is half-published. If it is
a named deliverable, it gets a body subsection, a sentence of interpretation and,
where the shape allows, a figure. Where a table has structure worth a statistic —
nine superposition vectors have a dispersion; a set of per-pair scores has a
distribution — computing it is a handful of lines and turns a dump into a result.

## What this is not

This is not a licence to publish everything. Bulk arrays, intermediate caches, and
per-row dumps belong exactly where they are. The test is the task's own list of
outputs: an object the task named belongs in the body; everything else is judged
on whether it carries an argument.

See also `cover-what-the-task-named` for building the list this sweep checks
against, and `result-table` for the shape an object takes once it is in the body.
