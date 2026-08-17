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

`earth-inter-technique-spread-is-a-result-not-a-caveat` covers what the value
grid has to say once it exists, and `earth-report-the-lattice-and-show-the-field`
covers the lattice it is drawn over. Follow both. This skill is the two failures
upstream of them: filling the grid with counts, and disqualifying the columns
that would have filled it with values.

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
study is actually about - which technique reports the most change, which two
disagree and where - and it means the comparison exists no matter what happens
to the rest of the run.

## A no-peek rule governs the estimator, not the report

Holding the published product out of your rebuild is good discipline: it is what
makes "we recovered the published series from the raw inputs" a claim rather than
a tautology, and it is worth instrumenting. The rule has a scope, and the scope
is the estimator. It says nothing about what may be plotted.

The failure is to extend it to the exhibit. A quantity read off the released
columns then gets treated as contaminated: it is fenced with a provenance
caveat, or reported as coming from a different population than the arms, or
moved into Limitations. The reconciliation the task exists to deliver then
appears in the report only as a weakness of the study, and a reader looking for
it finds nothing.

Three rules keep the scope where it belongs.

1. **Released, rebuilt and published are three labelled series, not three tiers
   of admissibility.** Plot them on the same axes, label each in the legend, and
   state the residual between them in one clause. Every one of them is data.
2. **A population mismatch is a recompute, not a demotion.** If the offsets you
   measured came off the released columns and your arms re-ran the pipeline on
   the raw inputs, run the same script against the arms' output and print both.
   That is a script, not a study.
3. **A scope condition travels in the same sentence as the number, in Results.**
   If it cannot be stated in one clause beside the value, it is not a caveat, it
   is a reason to recompute.

## What the value grid carries

- One reference technique, chosen as the one with the most complete coverage and
  named as the reference on the canvas.
- Every other technique's offset from it, per unit, with an interval, on that
  technique's own observing window rather than the intersection of all of them.
- The cross-unit mean offset per technique, with its dispersion, printed inside
  the panel, and the two or three units where it is largest named there too. The
  disagreement almost always lives in two places and those two places are the
  finding.
- The combined series' position inside or outside the spread of its inputs.

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
matrix as a planned figure slot: nineteen rows, five method columns, every cell
annotated, marginals on two sides, a careful footnote reconciling three file
counts. Every cell held a count of submitted files. The same archive shipped
`altimetry_mwe`, `gravimetry_mwe` and `demdiff_and_glaciological_mwe` columns
per region per year in its results directory - the whole decomposition, aligned,
with error columns beside each. The run computed a cross-region mean absolute
inter-method difference from exactly those columns, then wrote it into a
Limitations bullet with a scope caveat welded on, because the columns came from
the released product rather than from its own rebuild arms. The criterion asking
for the inter-technique comparison scored 3.3 of 100 against 48.0 for a plain
agent that drew the offsets and printed them; that item carried a fifth of the
task's weight and was the single largest loss in the pair.
