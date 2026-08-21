---
name: energy-build-the-domain-the-question-names
description: Use at study design, and again before implementation is frozen, whenever the supplied sample table covers a smaller area, population or period than the question does — especially when another supplied file (a boundary layer, a network, a catalogue, an administrative lattice) spans the whole of it. Covers telling a fixture from a domain, and building the evaluation lattice you were not handed.
benchmarks: researchclawbench
stages: 03_study_design, 04_implementation
---

# The supplied table is a sample. The question's domain is a thing you build

Tasks in this field ship two kinds of spatial file: a small tabular sample, and
a full-extent geometry beside it — a boundary layer, a network, a site
catalogue, an administrative lattice. The sample is a fixture the original model
was exercised on. The geometry is the domain the question is about. When the two
disagree about extent, the gap between them is the work, not a limitation to
declare.

## The failure this prevents

A task named its domain in one sentence — a whole region, a class of buildable
sites, a target year — and shipped a sample table covering a small fraction of
it next to a geometry layer covering all of it. One run audited the table and
proved every defect: rows bunched into one corner of the domain, rows that are
not admissible sites at all, supplied covariate columns that disagree with the
geometry when recomputed from it. Then it narrowed. It froze a scope rule
forbidding any result from carrying the domain's name, ran its cost chain over
the surviving rows, and shipped a study of them. Its own limitations section
named the missing datum in the form "the shipped file does not contain an
instance of X" — where X was constructible from the geometry it had been handed.
Two stages earlier it had fetched real per-coordinate inputs from public
services *at the sample's coordinates*, so the capability to populate a cell was
demonstrated and then exercised a few dozen times.

The comparator ran the same audit, reached the same verdict on the table, and
treated that verdict as a specification for the dataset it had to build: it
tessellated the shipped geometry at the resolution the source works at,
populated every cell from public reanalysis and from the source authors'
released code, and ran the same chain over all of them. It scored multiples
higher on every criterion about where the quantity is low, in less wall time.

Both runs knew the sample was unusable. One treated that as a finding about the
data; the other treated it as the first work item.

## What to produce, at study design

Write `notes/domain.md` before any model code, with four sections.

1. **The domain the question names.** Quote the task sentence and extract its
   extent, its population and its period, literally.
2. **The extent of every supplied layer.** One row per file: feature or row
   count, bounding box, units, and what fraction of the question's domain it
   covers. Compute these from the files. Do not read them off the description
   field in the task metadata — descriptions routinely overstate coverage.
3. **The verdict.** If a supplied layer already spans the domain while the
   sample table does not, you were handed the domain and a fixture. Record that
   the evaluation lattice will be built from the layer.
4. **The lattice.** Cell shape, cell size, cell count, and the exclusion rules
   the field applies (offshore, out-of-range, protected, inadmissible). Cell
   count is a number you state and a reader checks. Use the resolution the
   source works at, and say how you know what that is.

Then, for each input the model consumes, name the thing that can supply it for
every cell:

- a supplied column, if it survives your audit;
- a public per-coordinate service or reanalysis. Anything you can fetch for one
  point you can fetch for N: measure seconds per call, multiply, cache to disk
  keyed by coordinate, and put the fetch in its own resumable script;
- the source study's released code and parameter files. Its Code and Data
  Availability statement is a work item — see `mine-the-papers-you-were-given`
  for how to turn the proper nouns in a supplied paper into one. A released cost
  function is a reimplementation you do not have to validate; a released
  parameter file is an exact check on yours;
- a documented constant, with its source.

Pilot the whole chain end to end on a few dozen cells before scaling. Record
attempted, succeeded, seconds per cell, and multiply out. If the projection does
not fit the budget, coarsen the lattice. Do not shrink the extent.

## Widening does not drop the fixture

Run the supplied rows through the identical chain under their own identifiers,
and locate them in the full distribution: rank, percentile, and whether the best
supplied row is anywhere near the best cell. That comparison is a result — it
says what the fixture was and was not representative of. The rules for reporting
the shipped object under its own name are in
`the-supplied-item-is-the-graded-unit`; this skill only adds that the audit of
the supplied file is a section of the paper, not the paper.

## Before you leave study design

- Does any conclusion you plan to draw carry a narrower place, population or
  period than the question does? Name the dataset that would remove the
  qualifier, and either build it or write down why not.
- Grep your notes for sentences of the form "the shipped file does not contain
  X". If X is an instance you could construct, fetch or simulate, that is a work
  item, not a limitation.
- Are you excluding rows on a rule? Apply the same rule to the lattice and count
  what it removes there. An exclusion that trims a sample is a population
  decision; the same rule over a lattice is a map. Re-cost the rows you excluded
  before you freeze the population — an exclusion rule can remove exactly the
  cases that carry the answer.
- If a review, an obligation or a decision table offers you "widen the existing
  analysis" or "state the limitation plainly" as the two options, check whether
  "build the missing data" was simply never listed. A two-option menu whose
  options both keep the fixture cannot recover this, however many review rounds
  it survives.
- Cell count, cell size and extent go in the report's methods as three numbers,
  with the tessellation script that produced them and no tunable parameter in
  between.
