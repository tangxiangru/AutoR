---
name: physics-plot-the-named-quantity-and-declare-the-calibration
description: Use at study design when each figure's dependent variable is chosen, at analysis when an unknown calibration, an arbitrary unit or an invariance argument is about to change what goes on the y-axis, and before the report is finalised. Covers keeping the task's named quantity on the primary panel, resolving an unknown absolute scale with one declared constant instead of a veto, and where bounds, ratios and normalised deficits belong.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# Physics: the named quantity owns the y-axis; declare the calibration and move on

The task's Output or Scientific Goal sentence names a quantity — "the core
extracted physical quantity is Q and its dependence on X and Y". That string is
the y-axis label of the primary panel for every experiment the task names.
Everything you derive from Q — a ratio, a normalised deficit, a bound, a
residual — is a second panel.

This extends `material-landmark-scalars-in-physical-units`, which says a
dimensionless goodness-of-fit reported in place of a physical quantity reads as
though the physical quantity was never measured. Same failure, moved from the
scalar in the text to the axis of the figure, and with the case the materials
skill does not cover: what to do when the physical scale is genuinely unknown.

## The failure this prevents

A run established two correct things about its supplied data: the quantity
carried an unknown multiplicative factor, and under a second ambiguity in the
file only scale-free statistics were exactly invariant. Both were verified by
re-measurement; neither is in doubt.

It then rebuilt every panel around scale-free surrogates. On the magnitude
panel, a bound derived from a general inequality was drawn as the measurement,
and the measured series appeared as a grey dashed line labelled *uncalibrated,
rescaled for shape only*. On the second panel, a dimensionless ratio against the
reference model. On every subsequent panel, the normalised deficit
`1 − Q/Q(0)` in place of `Q`. Its recorded reason: fixing the scale against a
published landmark would be circular.

The outcome is a defensible report in which **Q appears on no y-axis**, and a
reader looking for "Q against X" — the phrase in the task's own brief — finds a
dimensionless deficit on log axes instead. A comparator hit the identical
problem and spent three lines of its Methods on it: one global divisor, where
it came from, the interval internal evidence brackets it to, and the note that
the ratios below are unaffected by it. Then it plotted Q, and scored higher on
both items where the two reports differed.

Check the source's own axis label before you decide the scale is unusable.
Papers publish this class of quantity in arbitrary units routinely, and a
scruple that the source did not apply to its own figure is not a reason to
delete yours.

## What to produce

**At study design.** Write down the quantity the task names, in the unit the
source uses — including `a.u.` or `normalised` if that is what the source uses.
Each experiment the task names gets one panel with that label on the y-axis, its
control variable on the x-axis, both axes linear unless the source's own panel
is not, and every supplied theory curve for that quantity on the same axes.

**At analysis, when the absolute scale is unknown.** Three steps, not a veto:

1. **Fix one constant for the whole report.** State in Methods and in the
   caption how it was fixed: a published landmark, a physical bound, a
   normalisation at one stated point, unity. One constant, named once, used
   everywhere.
2. **State the interval** that internal evidence puts on it, and carry that
   interval into every absolute number you quote.
3. **Split the claims.** List which results are invariant to the constant —
   exponents, ratios, shapes, orderings, which series lies above which — and
   which are not. The invariant list is your robustness argument. It is not your
   figure.

Circularity is a property of an *inference*, not of an axis. Fixing the scale
and then claiming you have confirmed the value you fixed it with is circular;
fixing the scale, saying so, and then comparing shapes and ratios is not. If you
will adopt no external number at all, the fallback is an `a.u.` axis with every
series divided by one declared reference value taken from inside the file. It is
never the deletion of the series.

## Where the derived forms go

4. A calibration-free bound — an inequality, a floor from a general theorem, a
   limiting case — is drawn **on** the primary panel as a labelled horizontal
   line or a shaded band beside the data. It is never drawn *as* the data.
5. Ratios, normalising factors, normalised deficits and residuals are secondary
   panels, insets, or a right-hand axis. They answer "by how much", after the
   primary panel has answered "what does it look like".
6. If you invert the quantity — a deficit instead of a value, `1 − Q/Q(0)`
   instead of `Q` — the un-inverted panel still has to exist. A reader laying
   your figure beside the source's is matching shapes, and `y` and `1 − y` are
   different shapes. The transformed view is an addition to the pair, not a
   substitute for the raw one.
7. A quantity the task names that you genuinely cannot produce still gets the
   axis it would have had: plot the closest proxy you do hold, label it a proxy
   in the legend, and say in one sentence what is missing.

## The check

Before the report is finalised, list the y-axis label of every panel you are
about to ship, in one column. If the quantity the task names is not literally
one of them, your result is not plotted, whatever the report says. Then confirm
that each named experiment has at least one panel linear in both axes: a
results section that is log–log throughout is a set of slopes, not a set of
measurements.
