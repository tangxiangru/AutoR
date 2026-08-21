---
name: the-figure-plan-is-a-purchase-order
description: Use at study design when the figure or panel plan is written, at implementation, and at experimentation when compute is being allocated. Covers writing each planned panel as a row naming the file and column it will be drawn from, pricing and buying the producing steps before the robustness machinery, and taking each panel's axis from the language the task states its own decision rule in.
benchmarks: researchclawbench
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Every planned panel names the file it will be drawn from

A figure plan written at design time gets executed almost literally. The writing stage draws the
slots that are in the plan, in the order they are in the plan, and it does not add new ones —
there is no time and, by then, usually no data. So a list of panel titles written before any
result exists is not a sketch. It is the set of results the study is able to have.

Two things go wrong in that list, and both are invisible until it is too late to fix them:

1. **A panel is planned whose source data no step of the run will ever produce.** At writing time
   this is not a panel that gets skipped. It is unrecoverable: the compute is spent, the stage has
   a wall clock, and re-running the thing that would have produced it is now a different run from
   the one being reported.
2. **A panel is planned on the wrong axis.** The choice is frozen before any number exists, and
   nobody re-reads the plan, so the run ships a figure that answers a neighbouring question and
   looks close enough to the right one that nothing internal flags it.

## A plan row is not a title

A list of eleven evocative slot names is not a plan. Each row of the plan gets six fields, and
you can fill all six before you have any results:

| panel | question from the brief it answers | x axis / y axis, with units | file + column the values come from | step that writes that file | does it exist yet / what it costs |
|---|---|---|---|---|---|

The fourth and fifth fields are the load-bearing ones. "The analysis will produce it" is not a
step. If you cannot name the file and the column, you have written an intention.

## The axis comes from the language the task states its decision rule in

Most briefs state their own operating rule somewhere: keep everything above a score or probability
cut, take the top N, accept inside a tolerance, select above a property threshold. Whatever
variable that rule is written in is the x axis of the panel that reports its yield.

- Sweep the rule's own parameter across its range; do not report the single operating point.
- Draw the stated operating point as a marked line on that axis.
- Draw the trivial reference on the same panel — the pool's base rate, the level implied by class
  balance, what a random or constant selection returns — and give the ratio to it.

A curve over rank or selection size answers a neighbouring question and can look almost identical
to a curve over the rule's own variable. Only one of them is the rule you were handed. The same
applies to the metric vocabulary: every quantity the brief names in its own words has to appear
among the reported numbers, in those words. A separation, ranking or significance statistic
supplied in place of the plainly named quantity reads as the named quantity never having been
measured — report yours as well, after.

(`chemistry-canonical-units-thresholds-incumbent` and `material-landmark-scalars-in-physical-units`
cover reporting in the field's unit and turning an error distribution into a threshold success
rate. What is here is the axis of the panel, and the plan row that fixes it before any result
exists.)

## A row whose file does not exist yet is a purchase

For every row where the source file is not already on disk, name the step that will write it and
price the step: time one unit, multiply, write the number in the row. Two things fall out of
doing this at design time rather than at writing time.

**Some panels have no writer at all.** The conventional diagnostics of anything iterative or
trained — an objective or a held-out metric indexed by step or epoch — exist only if something
writes them while the loop runs. The plan is where you discover that no step in the pipeline does.
(`the-canonical-figure` and `train-the-named-architecture` cover persisting the trace itself; this
is the check that catches its absence while the run can still act on it.)

**The price is usually trivial and gets treated as though it were not.** One instrumented
reference run, measured in seconds, sits inside a robustness budget measured in core-hours. Until
both numbers are written down next to each other, the cheap one keeps losing to the expensive one
by default.

## Order the spend: deliverable panels before robustness machinery

Permutation nulls, bootstrap replicates, positive-control ladders, extra seeds, ablation grids and
hyperparameter sweeps all consume budget, and all of them feel like rigour. They are rigour applied
*to a result*. Buy every producing step in the figure plan first — including the diagnostic
re-runs that exist only to fill a panel — and spend what is left on the machinery.

A run that ships thousands of null replicates and cannot draw its own primary panel has bought
error bars for a result it never displayed.

## Re-audit the plan while the buy-back window is open

At the end of implementation, and again before the last long job launches, walk the rows and
actually open the file each one names. For every row whose file is missing, or exists without the
column:

- buy the producing step now, while there is still compute; or
- strike the row, and record in the plan what replaced it.

Doing this after the final analysis is bookkeeping. Doing it while jobs can still be launched is
the only point at which a missing panel is still a scheduling problem rather than a missing result.

## The plan is a floor, not a ceiling

Results you did not anticipate deserve slots; add them. The failure this guards against is
subtraction by silence — a slot that quietly produces nothing and is never mentioned. If a panel
cannot be drawn, say so in one sentence where it would have gone, rather than leaving the reader
to notice the gap.

## Checklist

- [ ] Every planned panel is a row with question, axes, file, column, producing step and cost.
- [ ] Any panel reporting a selection or decision rule is on the axis the rule is stated in, with
      the operating point marked and the trivial reference drawn.
- [ ] Every quantity the brief names in its own words appears among the reported numbers.
- [ ] No row's source is "the analysis will produce it" with no named step.
- [ ] Producing steps are scheduled ahead of nulls, replicates, ladders and sweeps.
- [ ] The plan was re-opened at the end of implementation and every row's file was loaded.
- [ ] Rows that cannot be filled are struck explicitly and answered in one sentence in the text.
