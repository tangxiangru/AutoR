---
name: the-expected-negatives-are-the-discrimination
description: Use at study design when a per-unit metric's population is being chosen, and again at analysis and writing. Extends the per-unit publication clause of neuroscience-comparator-ladder-and-per-unit-predictions with the arm it omits: the units your sources expect to be null, the worst-positive-versus-best-negative separation number, and the rule that a shipped eligibility attribute is a reporting label and never a computation filter.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# Score the units your sources expect to be null

This is the missing third arm of the per-unit publication clause in
`neuroscience-comparator-ladder-and-per-unit-predictions`. That skill splits a
per-unit result two ways -- units an independent measurement validates, reported
as agreement k of n, and units where the model issues a novel prediction. The
split has a third population and a statistic, and without them the two-way
version can be executed in full and still leave the analysis unreadable.

## The third population

Every per-unit metric has three kinds of unit:

- **known positive** -- an independent measurement says the effect is there;
- **known negative** -- an independent measurement says it is *not*, and this is
  the arm that usually goes missing;
- **unknown** -- nobody has measured it, and this is where your predictions are.

The negatives are the discrimination. A metric evaluated only where the effect
is expected cannot fail: a model that finds the effect in every right unit and
also in fifteen wrong ones scores identically to one that got it right. Run the
negatives and you can write the threshold-free claim that actually settles it --
*the worst known positive scores above the best known negative* -- which is a
number, needs no imported cutoff, and survives a reader who disagrees with your
index definition. Miss them and the best you can say is a count at a threshold.

The negatives are also the cheapest rows you will ever compute. Where the metric
is a reduction over an array the simulation already produced, they cost one
more pass over memory you have already paid for.

## The trap: a shipped boolean looks like a roster

Supplied data arrives with an entity list and, alongside it, attribute columns:
an eligibility flag, a structural property, a curation status, a "characterised"
boolean. A subset selected by one of those columns looks like the roster. It is
in the data, someone curated it, and it comes with a one-sentence justification
that is defensible on the day you write it -- *only units with this property can
show the effect*.

It is not the roster. The roster is every row of the entity list. A subset
selected by a shipped attribute is a *hypothesis* about which units matter, and
testing that hypothesis requires the units it excludes. When you write the
filter, write it as a label on the output, never as a predicate that decides
what gets computed.

## Filter for reporting, never for computation

The filter rarely bites where it is written. It bites two stages later, at the
figure and the published table:

- the figure plots the eligible subset, so the population a reader sees is the
  one your mechanism argument already believed in;
- the published table carries an `eligible = no` column and a **blank** value
  cell for every excluded unit -- while the value sits computed on disk.

A blank cell reads as *not measured*. Never publish one for a quantity you
computed. Publish the value, and put the eligibility flag in its own column so a
reader can re-filter and you can be argued with.

Every entity your sources name individually gets a row, including the ones that
come back null. A confirmed null on a named entity is a result; an absent row is
read as the analysis not having been done, however careful the rows around it.

## What to produce

At **analysis**, one figure, one axis, one scale, three colours: known positive,
known negative, unknown-and-ranked. Not three panels -- the comparison is the
point.

In its caption, as numbers:

- worst known positive against best known negative, and how many pairs invert;
- how many unknowns score above the worst known positive, each named;
- for each named prediction, the fraction of replicates, seeds or ensemble
  members that agree with it, so a reader can tell a prediction from a coin flip.

## The sentence that turns a ranking into a hypothesis

A ranked list is not yet a claim, and a name that appears only inside a
threshold sentence has not been claimed. Say in the prose, as a sentence about
the units and not about your cutoff, which unknowns the model asserts the effect
for. Then say what they have in common in the *supplied structure* -- what they
connect to, what they are made of, where they sit relative to the known
positives -- and check that reading against the supplied structure data rather
than asserting it. That account is what an experimentalist acts on, and it is
the difference between a table and a result.

## Checklist

- [ ] Expected label -- positive, negative, unknown -- and its source recorded for every row of the supplied entity list.
- [ ] No shipped attribute or plausibility predicate decides what gets computed; filters are output labels only.
- [ ] Metric computed for every row, including expected negatives and unnamed units.
- [ ] One panel, one axis, three colours; no blank value cell anywhere a value exists on disk.
- [ ] Worst-positive versus best-negative stated as a number in the caption.
- [ ] Every entity the sources name individually has a row, nulls included.
- [ ] Predicted units named in prose with per-replicate agreement, not only plotted.
- [ ] A structural account of the predicted units, checked against the supplied structure data.
