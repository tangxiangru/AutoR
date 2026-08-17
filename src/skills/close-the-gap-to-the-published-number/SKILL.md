---
name: close-the-gap-to-the-published-number
description: Use at Stage 05 and Stage 06 the moment a reproduction lands materially off a number the source study published — a different order of magnitude, an inverted trend, a collapsed estimate. Covers why the gap is a defect in your pipeline until you have shown otherwise, how much of the remaining budget to spend closing it, and what to write when it will not close.
stages: 05_experimentation, 06_analysis
---

# A disagreement with the published number is a bug report addressed to you

You reran the study and got 0.140 V where the paper got 0.0117 V. You have two
moves available. One is to write the discrepancy down carefully, attribute it to
a difference in setup, and move on to the next section. The other is to treat the
gap as evidence that something in your pipeline is wrong, and spend budget until
it closes or until you can name the specific thing that makes it irreducible.

The first move feels like honesty and reads as one. It is also, almost always,
wrong on the facts: a twelvefold gap against a published measurement is far more
often a bug than a boundary. And it is scored as what it is — an analysis whose
methodology is defensible and whose numbers are not.

## The rule

**A quantitative disagreement with the source is a defect with an owner until an
experiment says otherwise.** Not a limitation, not a caveat, not a scope note.
The owner is this run.

Order of magnitude matters. Treat these differently:

| gap | reading |
|---|---|
| within the source's own stated uncertainty | agreement; say so and move on |
| a factor of 1.5-3, or a shifted intercept | a parameter, a normalisation, a split, a unit |
| a factor of ten, an inverted sign, an inverted trend | a bug; nothing else does this |
| your estimator collapses to a constant or to zero | a bug; the model learnt nothing |

The last two rows are not results. A latent charge that collapses to 0.0002 e, a
curve that sits exactly on the best-constant null, a metric that declines where
the paper's improves — each of these is a pipeline that did not run, wearing the
clothes of a finding.

## Spend the budget where the gap is

Before you write the discrepancy up, run the cheap discriminators. Most gaps die
to one of them:

1. **Units and normalisation.** Per-atom versus total, eV versus kcal/mol, RMSE
   versus MSE, percentage versus fraction. Recompute the published number in your
   units by hand, once, on paper.
2. **The split and the population.** Did they report on the test set, the whole
   set, or a curated subset? Are you scoring the same rows?
3. **The training budget.** A surrogate trained on 222 usable rows against a paper
   that trained on thousands is not a reproduction of the method, it is a
   measurement of your sample size. Say what you trained on and how far under the
   source you are, and if the shortfall is affordable, fix it rather than
   reporting it.
4. **A schedule or hyperparameter you chose and they specified.** A learning-rate
   schedule that is silently wrong will burn a hundred training runs and will not
   announce itself. Check the ones you invented, first.
5. **A one-point sanity case.** Find something in the source with a closed-form or
   trivially checkable answer and reproduce that. If it fails, the gap is upstream
   of the science.

Do this **while the compute budget is still open**. A gap discovered at Stage 06
with nothing left to run is a gap you will describe rather than close; the time
to look is the hour after the first number lands, not the hour before writing.

## When it genuinely will not close

Then it becomes a finding, and it is owed the same rigour as any other:

- The published value, your value, and the ratio, in one sentence.
- What you ruled out, by name, with the check that ruled it out.
- The one remaining candidate, and what it would take to test it.

"Our number differs and we discuss possible reasons" is not that. A list of
plausible causes with no eliminations behind it reads as a run that did not look.

## The check before you leave the stage

For every quantity the source publishes and this task asks for, one of three is
true and written down: it agrees, it disagrees and you closed it, or it disagrees
and you eliminated the cheap causes and named the expensive one. Nothing in the
fourth state — noticed, described, unexamined.

See also `reproduce-then-extend` for how the comparison table is built and where
the published column comes from, and `run-the-requested-analysis` for what to do
when the gap turns out to be in the supplied inputs rather than in your code.
