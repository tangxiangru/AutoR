---
name: withdraw-the-clause-whose-precondition-failed
description: Use at hypothesis freeze to attach a validity precondition to every decision rule, and again at analysis when an arm has come back and one of those preconditions turns out not to hold - duplicated test rows, an offset the split handed one arm, a same-arm seed null wider than the cross-arm difference, an arm that never cleared its competence bar. Covers measuring the preconditions before the arm runs, withdrawing a clause instead of publishing it with caveats that void it, and the line between withdrawing and moving the goalposts.
applies_when: latent charges|Born effective charges
stages: 02_hypothesis_generation, 03_study_design, 06_analysis, 07_writing
---

# A frozen clause with a broken precondition is withdrawn, not caveated

Freezing a decision rule before the data arrives protects you from one specific thing:
choosing the threshold, the direction or the population after seeing the number. It
does not oblige you to publish a verdict read off an instrument you have since shown
does not work. Those are opposite failures, and a run that has internalised the first
one will walk into the second while congratulating itself.

So every frozen clause gets a second field at freeze time, beside its threshold: the
**validity precondition**, the property the data and the arms must have for the clause's
reading to mean anything. Write it in the same sentence as the rule, because it is part
of the rule.

## The preconditions worth writing, and when to measure them

Most of them are cheap, and nearly all of them can be measured *before* the arm runs.
That is where the money is: a precondition that fails before training is compute you
get to spend somewhere else.

Are the test rows disjoint from the training rows, and not near-duplicates of them?
Count exact and near-duplicate pairs across the split, not just identical keys. Do the
two arms differ only in the factor the clause names, or does the split also hand one of
them an offset, a class balance or a per-group constant the other cannot have? Is the
cross-arm difference larger than a *same-arm* null - the same arm re-run under a
different seed, split or initialisation? And, before any of that: what does an arm that
learned nothing score on this test? The constant predictor, the analytic
zero-interaction value, the per-species or per-class lookup, the memorisation residual
of a split with duplicates in it. Compute that floor first. If the gap between "the
source's claim is true" and the floor is smaller than your own seed spread, the arm
cannot separate them, and running it buys you a null you already had on paper.

## At adjudication, read the preconditions before the verdict

If one failed, the clause is withdrawn. What goes in the report where the verdict would
have gone is the precondition, its measured value, and one sentence saying what would
have to be true for the clause to be readable - "the thirty test frames each have their
twin in training, so any error on this file is a memorisation residual and no
comparison on it separates the arms". That sentence is a measurement and it is worth
more than the verdict was.

Do not publish the verdict with the defects underneath it. A verdict printed in a
heading, a table cell or an abstract, with three paragraphs below explaining that it
has no power, is read as the verdict. Readers take the cell. Worse, the caveats are an
argument against your own number, written by you, arriving after the number - which is
the one rhetorical position from which nobody is persuaded of anything.

## Withdrawing is not moving the goalposts, and you must say which you are doing

The distinction is the *evidence you used*, and it is auditable. A withdrawal is
justified by a property of the data or the split - something you could have measured
before the arm ran, and often did. Moving the goalposts is justified by the result:
changing a threshold, flipping a direction, re-scoping a population, or excluding the
rows that disagree. Record which one you are doing, name the property, and give the
number. A run that writes "withdrawn: the clause's disjoint-split precondition fails,
measured at N duplicate pairs of N total" has done something a reader can check. A run
that writes "we soften the verdict in light of the data" has not.

Two corollaries. A precondition failure discovered before the arm runs is not a
withdrawal at all - it is a redesign, and it is free. And a clause you withdraw does
not take the experiment with it: the task named the experiment, not your clause. Run it
on a population where the precondition holds, generate one if you have to, and report
the pair.

## Why this is here

Measured. A reproduction froze six hypotheses and reported every one of them as refuted
or inconclusive, leading its abstract with that count. Two of the refutations were read
off arms whose preconditions the run had itself disproved and printed in the same
section: all sixty frames of one supplied file occur in exact duplicate pairs with
every test frame's twin in training; the split hands one arm a 32.34 meV/atom
per-species offset before its first optimiser step, on a file whose true separation is
exactly zero; and a same-arm seed null spans 0.6964 relative difference against the
0.5805 cross-arm difference the clause reads. The report states in plain words that
"the clause has no power on that file" and publishes the refutation anyway, on the
ground that softening a frozen verdict after seeing it would be worse. In the other
experiment the run computed the analytic zero-interaction floor before any model
trained, then spent three seeds of two arms confirming that both sit on it. The two
criteria those sections answer scored 6.0 and 27.3, against 24.0 and 61.0 for a plain
agent.
