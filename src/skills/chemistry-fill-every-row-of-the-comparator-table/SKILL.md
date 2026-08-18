---
name: chemistry-fill-every-row-of-the-comparator-table
description: Use at literature stage and study design when the source publishes performance broken out by class of system, and you are about to choose your evaluation panel with a filter written for throughput. Covers transcribing the table as rows, auditing the inclusion filter against those rows before it is frozen, and buying one target per row before a second target for any row.
stages: 01_literature_survey, 03_study_design, 05_experimentation
---

# Every row of the comparator table needs an arm of yours

## What goes wrong

At literature stage you extract the incumbent's performance table — the one that
breaks accuracy out by class of system — and you put it in a comparator section,
correctly cited. Then you choose the panel you will actually run, and you choose it
with a filter written for throughput: a size window, a component or chain count cap,
"whatever the implementation supports as input", an availability or deposit-date cut,
a per-target runtime ceiling. Finally you stratify your own results along an axis
your hypotheses distinguish, which is not the table's axis.

Each step is defensible. Together they delete whole rows of the table, and nothing
downstream notices, because the filter is written in a vocabulary the rows do not use
— it selects on size or on tooling, and the rows are classes. The published number
for the deleted row survives in your report as a quotation with nothing of yours
beside it. A reader looking for your result on that class finds a citation.

This costs more than it looks. A per-class claim is graded per class, so a missing
row reads as work not done rather than as coverage foregone. And a claim that one
method handles several classes — "general-purpose", "unified", "one model for all of
them" — is supported only by the same model run unchanged on each class. Depth inside
one class does not substitute, however many targets that depth contains.

## What to do

**1. Transcribe the table as rows, while the paper is open.** Not as prose. One row
per class the source's own table distinguishes, each carrying: the class name in the
source's words, the published value, the metric's exact definition, its threshold and
its N. Write it to `notes/comparator_rows.json` before any design exists. A prose
paraphrase loses the axis, and the axis is the only part that matters here.

**2. State the inclusion filter as an explicit predicate, then run it against the
rows.** Before the panel is frozen, write the filter as a list of conditions a
candidate system must satisfy. For each row of the table, name at least one candidate
that satisfies all of them. A row with no passing candidate has been deleted by your
filter, and you now have three options, each of which is a decision taken on purpose:

- widen the filter, or carve an exception for that row — usually the right answer,
  because one target costs one run;
- fill the row with a cheaper surrogate and label it as a surrogate;
- record the row as unfillable, naming the exact condition that excludes it and the
  price of relaxing that condition.

Filters that delete rows silently, in rough order of frequency: a size or length
window; a component, chain or subunit count cap; what your chosen implementation
happens to accept as input; data or structure availability; a per-target runtime or
memory ceiling; licence. Every one of them correlates with class membership, which is
exactly why the deletion is invisible from inside the filter.

**3. Allocate one target per row before a second target for any row.** The panel's
first N runs buy N classes, not N members of the most convenient class. Breadth along
the table's axis is the deliverable; breadth within a row is a refinement of a row you
already have.

**4. Stratify the reported results on the table's axis.** Add your own stratification
— by input type, by data source, by whatever your hypotheses distinguish — as a second
cut. It does not replace the first. If the primary results figure is broken out along
an axis the comparator table does not use, the reader cannot lay the two side by side,
which was the point of extracting the table.

**5. Compute your value in the row's own metric definition and threshold**, so it
lands in the same column as the published one; your preferred metric goes beside it,
never instead of it. `chemistry-canonical-units-thresholds-incumbent` covers the unit
and threshold discipline, `use-the-sources-own-names` covers carrying the class names
into your headings.

## What ships

One table, every row of the source's present, your column beside theirs:

| class (source's name) | published value | N | your value, same definition | N | delta, or the reason the cell is empty |

An empty cell carries the reason and the price of filling it, never a blank. A row you
decided not to run is a decision reported in one clause; a row nobody noticed is an
absence.

## The check, before writing

Take the class names out of `comparator_rows.json` and grep the report for each, with
word boundaries. A class that appears only in the related-work or comparator section,
and never in a results heading, a table row or a figure label, is one you cited
instead of measured. The check takes a minute, and it is the last point at which one
extra run can still close the gap.

## How this differs from its neighbours

`mine-the-papers-you-were-given` builds the list of proper nouns the supplied papers
attach to results and forces a run / compare / say-why-not decision on each.
`run-the-conditions-the-source-ran` covers the named experiments and scenarios.
`information-fill-the-whole-results-grid` covers filling a published grid at reduced
N. What is here and not in any of them is the **filter audit**: the population you
allowed yourself to draw from was chosen for cost, in a different vocabulary from the
table's rows, and that is the mechanism by which a run that read the table carefully
still finishes with no arm behind half of it.
