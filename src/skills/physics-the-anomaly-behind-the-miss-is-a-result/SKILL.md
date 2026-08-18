---
name: physics-the-anomaly-behind-the-miss-is-a-result
description: Use at experimentation the moment you diagnose why a block of your reproduced values misses the published ones, and again at analysis and writing when that diagnosis is about to be filed as an error source, a limitation, a flagged secondary observable, or a dispute with your own frozen scoring rule. Covers converting the mechanism into a statement about the system, giving it the rank a result gets rather than the rank a caveat gets, and where the extension worth most to a reproduction comes from.
applies_when: optimal size mismatch
stages: 05_experimentation, 06_analysis, 07_writing
---

# The mechanism behind the miss is a result about the system, in the right register

Somewhere in a reproduction a block of values will not come out. You chase it
properly and you find the cause: the relaxation leaves the basin you started it
in, a branch stops being a minimum below some value, a structure you built
relaxes onto a different one. You have the diagnosis, the diagnostic artifact and
the displacement jumps on disk.

Then it gets written down as an error-budget line against your reproduction
rate, as an inflated residual in a handful of rows, as a limitation, or - worst
- as an argument with your own preregistered scoring rule about whether those
rows should have counted. All of that is honest and all of it is a report about
your pipeline.

The same computation says something about the system, and in that register it is
worth more than the agreement it spoiled:

> Below a critical mismatch the chiral shell is not a local minimum at all - it
> relaxes exactly onto the achiral one - and that critical value falls
> monotonically as the core grows.

Same relaxations. One version is an error budget; the other has a threshold, a
scaling, a figure and a prediction, and it turns a preference the source could
only assert in prose into a criterion someone else can apply. Choose the register
deliberately, because nothing else in the pipeline will.

Write your own version of that sentence from your own numbers. If you find
yourself able to state the threshold before you have measured it, you are
remembering it rather than finding it, and it belongs in an exposure record
before it belongs in a result.

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
parameter, with the threshold drawn and labelled. Not a panel of residual
magnitudes - that is your agreement statistic wearing the phenomenon's clothes.
Give it a heading that names the phenomenon, not the hypothesis it broke.

**Beware the qualifier that reads as rigour and lands as a demotion.**
"A secondary observable." "Reported with the flag it carries." "Carried with
predictive weight withheld." Each is a true and creditable thing to say, and each
has the same effect on the artifact: the sentence stays and the deliverable
leaves, because a phrase like that is understood downstream as permission not to
give the thing a heading, a figure or an abstract line. Withhold the *evidential
weight* explicitly and give the *result* its full apparatus anyway. Those are
different dials and the qualifier only justifies turning one of them down.

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
system. If *every* place a mechanism appears is in Limitations, in an error
attribution, or in a paragraph about whether your own rule should be amended,
the result has been written in the wrong register and no reader will convert it
back. Appearing often is not the same as appearing once as a result.

A present sentence is not enough, so check the rank as well. For each mechanism,
four questions, and answer them about the sentence that carries the *number*,
not about the mechanism in general:

- Is the phenomenon **named** there? You may well have coined a good name for it
  elsewhere while using it to excuse a miss. A name that appears only in the
  error attribution does not make the result searchable.
- Does it have a **heading**, or is it the last sentence of a section about
  something else?
- Does a figure have it as its **subject** - the threshold against the parameter
  it depends on - or does it appear only as an annotation on the figure of the
  result it spoiled?
- Is it in the **abstract**?

Four noes means it is in the report and out of the deliverable. That is the
harder failure to see, because searching your own draft for the mechanism
succeeds: the words are all there, distributed across the places where it was an
excuse.

## Why this is here

Measured on Physics_000 of ResearchClawBench, one judge (gpt-5.1, three draws).
The AutoR run detected the chiral relaxation leaving its basin, named it, and
persisted `results/chiral_basin_escape.json` and `results/basin_diagnostic.json`.
Its report puts it to work as the cause of 11 of 13 misses in "84 of 99 published
optima reproduced", as what inflates its own chiral error at k = 5, 6, 7 to 0.431,
0.441 and 0.446 against published values of 0.018, 0.041 and 0.061, and as a
paragraph declining to rescore against its own frozen rule.

The failure is not that the physics went unreported - it is what rank it was
reported at, and the run is a demonstration that a mechanism can be everywhere in
a report and still not be delivered.

It *was* stated as a property of the system, with thresholds: six values, one per
core size, on **one** line of a 751-line report. That line is the last content of
its subsection - a subsection titled for a phase diagram, whose bolded claim is
that the run's third hypothesis is refuted - and it is introduced as "a secondary
observable, reported with the exposure flag it carries". No scaling is fitted to
the six values. No figure caption carries them. The abstract does not mention the
effect at all.

The rest of the report is not silent about it, which is the part worth studying.
The run had coined a good name for the mechanism, and that name occurs on **4**
lines - none of them the line carrying the thresholds. Every one of the four is
an explanation of a miss: the cause of three inflated error rows, an annotation
on the caption of the figure showing the reproduction it spoiled, an accepted
diagnosis inside the paragraph declining to rescore, and a note under an appendix
table. A fifth appearance, a Limitations bullet, concedes the branch was never
characterised. All statements about the pipeline. The one statement about the
system got a clause, and used none of the vocabulary that would have let a reader
searching the other five arrive at it.

Bare Claude Code, on the same task, published the same physics as **finding 2 of
four** in an opening block headed "Four findings that go beyond the source", with
its own figure, the threshold's dependence on core size, and a closing sentence
claiming it converts a kinetic explanation the source only offered in prose into
a quantitative, predictive criterion. It beat the AutoR run on the two criteria
that turn on the mismatch formula and the lattice construction, **49.67 to 37.0**
at weight 0.4 and **66.67 to 48.67** at weight 0.3. The judge's recorded reading
of the AutoR run on the second of those was that it is "comparable to the paper
but not demonstrably superior" - the ceiling of a reproduction that only agrees.
Part of that second gap is judge variance rather than craft: the comparator's
three draws on it spread 55 to 80 where the AutoR run's sat at 50, 48, 48.

The threshold's numeric value is deliberately not repeated anywhere in this file.
On this task it was also a pre-known quantity carried in from a previous run's
notes, and a skill that hands over the number invites the agent to publish it
without measuring it.
