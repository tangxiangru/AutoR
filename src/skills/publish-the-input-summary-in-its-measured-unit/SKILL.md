---
name: publish-the-input-summary-in-its-measured-unit
description: Use at implementation when the loader summarises the supplied data, at analysis when a summary statistic of the input becomes an argument to your estimator, and at writing while drafting the data section. Covers publishing dispersions in the unit the measurement was made in rather than the coordinate the estimator consumes, the scalar that reaches the page under its downstream name only, and the self-checks that catch both. Extends astronomy-error-budget-is-the-audit-trail.
benchmarks: researchclawbench
stages: 04_implementation, 06_analysis, 07_writing
---

# Publish the input summary in the unit it was measured in

**Extends `astronomy-error-budget-is-the-audit-trail`.** That skill already tells
you to characterise the supplied data before modelling — row count, central
value, dispersion, correlations between columns, units — and to report both mean
with standard deviation and median with a percentile interval, because subfields
differ on which is conventional. Runs execute that at load time, write a clean
manifest, and still lose the criterion. This is the hand-off half: the three ways
a characterisation that was measured correctly fails to reach the page.

## Three ways it disappears

**Coordinate substitution.** Your estimator does not work in the unit the
measurement was made in. It works in logs, in a normalised width, in a ratio to a
reference value, in standardised units. Whatever the estimator consumes is what
the analysis code prints, so the report quotes the dispersion as a width in the
derived coordinate. A width in a derived coordinate is not an interval: the
reader cannot invert it back to endpoints without the centre and the transform,
and nobody does that while reading. Published measurements of the same object are
quoted as value, error, unit. If your report never emits that form, your input
cannot be laid beside any external measurement of it — and neither you nor the
reader can notice that the shipped file disagrees with the source it was
extracted from.

**Renaming.** A dispersion you measured on the input becomes an argument to a
downstream formula — a tolerance, a step, a bin width, a noise term, a
convergence criterion. It then appears in the report exactly once, under the
downstream name, as a parameter of that formula. The number is physically on the
page and is unreadable as the measurement uncertainty, which is the thing that
was asked for.

**No slot.** Most runs maintain some list of headline numbers, and every entry in
it is an output of the run's own estimator. A quantity that describes the *input*
rather than the answer has nowhere to be written down, so nothing carries it from
the loader's artifact into the draft.

## What to produce

For every column of every supplied file, in the unit named in the file header or
in the source measurement:

- `value ± sd`, and the median with the endpoints of the central interval —
  endpoints, in the measured unit, not a width and not a span in a log
  coordinate.
- The derived-coordinate row beside it where your estimator needs one, never
  instead of it. A log width is a legitimate extra row and an illegitimate
  replacement.
- One clause on shape where mean and median separate by an appreciable fraction
  of the dispersion, or where the distribution runs into a hard physical
  boundary. That clause is what tells a reader whether your later Gaussian step
  was adequate.

Then the two bookkeeping rules that decide whether any of it survives:

1. **Two names per scalar.** When a summary statistic of the input is reused as
   an argument to a formula, record both in the summary artifact: what it
   measures, and what it is used as. Publish it under the measurement name where
   the input is described, and refer back to it where the formula is stated. One
   appearance under the second name only is the same as not reporting it.
2. **One input row in the headline list.** Whatever structure decides what gets
   written up — a headline-numbers file, a deliverables list, a results table —
   carries the supplied data's own characterisation as an entry in it. A quantity
   with no slot in that structure does not get written down, however well it was
   measured.

## Checklist, writing stage

- Grep the draft for `±` and for the interval form `(a, b)`. If no supplied
  measurement appears in either, the description of the input is not finished.
- Per supplied column, four boxes: central value present, dispersion present,
  both in the measured unit, interval given as endpoints.
- Every dispersion quoted in a derived coordinate has a sibling row in the
  measured unit inside the same table.
- Any number that appears in the draft only as a parameter of a formula: if it is
  also a measurement of the supplied data, add the sentence that says so, where
  the data is described.
- Take one number from the table and reproduce it with two lines of numpy against
  the shipped file. If it does not reproduce, it is not a characterisation of the
  input.

`publish-what-the-run-already-computed` is the general sweep for quantities the
run computed and never printed. This is the case that sweep misses, because a
loader artifact does not look like a result: the criterion asking for it is
usually worded as a plain request for the uncertainty on the data, and the run
has already measured it.
