---
name: a-model-you-can-audit-is-not-a-model-that-scores
description: Use at study design and implementation when choosing between a method you can validate quickly and a stronger one you are not sure you can afford. Covers pricing the expensive method with a measurement instead of an impression, the go/no-go that has to be written before the clock is spent, and why the safe choice is only safe on the axes nobody is grading.
applies_when: predictions will be scored
stages: 03_study_design, 04_implementation, 05_experimentation
---

# The auditable method wins the argument and loses the score

Given a fixed clock and a scored predictions file, there is a recurring choice
between two methods:

- one you can build in twenty minutes, cross-validate cleanly, explain fully, and
  defend against every question a reviewer asks;
- one the field actually uses to get the published number, which needs an hour of
  setup you have not done, has failure modes you cannot fully enumerate, and might
  not finish.

Every incentive inside a rigour-checking pipeline points at the first. The gates
reward an auditable choice. The reviewer is easier to satisfy. The write-up is
cleaner. And on a benchmark that grades predictions, none of that is measured.

Measured on a scored arm: the pipeline shipped a gradient-boosted tree on hand-built
features, with a set of scripts beside it named for what they audited — the
train/test alignment, the units, the row alignment, the submission state. The
control arm, on the same task with the same clock, wrote a graph network. The
control won by a fifth of the normalized range.

## Price it; do not judge it

The decision is not "is the expensive method better" — you already know it is. It
is "does it fit". That is a measurement, and it takes ten minutes:

1. **Run one unit of it.** One epoch on 1% of the data, or one forward pass on one
   batch, timed. Not an estimate from experience; the actual wall clock on this
   machine, which is the only one whose speed matters.
2. **Extrapolate to the full fit.** Epochs × data multiple × the unit. Add 50% for
   the things a first run does not do.
3. **Compare against the clock you have left**, minus a reserve for writing and
   checking the submission.
4. **Write the go/no-go down with both numbers in it.** Two lines is enough:
   "one epoch on 1% took 42 s → full fit ≈ 70 min; 150 min remain after reserve;
   go."

Step 4 is what makes this different from deciding by feel. A run that has written
the estimate can revisit it when the clock moves; a run that has only an
impression will re-litigate the same choice three times and act on none of them.

## Make the expensive method safe rather than avoiding it

Most of what makes the strong method feel unaffordable is recoverable:

- **Checkpoint every epoch and write a submission from the best checkpoint so far.**
  Then a training run that is killed by the clock has still contributed, and the
  downside of trying is bounded by the time, not by the outcome.
- **Start it in the background and keep the foreground on the cheap method.** The
  two do not compete for your attention, only for CPU, and the cheap one is
  already your floor.
- **Fix the seed and the split before the first fit**, so a later comparison
  between the two methods is a comparison and not a coincidence.

With those three, "try the strong method" costs you the wall clock and nothing
else. Without them it risks the deliverable, which is what makes the conservative
choice feel correct.

## The tell

You are on the wrong side of this when your validation number has stopped moving
and your file count has not. Four more feature-engineering scripts against a
plateau is the shape of a run that has decided, without saying so, that the method
is fixed. If the method is fixed and the number is short of the ladder, the run
has already ended; the remaining hours are spent on the record.
