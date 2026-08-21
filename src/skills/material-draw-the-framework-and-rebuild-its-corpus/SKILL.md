---
name: material-draw-the-framework-and-rebuild-its-corpus
description: Use when the brief asks for a framework combining several named components over a curated input resource, and only a labelled subset of that resource was supplied. Covers the overview figure no data script will ever emit, reconstructing the described corpus yourself, and the placeholders and empty panels that reach the delivered report.
benchmarks: researchclawbench
stages: 03_study_design, 04_implementation, 06_analysis, 07_writing
---

# The framework is a deliverable, and its picture has no dataframe behind it

A brief that opens "develop a framework combining A, B and C" is asking for the
assembled object, not only for the three components working separately. Every
stage of the run then produces its own plots, and none of them produces the
picture of the whole, because every figure a data pipeline emits comes from a
table and the overview schematic comes from no table. Nothing in an
analysis-driven figure script will ever create it. What ships instead is a
Methods paragraph promising a diagram, or — often enough that it is worth
grepping for — a placeholder comment left in the delivered report where the
diagram was going to go.

The other half of the same criterion is the input resource. The brief describes
a curated design space of a stated size and hands you a small labelled subset of
it. "The full corpus is not shipped" gets written down as a finding and the run
stops there. It is not a finding, it is a task: that space is a combinatorial
object over component pools you can obtain, enumerating it is cheap, and without
it nothing in the report says anything about the reach of the framework — only
about the subset someone else already scored.

## Study design: reserve slot zero

Before any hypothesis-driven or analysis-driven figure slot, reserve the first
one for the framework overview, and write down its panels: the schematic, the
input resource and its characterisation, then one panel per named component.
First slot, not last — the last slot is the one the budget eats, and this is the
figure the heaviest criterion is usually about.

## Build the schematic from the brief's own sentence

One box per noun in the brief's method chain, in the brief's own words, in the
order the brief writes them. Each arrow carries the object that flows and the
count that actually flowed: items supplied, items featurised, items simulated,
items trained on, candidates generated, candidates scored, candidates delivered.
Each box carries the metric that component actually reached, with the reference
or published value beside it where one exists.

Author it as code — graphviz, matplotlib patches, TikZ rendered to PNG —
committed beside the analysis scripts and rendered into the image directory like
any other figure, so it is regenerated rather than remembered.

A component that ran at reduced scale appears here as a number in its box next
to the reference number. That is readable, and it is a result. A hole is not.

Forbidden in this figure and in every other: a placeholder token, an empty
panel, an empty axis category held open for an arm that did not run, and a title
that states the status of an internal hypothesis or plan item instead of what
was found. Before the writing stage ends, grep the delivered report and the
image directory for `TODO`, `PLACEHOLDER`, `FIXME` and unrendered comment
markers, and grep your figure titles for internal identifiers. Fix or delete
every hit; a placeholder in a shipped file is read as the section not existing.

## Implementation: rebuild the resource the source describes

If the brief or the source study describes an input resource of a stated size
and you were handed a subset:

1. Identify the component pools it is a product or a selection over, and the
   rules that admit a component.
2. Obtain those pools from public databases, applying the source's stated
   filters, or your own filters stated explicitly.
3. Enumerate to the stated order of magnitude, or as close as memory allows, and
   say which of the two you did.
4. Characterise the result: counts per component class, the property or
   accessibility distribution over the whole space, how many of the supplied
   labelled rows fall inside your reconstruction, and what fraction of the space
   your generator can actually reach.
5. Record provenance: database, version or access date, each filter with counts
   before and after. A reconstructed resource without provenance cannot be used
   by anyone, including you at writing time.

If the rebuild is genuinely out of reach, the panel becomes the supplied subset
characterised in exactly that form, with its size against the stated size and
one sentence on what the gap prevents. That is much weaker, so take it only
after an attempt you can describe.

## Analysis: collect the components into one image

One panel per named component, in the same figure as the schematic, each in the
form its field uses: the primary simulated or measured trace the property was
fitted from — not only the fitted scalar — the calibration parity against the
reference, the learned component's reconstruction and validity, the search
trace, the delivered candidates in the property space.

`material-as-specified-run-and-stage-diagnostics` already requires each stage's
default diagnostic to exist. What this adds is the collection: a criterion about
a framework is about the assembled object, and a dozen conventional plots in a
dozen separate files do not add up to one. `the-canonical-figure` will not
produce it either — there is no field-standard plot whose data is "the
framework", which is exactly why it goes missing.

## Checklist

- [ ] Overview slot reserved before any other figure slot.
- [ ] Schematic authored as code, one box per component named in the brief, in
      the brief's words.
- [ ] Arrows carry realised counts; boxes carry realised metrics against
      reference values.
- [ ] Input resource rebuilt to its stated order of magnitude, or the shortfall
      stated with the attempt described.
- [ ] Provenance recorded for every external pool used in the rebuild.
- [ ] Characterisation panel: composition, property or accessibility
      distribution, overlap with the supplied subset, reachable fraction.
- [ ] One panel per named component, collected into the overview figure.
- [ ] Placeholder grep over the delivered report returns nothing; no empty
      panel, no empty axis category, no internal identifier in a figure title.
