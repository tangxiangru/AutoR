---
name: every-variant-persists-the-same-object
description: Use at implementation when you write the routine that reduces a scan to a scalar, at experimentation when the sweep over alternative treatments runs, and at writing before any comparison figure is finalised. Covers persisting the full curve for every variant on a shared grid rather than only its threshold crossings, why a ragged results file makes the field's comparison figure undrawable after the compute is gone, and diffing the rendered image against the plan slot that named it.
stages: 04_implementation, 05_experimentation, 07_writing
---

# Every variant persists the same object

**Upstream of the figure skills.** `astronomy-figure-is-the-unit-of-result` and
`draw-the-source-figure-panel-for-panel` say what the comparison figure must
contain: every competing treatment of one quantity overlaid on a single set of
axes, over the full scanned range, with the decision threshold drawn as a
labelled line. Neither is executable at writing time if the curves are not on
disk, and by then the sweep is over. This skill is about what the analysis writes
down, so that they are.

## What goes wrong

You compute one quantity under several treatments of the input: the full
distribution, a Gaussian approximation, an uncorrelated version, a coarse
interval, a point estimate, a larger or smaller model space. For each you scan a
parameter and reduce the scan to the thing you actually want — where the curve
crosses a threshold, the interval it excludes, the argmax, the first failure
point.

The reduction is correct, and it is what you persist. For the primary treatment
you also keep the underlying trace, because you plotted it while debugging. For
the alternatives you keep the reduced scalars only, because that is all the
comparison table needs.

Nothing errors. The results file ends up with ragged keys — one entry carrying an
array, the rest carrying pairs of numbers — and no counter anywhere records that.
At writing time the figure the field expects cannot be drawn from what exists, so
the alternatives degrade into a bar chart of scalar displacements beside a single
curve, and the panel quietly changes what it is a figure of. Re-running the sweep
is not affordable at that point in the run.

Two things are then unrecoverable for the reader: the **shape** of each
alternative — whether it degrades gradually or catastrophically, whether it has a
second feature elsewhere in the domain, whether it is flat where you claim it is
informative — and the **rest of the domain**, which is the only evidence that
your scan was wide enough to contain the answer.

## The rule

One schema for every variant of one computation.

- Fix a deterministic grid over the whole domain you intend to scan, before the
  sweep runs. Record its endpoints and spacing once, in the results file.
- Evaluate every variant on that grid, including the ones your estimator can
  answer analytically without a grid. An exact crossing point is cheaper and is
  not a substitute; keep both.
- Persist the whole array per variant — `.npz`, a CSV column, a JSON list — under
  the same key as the primary carries. Name variants at persist time the way the
  field names them, so the legend does not have to be reinvented later.
- Include the degenerate treatments as variants: the crudest summary of the
  input, the naive approximation, the no-model baseline. They cost almost nothing
  and they carry the argument for why the careful treatment was worth doing.

## A name-matched completeness check is not a check

The same run usually has a coverage gate — a plan, a deliverables list, a slot
per figure. If that gate matches on a heading string and an image filename, it
goes green on a figure that contradicts the plan slot that named it: the file
exists, the heading is present, and nothing opened either. Existence checks pass
on the wrong artifact.

Whatever sentence you wrote to declare a figure is a falsifiable statement about
a PNG. Re-read it and diff it against the rendered image clause by clause: number
of series, what each series is, the x-range, whether the threshold line is drawn
and labelled, whether anything declared as a curve came out as a bar. It costs a
minute, and it is the only step that catches a plan violated by the plotting
code.

## Checklist

Implementation and experimentation:

1. After the sweep, load the results file and print the key set per variant.
   Assert the sets are equal. Ragged keys are the defect and this is the whole
   test; write it as an assertion, not as an intention.
2. Draw one throwaway overlay of every variant **from the persisted file alone**,
   in a fresh interpreter. If you cannot, the file is incomplete and the sweep is
   still cheap to re-run.
3. Set the scanned domain from the question and the physics, before you know
   where the feature is.

Writing:

4. Axis limits come from the domain you scanned, including the saturated regions
   at both ends. If a feature runs off the edge of the plotted range, the scan
   was too narrow — widen it and re-run rather than cropping.
5. Anything you can only draw as a bar, an arrow or an annotated displacement is
   a variant whose curve was not saved. If it cannot be fixed, say so in the
   caption so the bar is not read as the comparison.
6. No panel of a results figure is a block of prose. A panel listing headline
   numbers is a table occupying a panel's space; move it and give the space back
   to the curves.
