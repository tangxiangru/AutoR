---
name: a-detection-score-is-a-claim-about-its-population
description: Use at study design and at analysis whenever a detection or ranking score (area under a precision-recall or ROC curve, recall at a fixed precision) is about to be compared against another study's number, or when one arm detects items the other misses. Covers publishing the population beside the score, the prevalence ladder to run when the source never states its own, and the characterisation of the extra detections that needs no annotation.
stages: 03_study_design, 06_analysis
---

# A detection score is a claim about the population it was computed on

## What goes wrong

Two arms are scored on the same candidates, one is better, and the result ships as two
areas under two curves. Areas are the least transferable statistic available. The area
under a precision-recall curve moves with the positive rate; the area under an ROC curve
moves with the composition of the negatives. Your candidate set is almost never the set
another study scored on. So when your area and theirs disagree, neither you nor the reader
can tell whether you disagree about the method or about the denominator - and the run
writes the arithmetic up as a substantive contradiction of the source, which is a false
claim that also displaces the true one.

The second failure sits underneath it. "More sensitive" is a claim about a *set*: the items
one arm found and the other did not. Reported as two scalars, the set is never opened, so
nothing is ever said about what the extra detections are or whether they are real.

Curve craft, the operating-point sweep and the count-of-additional-true-positives headline
are `life-benchmark-against-the-incumbent`; the general population/split discriminator is
`close-the-gap-to-the-published-number`. This skill starts where both stop: what to do when
the source never states its own population, and what to publish about the extra detections
when the items carry no annotation you can join to.

## Publish the population with the number

Every detection score in the report, in the table and on the panel, carries: n candidates,
positive count, positive rate, and the rule by which candidates entered the set. Do the
same for the source's number wherever the source states it, on the same row. A
precision-recall statistic quoted without its positive rate is not a comparable number,
and the chance line on your curve is that rate - draw it and label it with the value.

## When the source does not state its population, walk a ladder

The source usually will not. "The source does not report its candidate-set composition" is
where most runs stop, and stopping there converts the largest number in the report into an
unresolved limitation. Do this instead:

1. Resample the majority class of your own evaluation set to a ladder of positive rates -
   a geometric sequence from your own rate down to the smallest rate the source's setting
   plausibly implies, several seeds per rung.
2. Recompute the metric for *both* arms at every rung. Report value and across-seed spread
   per rung, as a small table or a second panel with rate on the x-axis.
3. Read three things off it, in writing: the rung (if any) at which your value meets the
   source's; whether the ordering of the arms is stable across the ladder; whether the
   size of the between-arm gap is stable across the ladder.
4. State which of three holds - prevalence explains the whole difference from the source,
   part of it, or none of it - and give the residual after matching.

The between-arm difference is usually far more stable across the ladder than either
absolute value. That is the sentence worth writing, because it is the one that survives a
reader who holds a different anchor for what the source's number was.

## Open the set, and characterise it with what you have

Materialise the comparison as an artifact before you summarise it: one row per candidate,
with each arm's score, each arm's call at the operating point you report, the label if you
have one, and a membership column over {both, method-only, baseline-only, neither}. Report
all three counts, not one - an arm that finds extra items while losing items the other had
is a different result from one that loses none.

Then characterise the method-only set against the shared set. This part needs no
annotation and is therefore never blocked:

- **Label composition.** Of the method-only calls, how many are true positives; the same
  for the baseline-only calls. A pile of extra detections that are mostly correct and a
  pile that is mostly noise are opposite results and cost the same to compute.
- **Score placement.** Where the extra detections sit in each arm's score range, and how
  close the losing arm came on them - which distinguishes items the baseline ranked just
  below its threshold from items it did not see at all.
- **Any covariate the supplied tables already carry** - depth, coverage, length, category,
  batch - as a distribution for the method-only set beside the shared set.

These go in Results, next to the metric they explain, not in an appendix.

## The annotation route is optional, and its failure is reported, not assumed

If the items can be joined to named biological or physical units, do it: the extras'
distribution over those units, tested against the shared set as background, with counts.
Two routes exist before you conclude they cannot - the source's supplementary tables,
which is where its own item-level version of the claim usually lives, and the reference
annotation the task names, which maps coordinates or ids to units. Attempt both, name the
join key each needs, and record what was missing. "Not attempted, inputs missing" written
in a run that successfully parsed the source's supplement is not a finding, it is a stage
that did not look. And if both genuinely fail, say which units the source itself reports
its extras in, so the reader can see exactly what is absent.

## Checklist

- [ ] n, positive count, positive rate and inclusion rule printed beside every detection
      score, for every arm.
- [ ] Chance line drawn on the curve at the actual positive rate and labelled with it.
- [ ] Prevalence ladder computed for both arms with seed spread, whenever a score is
      compared against another study's.
- [ ] Written verdict: prevalence explains all / part / none of the difference, with the
      residual.
- [ ] Membership artifact on disk; all three set sizes reported.
- [ ] Label composition and score placement of the method-only set reported in Results.
- [ ] Annotation join attempted by both routes, or its impossibility stated with the
      missing key named.
