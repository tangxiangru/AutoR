---
name: physics-a-forced-outcome-is-still-a-published-result
description: Use at study design when you are deciding which of the source's documented cases a rule of yours will be scored on, again at analysis before any hit-count, rate or census is published, and again at writing when the case is being named. Covers the case whose outcome your own theory proves must happen, why dropping it inverts the rate you then publish, and why the run you already did for it can still fail to arrive.
applies_when: self-assembly in growth simulations
stages: 03_study_design, 05_experimentation, 06_analysis, 07_writing
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
it costs you twice: once in a number, and once in a name.

## A rate over the surviving cases is not the rate anyone quotes

Take the number first, because it is the one that reads as a contradiction of
the source. When you remove the forced cases you remove, by construction, every
case in which the conserving outcome occurs. Then you publish "the
class-conserving rule scored 0 of 11". That sentence is true of your filtered
set and it is the opposite of what the system does - a reader comparing you
against a source that reports the conserving step dominating sees a flat
contradiction, and the disagreement is entirely an artefact of your denominator.

You will very likely notice this and say so; a careful run does. Saying so does
not repair it. "The baseline scores zero by construction, because the scored set
is precisely the cases in which the class changes" is an honest gloss on a rate
that is still the only rate in the report, and a reader who wanted the rate over
everything the source documented still does not have one.

Any rate carries its population with it. If the population was chosen by an
argument about evidential weight, the rate is a statement about your rule and
not about the system, and it may not be the only rate you publish. How often
each outcome class occurs across everything documented is a property of the
system; no exclusion argument bears on it at all, because the exclusions were
about which cases *test a rule*, and a census tests nothing.

## The forced case survives as an experiment and dies as a label

The second cost is quieter. A paper opens its results with the outcome it can
show most cleanly, and the cleanest outcome is very often the one the theory
forces. Deposit atoms of the same species onto an achiral seed and a chiral
shell appears anyway - nothing is driving it but geometry, which is exactly why
the authors put it first and gave it a name.

You have often run that case anyway, because it is also the cheapest ensemble to
set up and it doubles as a control for something else. So the trajectories
exist, a figure exists, and a sentence in your results says the shell formed.
What does not exist is any thread from that sentence back to the source. The
figure is captioned with your own diagnostic axes. The subsection is named after
your hypothesis. The phenomenon is described in your own words rather than the
field's. The case identifier from your own enumeration never appears. And the
verdict attached to it answers a question you invented - a parity control, a
coverage interval, a preregistered band - rather than the question the source
asked.

A reader looking for your reproduction of that result searches for its name and
finds nothing. The experiment was done. It was not delivered, and the gap
between those two is a writing act, not a compute budget.

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

**Look for the forced case on disk before you plan one.** A theorem says which
structure *should* form; a simulation says which one *did*, at what step, from
which state, in what fraction of trajectories. Those are two different results
and the second is the one the source published. But check first whether you have
already produced it under another name - the control, the pilot, the ensemble
built to calibrate an interval. Usually you have, and then the work remaining is
not compute.

**Label it with the source's own name, in its own subsection.** The forced case
almost always has one: a figure number, a named system, a named phenomenon.
Write the heading with that name. State in one sentence that your theory
predicted the outcome and your run produced it, in what fraction of trajectories,
and use the field's established words for the phenomenon rather than your own
paraphrase. Cite the case's row in your enumeration so the two can be joined, and
give the existing figure a caption that says which published result it is. A
reader looking for your reproduction of a numbered figure searches for that
number.

**Answer the source's question before your own.** A forced case usually arrives
carrying an internal test as well - whether the two enantiomers come out
balanced, whether an interval covers a preregistered band. Those tests are often
underpowered, and saying so instead of banking the verdict they hand you is
right. But the verdict on your internal test is not the verdict on the source's
claim. If it is the only verdict in the subsection, the reproduction reads as
inconclusive when what you actually established is that the outcome occurred.
State the source's result first, with the fraction of runs it occurred in; state
the internal test second, with its own separate verdict.

**Keep the epistemics beside the case, not in place of it.** "This outcome is
entailed by the result above, so it confirms the rule rather than testing it" is
one sentence under the subsection. It is not a reason for the subsection to be
absent.

## Before you finish

Open `<process>_all_cases.csv` and go down it row by row. For each: does it
appear in the published census; was it run, or already run under another name;
and does the report carry both the source's own identifier for it and the field's
own word for what happened? Then grep the report for the identifier of every case
you excluded, and for the name of the phenomenon. Zero hits means the exclusion
did not downweight the case, it deleted it from the deliverable while leaving the
work on disk.

If you have no such file at this point, that is the finding: the population was
never written down as a population, only as the subset that survived a rule.

## Why this is here

Measured on Physics_000 of ResearchClawBench, one judge (gpt-5.1, three draws)
over both arms. The growth-experiment criterion, weight 0.3, scored **3.33** for
the AutoR run against **36.0** for bare Claude Code - **9.80** weighted, the
largest single component of that task's 20.27-point deficit.

The run's own `notes/growth_cases.json` enumerated all **22** documented growth
outcomes with the source figure each came from. Its scoring conventions then
excluded two as entailed by a theorem it had proved ("credit for these is credit
for a theorem"), marked five more degenerate, to be scored "only for whether an
ordered shell of the predicted occupancy and family forms", and split four
anti-Mackay-terminated ones off as a set of their own. **11** cases survive into
the rule's scored set, and that set is what the report published over: "the
class-conserving baseline R0 scores **0** of 11", with a separate "**0** of 4"
for the anti-Mackay split - and its Methods state the trap in their own words, that
R0 "scores 0 on this set by construction, because the scored set is precisely the
cases in which the class changes", and record declining an adversarial reviewer's
proposal to score over the full 22-case census instead. No rate with 22 in its
denominator appears anywhere in the report. All 22 do appear together once, in
the right-hand panel of a figure that colours each case by whether one of the
run's own rules got it right - the census drawn as a scorecard, which is the same
substitution one level up.

The naming half is the part that looks like it cannot have happened, and did.
Among the degenerate five was the source's own Figure 6a demonstration, Rb
deposited on a Na13@Rb32 seed. That case *was* simulated - `deposition_runs.json`
records **60** Langevin trajectories depositing 72 particles onto exactly that
relaxed Bergman seed, **28** of which closed an ordered shell - it *was* drawn,
as the report's Figure 7, and the report states "The chiral shell does form
spontaneously on an achiral seed". What is absent is every thread back to the
source. `Fig. 6a` and `Figure 6a` occur **0** times in the AutoR report and **5**
times in the comparator's - and the AutoR report is the longer of the two,
62.3 kB against 49.3 kB, so nothing was cut for space. `symmetry break` is **0**
against **2**. Of the 22 enumerated case identifiers the report names only two,
neither of them this one. The figure's three panels are the run's own diagnostics
- band occupancy, Clopper-Pearson intervals on its own frozen clauses, the margin
its enantiomer label is assigned on - and the passage closes on "the combined
verdict is inconclusive", which is a verdict on that parity control and not on
whether the shell formed. The judge's recorded reasoning for the AutoR arm names
three things the images do not show, and two of them are these: the
symmetry-breaking event on that seed, and conservative-step dominance in
homo-atomic deposition.
