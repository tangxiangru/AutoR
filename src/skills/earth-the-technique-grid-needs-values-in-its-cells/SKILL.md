---
name: earth-the-technique-grid-needs-values-in-its-cells
description: Use at study design when the figure list is chosen, at implementation before any pipeline code is written, and again at analysis, when the supplied archive is stratified by measurement technique or instrument and you are about to describe that stratification. Covers reading the per-technique columns the archive already ships, drawing the technique grid with estimates in it rather than file counts, and why a no-peek rule about the reference product must not reach your figures.
benchmarks: researchclawbench
applies_when: DEM differencing|gravimetry
stages: 03_study_design, 04_implementation, 06_analysis
---

# Earth: a cell count is not a cell value

You will draw the grid. An archive stratified by measurement technique invites a
technique-by-unit matrix almost at once, and it is the right picture — but the
first version of it holds how many files fall in each cell, and that version
answers a filing question. The deliverable is the same grid with the *estimate* in
each cell. Draw both, in that order, and never let the first stand in for the
second.

The two look almost identical — same rows, same columns, same annotated cells,
same marginals — which is exactly why the substitution goes unnoticed. Nothing
internal flags it, because the picture that was planned did get drawn, on time,
under its planned filename.

What the value grid has to *say* once it exists is not this skill's subject and is
already written down: `earth-inter-technique-spread-is-a-result-not-a-caveat` for
the reference technique, each technique's own observing window, rate against
interannual variability, what to do when a statistic sits on a different
population from your arms, and where the offsets have to be printed;
`earth-report-the-lattice-and-show-the-field` for the lattice it is drawn over.
Follow both. This skill is the two failures *upstream* of them — the two ways a
run arrives at analysis with no per-technique values to put anywhere.

## Read every column header before you write any pipeline code

Open the header line of every supplied file, including the ones in a directory
whose name says results rather than inputs.

An archive that publishes a combined or consensus series almost always publishes
the per-technique series beside it: one column group per technique, each carrying
a value, an error, and often a variability column that tells you whether that
technique contributed the trend or only the year-to-year wiggle. Those columns
*are* the decomposition. They already sit on your unit index and your time index,
they carry their own uncertainties, and turning them into the per-technique
comparison is a groupby and a subtraction.

Count them before you plan. If most of the columns in the file you are about to
read for one combined series belong to individual techniques, then the archive's
own view of itself is stratified, and a plan that reads only the combined column
has discarded the majority of what was shipped.

Do that arithmetic in the first hour, before the analysis plan is frozen, and
write the offsets to a results file. It costs minutes, it tells you what the study
is actually about — which technique sits furthest from the others, and where they
disagree most — and it means the comparison exists no matter what happens to the
rest of the run.

## A no-peek rule governs the estimator, not the report

Holding the published product out of your rebuild is good discipline. It is what
makes "we recovered the published series from the raw inputs" a claim rather than
a tautology, and it is worth instrumenting. But the rule has a scope, and the
scope is the estimator. It says nothing about what may be plotted.

The failure is to extend it to the exhibit. A quantity read off the released
columns then gets treated as contaminated: fenced with a provenance caveat,
labelled as describing a different population from your arms, or moved into
Limitations. The comparison the task exists to deliver then survives only inside a
list of the study's own shortcomings, which is not where a reader goes looking for
a result — and it is a strange place to put the one thing you were asked for.

Released, rebuilt and published are three labelled series, not three tiers of
admissibility. Plot them on the same axes, label each in the legend, state the
residual between them in one clause, and let the reader see all three. Every one
of them is data.

A scope condition of this kind is usually true and almost never a reason to
demote. If yours is real, `earth-inter-technique-spread-is-a-result-not-a-caveat`
says what to do with it, and what it says is that the fix costs a script.

## Before you finish

List the figures you are shipping and, for each one whose axes are the archive's
own stratification, say what is inside the cells. If the answer for every such
figure is a count, a coverage flag, or a residual against a reference version of
your own series, then the strata exist in the report as an inventory and the
quantity they stratify has never been shown per stratum.

Then read your Limitations section looking for units. Any physical quantity with a
unit that appears there and nowhere in Results is a result you measured and then
disowned.

## Why this is here

A run on a multi-technique reconciliation archive drew the technique-by-region
matrix as a planned figure slot: nineteen region rows, five method columns, every
non-empty cell annotated, marginal bars on two sides, and a footnote reconciling
the shipped file count against the published submission count. Every cell held a
`used/excluded` count of submitted files, and the run's own figure manifest
recorded the slot, in those words, as "counts, not estimates". It never drew the
same grid with a rate in it. Ten figures reached the report and not one of them
shows a rate per technique.

The columns were there. Each of the archive's nineteen per-region result files
carries the same twenty-three-column header, and fifteen of those twenty-three are
per-technique — three techniques, each with a mass column, a specific-mass column,
an error column for each, and a variability column. The run found them: it
computed a mean absolute inter-method difference across twenty-seven
region-method pairs in thirteen regions, and then filed it in Limitations behind a
note that it described a different population from its own arms, because the
columns came from the released product rather than from its rebuild. That
statistic and the phrase "inter-method" occur in the shipped report exactly three
times between them, all three inside the Limitations section, none in Results. The
one figure that does compare methods carries a footnote saying, in the run's own
words, that its arms describe the reconciliation itself and not a re-average of
the released per-group columns — the no-peek rule, travelling from the estimator
onto the picture.

The criterion asking for the inter-technique comparison scored 3.3 of 100 against
48.0 for a plain agent that drew the per-technique offsets, printed them in
Results, and read one of its three techniques straight out of the source's own
published figure data. That criterion carried a fifth of the task's weight and was
the single largest loss in the pair.
