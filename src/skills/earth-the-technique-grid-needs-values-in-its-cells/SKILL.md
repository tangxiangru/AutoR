---
name: earth-the-technique-grid-needs-values-in-its-cells
description: Use at study design when the figure list is chosen, at implementation before any pipeline code is written, and again at analysis, when the supplied archive is stratified by measurement technique or instrument and you are about to describe that stratification. Covers drawing the technique-by-unit grid twice - once with counts, once with estimates - reading the per-technique columns the archive already ships, and why a no-peek rule about the reference product must not reach your figures.
applies_when: DEM differencing|gravimetry
stages: 03_study_design, 04_implementation, 06_analysis
---

# Earth: a cell count is not a cell value

You will draw the grid. An archive stratified by measurement technique invites a
technique-by-unit matrix almost at once, and it is the right picture - but the
first version of it holds how many files fall in each cell, and that version
answers a filing question. The result is the same grid with the *estimate* in
each cell: the rate, its interval, and the years that technique actually
observed there. Draw both, in that order, and treat the second as the
deliverable. A run that ships only the first has inventoried the archive and
called it an intercomparison.

The two grids look almost identical - same rows, same columns, same annotated
cells, same marginals - which is exactly why the substitution goes unnoticed.
Nothing internal flags it, because the picture that was planned did get drawn.

This skill is the two failures upstream of the value grid: filling it with
counts, and disqualifying the columns that would have filled it with values.
Two other skills cover the grid itself, and you should follow both.
`earth-inter-technique-spread-is-a-result-not-a-caveat` is what the value grid
has to say once it exists - the reference technique, each technique's own
observing window, rate against interannual variability, and where the offsets
have to be printed. `earth-report-the-lattice-and-show-the-field` is the lattice
it is drawn over.

## Read every column header before you write any pipeline code

Open the header line of every supplied file, including the ones in a directory
whose name says results rather than inputs. An archive that publishes a combined
or consensus series almost always publishes the per-technique series beside it -
one column group per technique, each with a value, an error and often a flag
saying whether that technique carried the trend or only the year-to-year
variability. Those columns *are* the decomposition. They already sit on your
region index and your annual index, they carry their own uncertainties, and
turning them into the per-technique comparison is a groupby and a subtraction.

Do that arithmetic in the first hour, before the analysis plan is frozen, and
write the offsets to a results file. It costs minutes, it tells you what the
study is actually about - which technique sits furthest from the others, and
where they disagree most - and it means the comparison exists no matter what
happens to the rest of the run.

## A no-peek rule governs the estimator, not the report

Holding the published product out of your rebuild is good discipline: it is what
makes "we recovered the published series from the raw inputs" a claim rather than
a tautology, and it is worth instrumenting. The rule has a scope, and the scope
is the estimator. It says nothing about what may be plotted.

The failure is to extend it to the exhibit. A quantity read off the released
columns then gets treated as contaminated: it is fenced with a provenance
caveat, or reported as coming from a different population than the arms, or
moved into Limitations. The comparison the task exists to deliver then survives
only inside a list of the study's own shortcomings, which is not where a reader
goes looking for a result.

Released, rebuilt and published are three labelled series, not three tiers of
admissibility. Plot them on the same axes, label each in the legend, and state
the residual between them in one clause. Every one of them is data. If the
statistic you measured sits on a different population than the arms you
preregistered, the pinned skill named above tells you what to do with it, and
what it tells you is that the fix costs a script.

## Before you finish

List the figures you are shipping and, for each one whose axes are the archive's
own stratification, say what is inside the cells. If the answer for every such
figure is a count, a coverage flag or a residual against a reference version of
your own series, then the strata exist in the report as an inventory and the
quantity they stratify has never been shown per stratum.

Then read your Limitations section looking for units. Any physical quantity with
a unit that appears there and nowhere in Results is a result you measured and
then disowned.

## Why this is here

A run on a multi-technique reconciliation archive drew the technique-by-region
matrix as a planned figure slot: nineteen region rows, five method columns,
every non-empty cell annotated, marginal bars on two sides, and a footnote
reconciling the file count against the submission count. Every cell held
`used/excluded` counts of submitted files, and the run's own figure manifest
recorded the slot as "counts, not estimates". It never drew the same grid with a
rate in it. The same archive shipped `altimetry_mwe`, `gravimetry_mwe` and
`demdiff_and_glaciological_mwe` columns per region per year in its results
directory - the whole decomposition, aligned, with an error column and an
annual-variability column beside each. The run computed a mean absolute
inter-method difference from exactly those columns, then filed it under Limitations
behind a note that it described a different population from its own arms,
because the columns came from the released product and not from the rebuild; the figure directory
holds ten figures and not one of them carries a per-technique estimate. The
criterion asking for the inter-technique comparison scored 3.3 of 100 against
48.0 for a plain agent that drew the offsets and printed them in Results; that
item carried a fifth of the task's weight and was the single largest loss in the
pair.
