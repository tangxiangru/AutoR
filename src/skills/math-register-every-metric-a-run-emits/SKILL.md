---
name: math-register-every-metric-a-run-emits
description: Use at study design when cells are about to be chosen on a binary per-run outcome - solved / converged / correct / within tolerance - and the same runs also emit continuous quantities. Covers the metric register, recording every row on failed and timed-out runs, sizing n from a two-instance paired pilot instead of from the rate, and per-cell paired reporting with both averaging conventions.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Register every metric a run emits, then choose cells to cover the register

## The two facts this skill exists for

1. **A run that fails still produces the continuous metrics.** A run that solved nothing has a
   final residual, a count of remaining violations, a best incumbent objective, an iteration
   count and a wall clock. Recording the outcome as `False` and discarding the rest throws away
   a measurement you already paid the solver for, and it is what turns a floored cell into an
   empty cell.
2. **A paired continuous difference resolves at a fraction of the n a rate needs.** Ten points of
   separation in a binary rate needs n in the hundreds. The same two arms compared on a
   continuous quantity, instance by instance, usually separate at n of 5 to 10, because the
   pairing removes the instance-to-instance variance that dominates the rate.

Together they say that a cell's informativeness is per metric, not per cell. A cell can be
worthless for the headline rate - every arm floored, every arm saturated, or the arms tied - and
be the cleanest cell in the study for something else. Check what the continuous metrics do there
before you drop it.

## What goes wrong

The headline metric is binary per run: solved / converged / correct / within tolerance. It is the
one the source's headline table reports, so it becomes the metric the *plan* is argued in. A
power calculation over that rate ranks the cells, the top cell is declared primary, and the rest
are skipped as uninformative.

The rate is the coarsest possible read of a run, and it is the one metric that is guaranteed to
be uninformative wherever the problem is too hard or too easy for every arm. Selecting cells by
it systematically discards the regime where a source's *secondary* claims live - the mechanism
claims, the "why it works" claims - because those are precisely the claims the authors made with
a continuous quantity in a place where the rate had nothing to say.

## The metric register

At study design, before cells are chosen, write one row per metric the report will state:

| metric | per-run type | emitted by the code where | present on a failed run? | paired? | n to resolve |

Rules for filling it:

- **Type.** binary / count / continuous / time. Anything the report will put a number on gets a
  row, including quantities you think of as diagnostics.
- **Emitted where.** Name the variable or the log line. If a metric is computed inside the solver
  and thrown away at the boundary, that is a one-line change and you make it now, not after the
  first full pass.
- **Present on a failed run.** Answer honestly. If the answer is no and it could be yes cheaply,
  change the code before the first real run.
- **n to resolve.** For the rate, from a two-proportion or McNemar calculation. For each
  continuous metric, from the paired standard deviation of a **two-instance pilot** - not from
  the rate's number, which is the wrong scale by an order of magnitude and is what makes cheap
  cells look unaffordable.

Then choose cells to cover the register, not to maximise one row of it.

## At experimentation

Log every register row on every run: failed runs, timed-out arms, probe-only cells, the arms you
ran twice by accident. It is free - the solver already computed them - and it is unrecoverable
later.

Persist **per-instance records**, not cell means. Pairing, the commonly-solved subset, the
re-thresholding to a shorter limit and the dispersion all need the per-instance rows; a table of
means supports none of them and cannot be un-averaged.

## At analysis

- One row per cell per arm per metric, including the cells where the rate ties, floors or
  saturates. The tied cell is a result: same rate, different continuous behaviour, is a
  mechanism finding and the strongest use of a cheap cell.
- Report each continuous metric as a **paired change against the incumbent, per cell, with its n
  and its dispersion** - not as two independent cell means with the reader left to subtract.
  State the sign convention once, in the caption.
- Report both averaging conventions when they differ: each arm averaged over its own successes,
  and the subset of instances every arm solved. The stronger arm solves harder instances and is
  penalised by its own success under the first convention. When the two disagree in sign, that
  disagreement is a selection effect and is worth a sentence.
- No pooled aggregate as the primary object. Per-cell values are the result; pooling hides sign
  reversals between cells and the reader cannot un-pool it.

Pairing a quality metric with the cost metric for the same comparison, and giving the break-even
factor, is already required by `math-equal-effort-baselines-and-knob-sweeps`; the register is
what guarantees both members of the pair were recorded on every run rather than one of them at
one cell.

## Checklist

- [ ] Does the register have a row for every quantity the report will state?
- [ ] For each row: is it emitted on unsolved and timed-out runs? If not, did I fix that before
      the first real run?
- [ ] Was any cell dropped because the *binary* rate there is tied, floored or saturated? What do
      the continuous rows do there?
- [ ] Is each continuous n sized from a paired pilot, or inherited from the rate's calculation?
- [ ] Are records persisted per instance, so pairing and the commonly-solved subset survive to
      analysis?
- [ ] Is every continuous comparison reported per cell, paired, with n and dispersion?

## Anti-patterns

- Reporting the continuous metrics only at the cell that was selected on the rate. That cell was
  chosen by the wrong criterion for them.
- Treating a metric as unavailable because the run failed, when the solver printed it.
- Averaging each arm over its own successes and presenting that alone as the comparison.
- A single pooled number per metric over all cells, with the per-cell values only in a supplement
  or not at all.
