---
name: chemistry-accuracy-and-cost-for-every-module-you-swap-in
description: Use at study design, through experimentation and again at analysis when the method under test is a drop-in replacement for a standard layer — a different basis, kernel, activation family or transform — and the source claims the replacement is both more accurate and cheaper. Covers giving every alternative module a cell in the accuracy column and in the cost column, fixing one matching convention across both, and dividing the runtime by the invariant already sitting in your own results file before you publish a contradiction of the source's ratio.
applies_when: Fourier-based Kolmogorov|replacing conventional MLP-based transformations
stages: 03_study_design, 05_experimentation, 06_analysis
---

# A module you only timed is half an arm

When a study's contribution is a module swapped into an existing architecture, its
claim is almost always joint: the replacement is *more expressive* and it is
*cheaper*. That is one claim with two columns, and it is answered by one table in
which every module the source compares — the proposed one, each alternative it is
compared against, and the conventional layer being replaced — carries a value in
both. An arm that appears only in the timing table cannot answer the accuracy
half. It is also the cheapest number in the whole study: the arm is already
implemented, the graphs are already featurised, and it is one training run from a
score. Build it once, then run it through the same loop, the same split and the
same estimator as the proposed module, and give it its row.

`rebuild-the-sources-headline-table-row-for-row` owns which columns have to
exist at all. This is about what has to be inside each of them once they do.

## One matching convention, stated, across both columns

Equal width and equal parameter count are different experiments. A basis that
holds 2K coefficients where a linear layer holds one is, at equal width, a bigger
model; at equal parameters it is a narrower one. Decide which match the comparison
is made at, write it in the caption, and use the same match on both sides of the
joint claim. A run that compares accuracy at matched parameters and cost at
matched width has measured two different comparisons and answered neither, and you
will notice this only as a paragraph in the discussion explaining why its own two
halves disagree.

Better, when the budget allows: two rows per module, one at each match. The pair
is what localises the effect on the size axis. A module ahead at equal width and
level at equal parameters is buying its lead with capacity, and that sentence is
worth more than either row alone.

## Divide before you contradict

A wall-clock ratio is a ratio of seconds, on your machine, at your parameter
count, batch size and thread count. Before it goes in the report, put the
invariant next to it — parameter count, multiply-accumulates per forward pass,
basis evaluations per message, and the ratio *per parameter* or per FLOP. The
denominator is normally already in your own results file, because you printed the
parameter counts when you built the arms.

Do this especially, and before you write the sentence, when your ratio disagrees
with one the source published or deposited. The invariant usually reconciles them,
and what looked like a contradiction of the source turns out to be your two arms
sitting at different capacities. A contradiction published in the results and then
explained away in a subordinate clause reads as a measurement that was not
finished. If the disagreement survives the division, you now have a real finding
and the eliminations to go with it — `close-the-gap-to-the-published-number`
governs how that is written, and `time-the-operation-not-the-invocation` covers
the harness-level confounds (clock, threads, startup cost) that the invariant does
not remove.

Check the alternative's own size knob while you are there. Timing a basis at one
harmonic against a competitor at five and calling the ratio a comparison of bases
is a comparison of knobs.

## The family claim is about a family

"This basis is stronger than those bases" is a statement about a set, so sweep the
module's own hyper-parameter — harmonic count, spline order, polynomial degree,
rank, number of experts — at least coarsely, on one dataset, and report the metric
against the knob with cost on the same axis. One setting of one basis is one point
in a space the claim quantifies over.

## Then say why the winner wins

Finish with the mechanism, in one or two sentences that a number in your own
results supports. Three shapes it takes: a *range* argument — one family stays
bounded on inputs spanning orders of magnitude where another does not; a *domain*
argument — a basis stops being faithful once its input leaves the interval it was
fitted over; a *conditioning* argument — one family trains stably under the
optimiser you used where another stalls. Which of those is true here is a
measurement rather than a pick from a list, so print the quantity the argument is
about — the pre-activation range, the gradient norms, the loss curves — and let it
decide, including when it decides against the module the source is selling. A table
of ratios with no sentence about the mechanism leaves an expressivity criterion half
answered, because that criterion is about *why* the substitution helps and the
numbers alone do not say; an unmeasured mechanism sentence is worse than none,
because it reads as an explanation and is a guess.

## Why this is here

Measured on Chemistry_000 of ResearchClawBench, scored with gpt-5.1 over three
draws. The criterion covering the basis comparison (weight 0.35) scored 48.3 for
the run under study against 58.7 for bare Claude Code on the identical brief.

Reading that run's artifacts: of the eleven files in `outputs/results/`,
`runtime_by_basis.json` is the only one the B-spline arm appears in at all — it was
timed and never scored, so the alternative basis has no accuracy cell anywhere in
the run, and it was timed at K=5 against the proposed basis at K=1. The third basis
the source compares is named twice in the run's own note scripts, once in a comment
and once inside a string, and zero times in the report.

That same JSON reports Fourier/MLP seconds ratios of 2.1168, 3.7198 and 3.8333
beside the authors' own deposited 1.0094, 1.0086 and 1.0615 — high by 110, 269 and
261 per cent. The report prints both, concludes that the source's caption is
contradicted by the source's own deposited data, and disposes of its own factor of
two-to-four in one clause about parameter counts. Those parameter counts were in
the same file: 43489/21889, 53793/13569 and 70370/17762. Dividing the seconds ratio
by the parameter ratio gives 1.0654, 0.9383 and 0.9676 — within nine per cent of
the deposited values rather than two to four times them. The clause was a division
the run was one line from publishing. The B-spline leg survives that division
(0.286, 0.281, 0.279 against a deposited 0.417-0.467), which is what a division
does: it relocates the finding rather than deleting it.
