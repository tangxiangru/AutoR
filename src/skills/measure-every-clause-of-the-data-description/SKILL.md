---
name: measure-every-clause-of-the-data-description
description: Use at study design when the task ships datasets with prose descriptions, and at analysis and writing before the data section is fixed. Covers turning every asserted clause into a measurement — including the qualitative ones about variety, structure and how the data was generated — and why a verdict on the data's fitness is weak until the characterisation under it exists.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# The data description is a list of claims, and each one is a measurement

A supplied dataset arrives with prose that asserts what it is: how large it is, what fraction of
it carries the label, how varied its contents are, how it was produced, and what all of that is
supposed to make possible. Those clauses are the specification the data section is read against.
A reader arrives at that section asking one question — is this data what it says it is? — and
expects a number under every clause.

What runs actually do is measure the two clauses that are already numbers, find one of them is
slightly off, and spend the section on that. The clauses that require *describing* rather than
*checking* — how varied the contents are, what structure the items have, whether the generating
process is controlled and recoverable — are never measured at all. The section becomes a
complaint where a characterisation was owed.

## Build the clause table at design time

Split each supplied file's description at its own conjunctions. A single sentence routinely
carries three assertions and only the first one ever gets measured. One row per assertion:

| asserted (verbatim) | quantity that would test it | how measured | measured value | agrees? |
|---|---|---|---|---|

Write the first three columns before any result exists. Every row must have a measurement named
in it, including the rows that are adjectives.

## The clauses that get skipped, and how to measure them

Counts, class balance and the feature schema are the easy rows and usually the only ones anyone
fills. Three families get dropped, and they are cheap:

**Variety of contents.** How many distinct entities, categories, tokens or values occur; how
concentrated they are — share held by the most common few, entropy, effective number of
categories; whether that distribution differs between the splits. A count of distinct values with
no distribution behind it is not a characterisation of variety.

**Structural variety.** Item size (elements, nodes, tokens, residues, time steps): minimum,
median, maximum and the histogram. Whatever the internal structure is — connectivity, degree,
branching, sparsity, ordering — as a distribution. How many distinct structural patterns occur and
how often each recurs. Then the same statistics per split, on shared axes, so drift is visible
rather than assumed absent.

**How the data was generated, and whether that is controlled.** Look for the generator before you
conclude there isn't one: a seed, a script, a rule, parameter ranges, a version string, a
provenance field inside the file itself. State what you found and what you were able to reproduce
— can the file be regenerated; do the labelled and unlabelled portions come from one process or
several; is there a recoverable rule separating the classes. If a generating rule is recoverable,
state it: it bounds what any model can extract, and it is a genuine result about the data. If it
is not recoverable, say which of the three (seed, rule, parameter ranges) is missing.

Each of these is a handful of lines over files you already loaded, and cheaper than any modelling
step in the run.

## Describe first, adjudicate second

Where a measurement disagrees with the prose, that is a row with two values in it and one sentence
of comment. Then the table keeps going.

The failure is the pivot: one contradicted clause becomes the section's thesis, the remaining
clauses are never measured, and the section closes by concluding the data cannot support the
study. That verdict may even be right, and it is still the weakest possible version of itself,
because it rests on the two clauses that were easy to check and says nothing about the three that
were not. A reader who asked whether the data is what it claims gets an argument that it isn't,
based on a minority of its claims.

An argument that the inputs are unfit is a strong claim and needs the full characterisation
underneath it, not instead of it. (`run-the-requested-analysis` covers not letting that verdict
replace the study. What is here is the measurement recipe that has to exist before the verdict is
worth stating at all.)

## What the data section contains

- One subsection per supplied file, with the file's name in the heading.
- That file's clause table, complete, with the measurement column filled in every row.
- Two or three panels: the size or length distribution, the composition or category distribution,
  the label distribution — every split on shared axes in each panel.
- One paragraph per file on what its measured properties *enable and bound* for the rest of the
  study: which analyses are supported at this size and balance, which are not, what the variety
  and the generating process imply about what can be learned.
- Where the file is synthetic or a simulation, what it does and does not reproduce about the real
  thing, in the same terms the description uses.

## Where this sits next to `the-supplied-item-is-the-graded-unit`

That skill covers a single named object shipped in `data/` — report that object's own quantities
under its own name, and print the object rather than pointing at a path. This is the corpus case:
a whole file whose description makes several claims about a population, where the loss is not a
missing identifier but the clauses nobody turned into a number. Run both when a task ships both.

## Checklist

- [ ] Every clause of every supplied file's description is a row in one table.
- [ ] Each row names its measurement and puts the measured value beside the assertion.
- [ ] The qualitative clauses have numbers under them: distinct counts, concentration,
      distributions, structural pattern counts.
- [ ] Generation and provenance were investigated, and the answer is stated either way.
- [ ] Every split is measured the same way and plotted on shared axes.
- [ ] A disagreement is a row, and the rest of the table is filled in anyway.
- [ ] No verdict about the data's fitness appears before the characterisation it rests on.
