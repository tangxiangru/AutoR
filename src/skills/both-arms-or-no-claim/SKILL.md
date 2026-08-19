---
name: both-arms-or-no-claim
description: Use at study design and again at implementation whenever the question is a contrast and one of the things being contrasted turns out to be unavailable. Covers substituting so the axis survives, what a one-armed experiment can and cannot conclude, and why silently dropping the missing arm is the failure that never surfaces.
stages: 03_study_design, 04_implementation, 06_analysis
applies_when: compare|comparison|contrast|versus| vs |between|across models|larger|smaller|stronger|weaker|scal(e|ing)|ablat
---

# A contrast with one side missing does not become a smaller contrast. It becomes a different question.

Most empirical questions are comparative: weak against strong, short against long,
one format against another, with a feature against without. The named thing on one
side is often unavailable — a model the deployment does not serve, a dataset behind
a login, an API that has been retired.

There are three responses and only two of them are honest.

## The failure this prevents

The tempting response is the third one: run the arm that works, report what it
shows, and let the comparison quietly become a description. It leaves no trace. The
write-up says something true about the arm that ran, the missing arm is simply not
mentioned, and no reader can tell that the question asked for two.

Measured on a deployment where **none** of the models a task named was served:
every run had to substitute, and the runs that did not say so produced conclusions
about "models" from a single model.

The same shape appears without any missing resource, from a budget: an arm is
planned, the clock runs down, and the conclusion is written from the arms that
finished. The plan named four conditions; the finding rests on two.

## The test

Before writing any conclusion that contains a comparative word — *more*, *less*,
*degrades*, *improves*, *unlike*, *whereas* — check:

1. **Did every side of that comparison actually run?** Name the arms and point each
   at the file that holds its measurements.
2. **If a side was substituted, does the substitution preserve the axis?** A weak
   model replaced by another weak model keeps a capability contrast. A weak model
   replaced by a frontier one destroys it — and reverses conclusions about scaling.
3. **If a side is missing, is the sentence still about it?** If yes, the sentence is
   not supported.

## What to do

**Substitute along the axis.** Ask what property the question is contrasting, and
pick the replacement that preserves *that* property, not the one that is nearest by
name. For a capability contrast, span the capability range the deployment has. For
a length contrast, span lengths. Record the substitution beside the result.

**Say it in the conclusion only where it changes what can be claimed.** A
substitution that preserves the axis needs no caveat in a short conclusion; one that
narrows the range does — "within the range tested" is a real qualifier, not a hedge.

**If no substitution preserves the axis, report the arm you have as a
description, not as a comparison.** "Model X shows the effect" is defensible. "The
effect is stronger in weaker models" is not, on one model, and the second sentence
is the one that gets written by default.
