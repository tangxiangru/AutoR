---
name: a-null-test-bounds-the-instrument-not-the-answer
description: Use at analysis and again at writing whenever you run a permutation, shuffle, placebo, unforced-control or power test against your own headline result, especially when it comes back saying the result is not distinguishable from noise. Covers giving every condition the task names its own value line and stating the relation across them as a result, keeping the estimate and the bound as two results with two different subjects, and the sentence order that stops a bound replacing the answer.
stages: 06_analysis, 07_writing
---

# Give every condition its value line, then bound it

## The spine

For every condition the task names — every scenario, arm, dose, cohort, model,
regime — the report carries one line of this shape:

    condition: value [interval] vs reference value, gap

Including conditions you could only reach by derivation, interpolation or
borrowing. A derived condition gets its line with the derivation named in the
same clause. It does not get a footnote in place of a number.

Then, in its own sentence, **the relation across conditions, stated as a
result**: the ordering, the monotonicity, the crossing — whichever relation the
task's comparison is about. Over all the conditions the task named, not the
subset your claim structure happened to scope.

This is where runs holding correct numbers lose. The results file has the values
in the right relation; the preregistration scoped the ordering claim to a subset
because one condition arrived late or by derivation; and the report never states
the full relation anywhere. The relation is a separate result from the values,
and having the values on disk is not stating it. A condition your hypothesis
excluded is still a condition the task asked about.

`reproduce-then-extend` owns the shape of the published-versus-ours table these
lines live in. Do not restate it; fill it.

## Two results with two different subjects

Building a no-signal null against your own criterion — permuting the labels that
carry the contrast, an unforced control run, a placebo condition, a
within-population split — is right, and most runs never do it. Then it comes back
saying your headline sits inside it, and the run has to decide what that means.

It means two things, and the loss is in fusing them.

- **The estimate.** "Under condition C, X% of the population falls in the high
  class, interval [l, u], against a published Y%." Subject: the world.
- **The bound.** "At this sample size, window length and threshold, the same
  criterion returns Z ± s from labels carrying no signal." Subject: your
  instrument.

The bound does not delete the estimate. It says how much of the estimate is
attributable to signal. Fuse them and you publish a verdict where the task asked
for a quantity, and a reader looking for the number finds a non-result.

## At analysis

1. Keep the two in separate artifacts with separate decision rules. The null's
   verdict never overwrites the estimate's field.
2. Choose the null that matches the claim, and say why. Where the field has a
   standard no-signal instrument — an unforced control run, a scrambled decoy
   set, a permutation over a held-out population — prefer it to one you invented.
   A permutation *within* the same sample confounds internal variability with the
   effect and is the widest, least informative null available.
3. Calibrate it before believing it. Run it on a case known to carry signal. A
   null that also swallows that case is measuring its own width, and that is a
   finding about your criterion rather than about your result.
4. Express it as a quantity in the headline's units: the false-positive floor,
   the configuration that produced it, and — if one more run is affordable — the
   sample size, window or threshold at which the result would clear. A floor with
   a number is a contribution. "Not significant" is a label.
5. Name the construction feature that produces the floor: a ratio threshold at
   small counts, a floor near the quantisation step, a fixed denominator. Show
   the sweep, so a reader can tell whether the floor belongs to your
   reconstruction or to the published method.
6. Separate "no power to detect" from "no effect". They imply opposite next
   actions. State which one your evidence supports, and what would distinguish
   them.

## At writing: the order inside the sentence

The bound is not banned from the abstract, the title or the conclusion. A run can
lead with its noise floor and still read as having answered — provided that
everywhere the reader meets the quantity, **the requested value comes first in
the sentence and the bound comes second, in the same sentence.** Estimate, then
bound. Never bound alone.

What loses is the reverse order, and substitution:

- a sentence whose subject is the verdict and whose object is the value;
- a verdict standing where the value should be, with the value deferred;
- the caveat re-attached to quantities the null was never computed for.

The third is a correctness problem, not a matter of tone. A bound is computed for
specific quantities under a specific configuration. Restating it over a regional
breakdown, a downstream comparison or a secondary arm that never entered the null
asserts something you did not measure. Attach it where it was computed;
elsewhere, cross-reference it.

If the null is the most interesting thing the run found, it is an *additional*
result. The conclusion still opens with what the task asked for.

## The checks

- One value line per condition the task names. A missing line is a missing
  result, and a caveat does not substitute for it.
- The relation across conditions is written as a sentence, early, and covers
  every condition — including the derived ones.
- Read the first results sentence of the abstract. Is the first quantity in it
  the one the task asked for, or is it a p-value or an interpolation error?
- Grep for the bound's label. Every occurrence outside its own section is either
  a cross-reference or a quantity the null was actually computed for.
