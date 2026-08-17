---
name: hand-the-model-the-quantity-it-is-supposed-to-infer
description: Use at study design and again the first time a trained arm lands short of a published number, when the pipeline infers an intermediate quantity - a per-atom charge, a latent field, an assignment, an alignment - and then feeds it to whatever gets scored. Covers the arm that supplies that quantity's true value instead of estimating it, the scale sweep through it that turns the arm into a panel, and why this is the one diagnostic that still works on hardware that cannot converge the real arm.
applies_when: latent charges?|latent Ewald
stages: 03_study_design, 04_implementation, 05_experimentation, 06_analysis
---

# Hand the model the quantity it is supposed to infer, and re-measure

Your pipeline estimates something in the middle and then uses it to produce the number
that gets scored. The report can say "we got X, the paper got Y". It usually cannot say
*which part of the pipeline the difference is in*, and without that the shortfall is
not a finding, it is a complaint.

The cheapest experiment in the whole study answers it. Replace the inferred quantity
with its true value and re-measure everything downstream, unchanged. The truth comes
from wherever it comes from: shipped in the data as a field nobody trained on, exact by
construction for a system you or the source built, computable analytically, or read out
of the accepted reference program. Train the rest of the model exactly as before. The
only difference is that one channel no longer has to be estimated.

## What the arm buys, and each of these is a result

**A decomposition instead of a lament.** Your gap to the published number splits in two:
the part that survives being handed the answer - the representation, the objective, the
downstream sum, your implementation of all three - and the part that vanishes, which is
your estimate of that one channel. Report both halves. "Handing the model the exact
values is worth a factor of twenty in the scored error, so essentially all of our
remaining gap is the estimate of this channel and not the descriptor or the summation"
is a stronger sentence than any accuracy number you were going to print, and it is the
sentence the source's own discussion cannot make.

**A test of the objective rather than the optimiser.** If supplying the true value makes
the loss *worse*, then the true value is not the optimum of the objective you wrote, no
amount of training will find it, and you have a specification bug worth more than the
whole accuracy table. If it makes the loss better, the specification is right and every
remaining question is about estimation. Nothing else in a study separates those two,
and runs routinely spend their entire budget on the assumption that it is the second
one.

**A panel.** Scale the supplied value by a factor and sweep it - zero, so the channel is
switched off, through one, and past one - and plot the scored metric against the
factor. A minimum sitting at one is a picture of "the objective is minimised at the
true value", the depth of the well is the channel's worth in the units the task cares
about, and the zero end is the honest floor for the entire study: what a model that
never uses the channel achieves. Three numbers, one curve, one figure slot.

## When to run it

At pilot scale, before the main arms, on the smallest training set that trains at all.
It needs no head to converge and no seed repeats, so it is affordable exactly when
nothing else is - which is the case where it matters most. On a machine that cannot
converge the real arm, the supplied-value arm still tells you where the gap is, and
"our channel is fourteen per cent off and that costs a factor of five downstream" is a
finding, where "we ran at one per cent of the published schedule" is not.

Run it again at the end, on the arm you actually report, so the decomposition is
measured on the numbers in the table rather than on a pilot.

## What it is not

It is not an input ablation. Deleting a channel and retraining measures what
*information* is present in the input; supplying the truth measures what your
*estimator* costs you. A study with three input-ablation arms and no supplied-value arm
can tell you that the information is there and still cannot tell you why its own number
is wrong. It is not a null either. Run all three if you can; they answer three
different questions, and only this one localises a gap.

Give it its own row in the comparison table, between your arm and the published one:
channel off, channel learned, channel supplied, published. Four rows, and a reader
locates your gap without being told.

## Why this is here

Measured. Two runs reproduced a potential that infers an unsupervised per-atom quantity
from energies and forces alone; both landed short of the published error. The run that
also trained an arm with the true values imposed, sweeping their scale from zero through
one to one and a quarter, could report that the exact values are the optimum of its own
objective to the resolution of the scan, that supplying them was worth a factor of 20 in
force error and 37 in energy error, and therefore that its whole remaining gap sat in
the estimate of that one channel rather than in the descriptor or the Ewald sum. It
scored 52.7 on the criterion covering that experiment. The run that instead spent its
budget on input ablations - the same data with one channel deleted, three arms, three
seeds each - could only report that everything it trained sat far from the published
number at a fraction of the published schedule, and scored 28.3.
