---
name: physics-a-forced-outcome-is-still-a-published-result
description: Use at study design when you are deciding which of the source's documented cases a rule of yours will be scored on, and again at analysis before any hit-count, rate or census is published. Covers the case whose outcome your own theory proves must happen, why dropping it inverts the rate you then publish, and where the forced case has to appear anyway.
applies_when: self-assembly in growth simulations
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Being forced is a reason to predict it, not a reason to drop it

Part way through a reproduction you prove a small theorem. The class-conserving
step always carries the smaller optimal mismatch, so at zero mismatch the
conserving step is forced; the two candidate shells on a diagonal seed are
enantiomers, so no size-based rule can tell them apart. Cases like these now
look worthless as evidence: a rule that predicts them gets credit for
arithmetic. So they come out of the scored set, with a defensible sentence in
the scoring conventions saying why.

The reasoning is right about *inference* and wrong about *the deliverable*, and
the two failures it causes are separate.

## The source's demonstration is usually the forced case

A paper opens its results with the outcome it can show most cleanly, and the
cleanest outcome is very often the one the theory forces. Deposit atoms of the
same species onto an achiral seed and a chiral shell appears anyway - nothing is
driving it but geometry, which is exactly why the authors put it first and gave
it a name. That is the case your exclusion rule deletes.

Once it is out of the scored set nothing else in the pipeline picks it up. It is
not simulated, because the experiment grid was filled from the scored set. It is
not drawn, because figures are drawn from experiments. It is not named, because
prose follows figures. The reproduction ends up with no account of the source's
first result, while the notes file that enumerates it sits on disk, complete and
correct.

## A rate over the surviving cases is not the rate anyone quotes

The second failure is quieter and worse. When you remove the forced cases you
remove, by construction, every case where the conserving outcome occurs. Then
you publish "the class-conserving rule scored 0 of 11". That sentence is true of
your filtered set and it is the opposite of what the system does - a reader
comparing you against a source that reports conserving steps dominating sees a
flat contradiction, and the disagreement is entirely an artefact of your
denominator.

Any rate you publish carries its population with it. If the population was
chosen by an argument about evidential weight, the rate is a statement about
your rule and not about the system, and it may not be the only rate in the
report.

## What to do

**Two populations, two files, in this order.** `results/<process>_all_cases.csv`
holds every documented case, no exclusions, with columns for the outcome and its
class, and it is the source of the census: count and fraction of each outcome
class, over everything, with N. `results/<process>_scored.csv` is the subset your
rule is tested on, identical rows plus an `excluded_because` column. Publish the
census first and the rule's score second, and say in one clause how the second
population was cut from the first.

**An exclusion is a column, never a deleted row.** `forced`, `entailed`,
`degenerate`, `tautological`, `carries no confirmatory weight` are attributes of
a case. A case with one of them is still run, still counted, still plotted, still
named. The attribute changes what you may conclude from it, and nothing else.

**Simulate the forced case rather than asserting it.** A theorem says which
structure *should* form. A deposition run says which one *did*, at what step,
from which state, in what fraction of trajectories. Those are two different
results and the second is the one the source published; a proof of the first is
not a substitute for it, and the run is cheap because you have already built the
machinery for the harder cases.

**Give it the source's name and its own subsection.** The forced case almost
always has one - a figure number, a named system, a named phenomenon. Write the
heading with that name, state in one sentence that your theory predicted it and
your simulation produced it, and put the phenomenon's own words in that sentence.
A reader looking for your reproduction of Figure 6a searches for "Fig. 6a".

**Keep the epistemics beside the case, not in place of it.** "This outcome is
entailed by the result above, so it confirms the rule rather than testing it" is
one sentence under the subsection. It is not a reason for the subsection to be
absent.

## Before you finish

Take the enumeration of documented cases you built at literature stage. For each
row: does it appear in the whole-population census, did it get run, and does the
report contain the source's own identifier for it? Grep the report for the
identifier of every case you excluded. Zero hits means the exclusion did not
downweight the case, it deleted it.

## Why this is here

Measured on Physics_000 of ResearchClawBench, one judge (gpt-5.1, three draws)
over both arms. The growth-experiment criterion, weight 0.3, scored **3.33** for
the AutoR run against **36.0** for bare Claude Code - 9.8 of that task's
20.3-point deficit, its largest single component. The run's own
`notes/growth_cases.json` had already enumerated all **22** documented growth
outcomes with the source figure each came from; its scoring conventions excluded
two as "entailed by T1" and marked five more "degenerate", to be scored "only for
whether an ordered shell of the predicted occupancy and family forms", leaving an
11-case set, and the report published "the class-conserving baseline R0 scores 0
of 11" over it. Among the excluded was the source's Figure 6a demonstration,
Na13@Rb32 with Rb deposited on it. The strings `Fig. 6a` and `symmetry break`
occur **0** times in that 62-thousand-character report; the comparator names
Fig. 6a **5** times, calls it symmetry breaking **twice**, and won the criterion.
The judge's stated reason was that the figures do not show the symmetry-breaking
event on that seed.
