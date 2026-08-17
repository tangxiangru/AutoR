---
name: material-same-estimator-same-slot
description: Use at the literature survey when you recompute a statistic out of the source's own tables, and again at analysis and writing when a reproduction result is being placed in a figure, a caption and a table. Covers republishing the source's summary statistic in the source's own estimator, set and n, sweeping the literature-stage artifacts for statistics that never reached the draft, and giving the reproduction the panel position and caption clause the audit tends to take. Extends material-as-specified-run-and-stage-diagnostics.
stages: 01_literature_survey, 06_analysis, 07_writing
---

# Same estimator, same slot

This extends `material-as-specified-run-and-stage-diagnostics`, which says the
audit of a defective spec may not take the title, the abstract's first sentence
or panel (a). It adds the two things that skill leaves unsaid: what *form* the
source's number has to come back in, and what "panel (a)" means physically.

## The two failures

**The statistic changes form on the way into the report.** The source publishes
a summary statistic over its own set — a mean absolute error over N benchmark
cases, a mean absolute deviation in meV/atom, an RMS across sites. Your
literature stage recovers it, parses the underlying table, validates the parse,
and writes the recomputed value into an intermediate artifact. The report then
publishes a different reduction of the same rows: a signed mean, an RMSE, a
per-item table left for the reader to reduce, or your own error against the
handful of cases that were shipped to you. Every number in the report is
correct. The one a reader checks a reproduction with is not there. This failure
hides itself, because the same digits usually do appear somewhere in the
document attached to a different quantity, so searching for the value finds a
hit.

**The reproduction is drawn and then buried.** You reproduce the source's figure
well — same entities, same ordering, values that match — and place it as the
third panel of a composite at a third the width, on an axis range stretched by a
neighbouring panel's outliers, under a caption whose first clause explains why
the inputs behind it are unsound. Position, size and caption polarity are read
before content is, and a correct reproduction in that position reads as a
reproduction you declined to do.

## What to do

**Stage 01 — record the statistic as a form, not as a value.** For every summary
statistic the source publishes that your task touches, write one row: estimator
name, set, n, unit, the value as the source states it, your recomputation from
the underlying table where the table is available, and the check that validated
your parse (a column the source also publishes, which your recomputation must
reproduce row by row). Mark each row *to publish*. That file is a publication
queue, not a note.

**Stage 06 — recompute in the source's own form.** Same estimator, same set,
same n, same unit. Do not upgrade the statistic because you prefer a different
one, and do not report a signed quantity where the source reported a magnitude:
they answer different questions and the substitution is invisible to you and
obvious to a reader. Then:

- If you can only run part of the set, restrict the source's statistic to the
  same part and report both, with both n's stated.
- If the set cannot be rebuilt at all, republish the source's own value with its
  n, attributed, and say your run does not contest it. A source statistic
  reported as the source's is still the anchor the reader wanted; an absent one
  is an experiment not done.
- Where you have your own version, put them in one row:

  | statistic (estimator, set, n) | source | this run | difference |

**Before you ship — sweep the literature artifacts, not only the run outputs.**
`publish-what-the-run-already-computed` sweeps what the run computed. This is the
other pile, and it is missed more often, because a number recovered from a paper
feels like background rather than a result. Open every literature-stage artifact,
list each numeric field you recomputed or validated there, and grep the draft for
it. Absent means not reported. Present only as some other quantity's value is
worse than absent: it makes the missing statistic look present to you and to
nobody else.

**Stage 07 — slot geometry.** For each result the task names:

- it is figure 1, or panel (a) of figure 1: first position, full width, axis
  range chosen so the compared quantities fill the panel;
- the caption's first clause states the comparison and its outcome, in the
  source's units, with the source's value and yours both printed;
- a defect in the supplied inputs comes after that clause, quantified against the
  protocol's own threshold in the protocol's own units — "residual forces of X
  against the Y the protocol's convergence criterion states", not "these inputs
  are unusable";
- the number the defective inputs give is still reported, because that is what
  the named experiment measured;
- a multi-panel composite is an addition. A named result appears once at full
  size on its own before it appears as somebody's panel (c).

## Checklist

- [ ] Every source statistic your task touches has a row with estimator, set, n
      and unit, written at the literature stage.
- [ ] Each is republished in the source's own estimator, or explicitly deferred
      to the source's value with attribution.
- [ ] No signed mean, RMSE or per-item table stands in for a published magnitude.
- [ ] The draft has been grepped for every value the literature stage recomputed.
- [ ] No value appears in the report under a quantity it does not belong to.
- [ ] Each named result is first position, full width, in its own figure.
- [ ] Every caption's first clause is the comparison, not the complaint.
- [ ] Every complaint is a number against the protocol's own threshold.
