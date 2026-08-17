---
name: energy-inject-the-defect-the-algorithm-claims-to-fix
description: Use at hypothesis generation, study design and experimentation when the deliverable includes a data-repair algorithm - cleaning, imputation, outlier correction, gap filling, denoising - and especially when the supplied file turns out to hold little for it to repair. Covers injecting the defects the algorithm names into a leaf unit held as truth, scoring recovery per stage in physical units, and checking what the repair did to the downstream object.
stages: 02_hypothesis_generation, 03_study_design, 05_experimentation
---

# Inject the defect the algorithm claims to fix, then score the recovery

## What goes wrong

The task names a repair algorithm among its outputs. You count what it would act
on in the supplied file and find little or nothing - few gaps, no sentinels, no
obvious spikes. You run the published rule over it, it changes almost nothing,
and you write the true sentence - *the algorithm is inert on this file* - and
move on to something you can measure.

That sentence is a property of the file, not a validation of the algorithm. A
repair algorithm can only be scored where the truth is known, and on a clean file
the truth is known everywhere. Inertness is the cue to manufacture the defects,
not a reason to stop.

The near-miss version costs just as much and looks finished. A run injects **one**
of the defect types (gaps), on the **aggregate** node, scores a **normalised**
error, plots error against gap length, and never runs the algorithm's later
stages, never touches a leaf unit, and never checks what the repair did to the
analysis the data exists for. Four fragments, no experiment.

## What to produce

One injection-recovery experiment, on one named leaf unit of the supplied
archive, scored at two levels, in one panel. Declare it at hypothesis and design
time as its own line item - not as a clause of a hypothesis about something else
- and give it a figure slot before any diagnostic of your own claims one.

## Checklist

1. **Enumerate the defects the algorithm names.** One row per stage: stage name,
   the defect it treats, its published parameters (window, multiplier, k,
   epsilon, tolerance), and whether a released implementation exists. Every named
   stage is a row, an arm, and its own recovery number; a stage with no released
   code is implemented from the prose at the source's stated parameters and
   labelled as such, not skipped.
2. **Count how many of each defect the supplied file already contains,** and
   report the counts. If they are zero, that is the trigger for step 4, and you
   say so in the report.
3. **Pick the unit before you see a result, from the supplied archive.** A leaf
   entity - one building, one site, one sensor - under the identifier the shipped
   archive gives it, with a complete series over the supplied period. Take the
   first leaf in the archive's own listing order and record that as the selection
   rule; choosing afterwards selects the exhibit on the outcome. Two prohibitions:
   do not run this on an aggregate, because a sum over many leaves averages away
   exactly the corruption the algorithm treats; and if you have also obtained a
   larger or longer release of the same data, this experiment still runs on the
   supplied file, because that is the file the task's questions are written about
   (`the-supplied-item-is-the-graded-unit`). A wider release is an extra arm,
   never the substitute.
4. **Freeze the untouched series as truth and inject every defect type at once.**
   State a rate for each type separately (the source's rates when it gives them,
   otherwise a small stated rate per type), the seed, and the injection model -
   MCAR cells or blocks for missingness, multiplicative or additive spikes from a
   stated distribution for outliers. Write the injected mask to `outputs/` so the
   scored cells are auditable. Inject into the truth series, never into the
   algorithm's own output.
5. **Run the stages in the order the source composes them,** recording after each:
   cells touched, cells changed, cells still wrong. Per-stage numbers are how a
   reader learns which stage does the work.
6. **Score at the cell, in the carrier's own unit.** MAE and RMSE over the injected
   cells only, in the unit the column header names - not normalised, not
   dimensionless - beside two references: the corrupted-and-uncleaned
   baseline, and one trivial comparator (linear interpolation, seasonal
   persistence, rolling median). The headline sentence is a percentage reduction
   against the corrupted baseline with both absolute values in it. Report the
   recovered fraction of injected cells as well: an imputer that declines to fill
   scores a flattering error on the cells it did fill.
7. **Score downstream, at the level the data is used.** Recompute the object the
   task's stated goal names - daily-profile clusters at the source's own settings,
   the correlation matrix, a forecast error - twice, on truth and on the cleaned
   series, and overlay them. A cleaner can hit a small cell-level error and still
   move the structure; structure that survives is the stronger claim.
8. **One panel, printed with its numbers, and the same numbers in prose.** Truth,
   corrupted and cleaned on shared axes over a readable window of the named unit;
   the downstream object before and after beside it; the unit's identifier in the
   panel title; MAE, RMSE, both injection rates and n printed on the image, so the
   panel is scoreable without the body text. Then write those same values into the
   results section, because a report's figures are read as a bounded prefix in
   document order and a panel far down the list may never be opened. Adding a
   panel without deleting one lowers the odds for every other exhibit, so this one
   displaces a diagnostic rather than joining them.
9. **Then report what the algorithm does on the uncorrupted file** - inert,
   deleting, rewriting - with its cell counts, as a second result placed after the
   recovery figure. Both are findings; only one of them is the validation.

## Before you finish

For each stage in the step-1 table, find in the report: the injected rate, the
unit it was injected into, the post-repair error in physical units, and one
sentence naming what that stage recovered. A stage with no row is a stage nobody
ran.
