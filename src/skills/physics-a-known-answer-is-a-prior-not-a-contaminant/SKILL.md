---
name: physics-a-known-answer-is-a-prior-not-a-contaminant
description: Use at literature survey and hypothesis freeze when you already know some of the answers - from a note left by a previous run, a review that quotes the number, a related paper, or your own reading - and you are recording that exposure so your predictions stay honest. Covers the three ways a contamination record silently deletes the results it was meant to flag, and what to produce for each pre-known quantity instead.
benchmarks: researchclawbench
applies_when: multi-shell icosahedral
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design
---

# Prior knowledge downgrades a result's evidential weight, not its existence

You begin a reproduction already knowing some of what you will find. A note from
a previous run names the threshold. A review quotes the constant. The
supplementary material's printed equation is known to be wrong and you know the
correction. Blind prediction is worth protecting, so you write the exposure down
and mark those quantities pre-known.

That ledger is right and you should keep it. What goes wrong is the step after
it, where a flag on a quantity turns into the quantity's absence from the
report - and every form that takes feels like rigour while you are doing it.

## The three deletions

**By hypothesis.** A pre-known quantity cannot be a discovery, so no hypothesis
is written about it. The figure plan is filled from the hypotheses. The results
sections follow the figures. Nothing downstream ever reaches the quantity.

**By route.** You know what the printed equation returns, so you reach the same
answer another way - through the Methods' derivation rather than through the
equation itself. Now the equation is never evaluated, the erratum is never
confirmed first-hand, and the strongest thing you could have said about the
source's supplementary material is a thing you deliberately did not look at.

**By demotion.** The pre-known item is graded a "secondary observable", or
"flagged", or "carried with predictive weight withheld". Those phrases have no
downstream implementation. In practice they mean no compute, no figure slot and
no sentence.

The result is a run whose disclosure file is more informative than its report:
it names, in a machine-readable list, exactly the findings the run declined to
produce.

## What to do

**Every pre-known item is a row in a Results table, not only in a ledger.**
Columns: the quantity, the pre-known value with where you knew it from, your own
in-run value, and `blind: no`. The flag costs a word. The missing row costs the
result. The one thing you may never do is quote the pre-known number as your own
measurement - which is what the ledger is actually there to prevent, and it
prevents it perfectly well while the row is present.

**Never let exposure choose the method.** If the question is what the printed
equation gives, evaluate the printed equation, even though you know. Choosing
the other derivation to preserve blindness sacrifices a result to protect a
statistic nobody scores.

**Spend budget on pre-known items preferentially, not last.** Someone has
already established that the quantity is real and interesting; that is a
selection signal about what is worth measuring, and it is the cheapest one you
will get. A pre-known finding you reproduce first-hand is a confirmed finding
with a provenance you can defend. A blind result on a question nobody cares
about is blind and worthless.

**Recover the blindness cheaply where it matters.** Before you compute, write
down which side of your threshold the pre-known value falls on, and what you
would conclude either way. That is a pre-registration of the replication, it
takes one sentence, and it buys back most of what exposure cost. Then run it.

**Publish the exposure ledger as an appendix table.** Disclosure is what protects
the run from the charge of having known the answer. Silence is not disclosure,
and an absent result is not caution.

## Before you finish

Read the exposure list top to bottom. For each item, name the section of the
report where your own value for it appears. A status of "not measured here" or
"not tested here" is a record of exposure; it is not an outcome, and if it is
still the status at writing time the ledger has eaten a deliverable.

## Why this is here

Measured on Physics_000 of ResearchClawBench, one judge (gpt-5.1, three draws).
The AutoR run's `workspace/literature/prior_exposure_disclosure.json` lists
**13** pre-known quantities, carried in from memory notes left by earlier runs of
this same task and read in the first minute of the run. Four are marked
"NOT MEASURED HERE" or "NOT TESTED HERE": the threshold form of the growth rule
(PK08, known to score 12 of 12 against 9 of 12 for the alternative reading); the
mismatch below which the chiral shell stops being a local minimum and relaxes
onto the achiral one (PK09, annotated "the single most contaminating item in the
notes"); the alkali lattice constants (PK10); and the erratum in the source's
supplementary Eq. (86) (PK12, whose note reads "This run reached the AM optimal
mismatches through the Methods' edge-length route, never through Eq. (86)").
Stage 02 then disposed of PK09 in one clause — "branch existence is reported as a
secondary observable with the exposure flagged" — and what that clause bought
downstream was a single sentence at the tail of a results subsection, under no
heading of its own, with no figure whose subject it is and no line in the
abstract. PK12 bought nothing at all. Bare Claude Code, on the
same task, read one of the very same memory notes — its transcript shows the
`Read` — and kept no ledger at all: no such file in its workspace, no mention of
prior exposure anywhere in its report. It opened with three of those four items
as **findings 1, 2 and 3** of four, and beat the AutoR run **50.7 to 30.4**. That
is not an argument for keeping no ledger. It is the measurement that separates
the ledger's two effects: the disclosure was free and the withholding was not. The
strings `erratum`, `errata` and `Eq. (86)` appear on **0** lines of the AutoR
report and **3** of the comparator's, one of them in that opening block.

Worth knowing before you trust a note-to-self here: this ledger *already* carried
the right instruction. Its own `consequences_for_later_stages` says to register
each contaminated item "as a pre-registered replication test and say which side
of its threshold the pre-known value falls on BEFORE writing the rule" — close to
what this skill asks for — and no such registration reached the report. None of
the 13 identifiers appears in it, the string `pre-known` appears **0** times, and
the ledger's vocabulary survives in exactly one clause: the "exposure flag" that
demotes PK09 to a secondary observable. An instruction about how to think does
not survive six stages. An instruction that names a row in a table does.
