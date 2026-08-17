---
name: physics-the-anomaly-behind-the-miss-is-a-result
description: Use at experimentation the moment you diagnose why a block of your reproduced values misses the published ones, and again at analysis and writing when that diagnosis is about to be filed as an error source, a limitation or a dispute with your own frozen scoring rule. Covers converting the mechanism into a statement about the system, where such extensions come from, and why one attached to the source's own result is worth more than a new question beside it.
applies_when: optimal size mismatch
stages: 05_experimentation, 06_analysis, 07_writing
---

# The mechanism behind the miss is a result about the system, in the right register

Somewhere in a reproduction a block of values will not come out. You chase it
properly and you find the cause: the relaxation leaves the basin you started it
in, a branch stops being a minimum below some value, a structure you built
relaxes onto a different one. You have the diagnosis, the diagnostic artifact and
the displacement jumps on disk.

Then it gets written down as the reason fifteen of your ninety-nine values miss,
as an inflated error in three rows, as a limitation, or - worst - as an argument
with your own preregistered scoring rule about whether those rows should have
counted. All of that is honest and all of it is a report about your pipeline.

The same computation says something about the system, and in that register it is
worth more than the agreement it spoiled:

> Below a mismatch of 0.125 on a 147-atom core the chiral shell is not a local
> minimum at all - it relaxes exactly onto the achiral one - and that threshold
> tracks the geometric anti-Mackay optimum to within 17 % across a tenfold range
> of core size.

Same relaxations. One version is an error budget; the other has a threshold, a
scaling, a figure and a prediction, and it turns a preference the source could
only assert in prose into a criterion. Choose the register deliberately, because
nothing else in the pipeline will.

## Where your best extension comes from

Keep a **repair log** from the first stage: every place you had to depart from
the source as printed to make its numbers come out. An equation re-derived
because the printed one returns the wrong sign. A formula that had to be
symmetrised because the elementary step takes one index past the other. A
normalisation the source never states. A constant you had to fetch elsewhere. A
branch that would not stay put. One line each, with the symptom that forced it.

That list is your extension candidates, and it is a better list than anything you
will invent, because every entry is already attached to a result the source
published. An extension drawn from it shares a figure, an axis and a number with
the reproduction, so a reader sees more evidence for the same result. An
extension that opens a question the source never asked stands *beside* the
reproduction: it takes its own panel, carries its own verdict, and if it comes
back negative - which a question chosen for being open often does - the report as
a whole reads as a study that failed, however much of the source it reproduced.

An independent check the source never ran belongs on the same list: verifying
your constructed shells against the order-60 icosahedral rotation group and a
mirror test is not housekeeping, it is a property of the object the source
asserted and did not demonstrate.

## What to do

For each entry in the repair log, ask the physical question rather than the
pipeline question. Not "why does my number miss theirs" but "what is the system
doing here, and at what value does it start doing it". If the answer has a
threshold, measure the threshold and its dependence on the one parameter you can
vary; a threshold with a scaling is a result, an error bar on a miss is not.

Give it observable axes and the source's vocabulary: the quantity against the
parameter with the threshold drawn and labelled, not absolute error against row
index. Give it a heading that names the phenomenon, not the hypothesis it broke.

Put it in the abstract, in the same paragraph as your agreement statistic. A
reproduction that only agrees can be read, at best, as the same as the paper. The
sentence that says you found something the paper does not contain, *on the
paper's own result*, is the one that moves that reading.

Where a frozen decision rule and the physics disagree, report both numbers - that
part is right - but do not let the adjudication of your own rule be the only
place the phenomenon appears. The scoring dispute belongs in one paragraph of the
discussion. The phenomenon belongs in the results, with its own number.

## Before you finish

Read every entry in the repair log against the report. Each should have a
sentence in the results, and that sentence should be a statement about the
system. If the only place a mechanism appears is in Limitations, in an error
attribution, or in a paragraph about whether your own rule should be amended,
the result has been written in the wrong register and no reader will convert it
back.

## Why this is here

Measured on Physics_000 of ResearchClawBench, one judge (gpt-5.1, three draws).
The AutoR run detected the chiral relaxation leaving its basin, named it, and
persisted `results/chiral_basin_escape.json` and `results/basin_diagnostic.json`.
Its report uses it three ways: as the cause of 11 of 13 misses in
"84 of 99 published optima reproduced", as inflating its own chiral error at
k = 5, 6, 7 to 0.431, 0.441 and 0.446 against published values of 0.018, 0.041
and 0.061, and as a paragraph declining to rescore against its own frozen rule.
It is never stated as a property of the system and no threshold for it is
reported. Bare Claude Code, on the same task, published the same physics as its
second headline finding with the threshold and the tenfold-range scaling quoted
above, and beat the AutoR run on the two criteria that turn on the mismatch
formula and the lattice construction, **49.67 to 37.0** at weight 0.4 and
**66.67 to 48.67** at weight 0.3. The judge's stated reading of the AutoR run on
the second of those was that it is "comparable to the paper but not demonstrably
superior" - which is the ceiling of a reproduction that only agrees. Part of that
second gap is judge variance rather than craft: the comparator's three draws on it
spread 55 to 80 where the AutoR run's sat at 50, 48, 48.
