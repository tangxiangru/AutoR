---
name: every-claim-in-the-data-description-is-a-result
description: Use at literature survey and study design, when you first read the task's description of each supplied data file, and again at analysis. Covers turning the description's counts, values, shapes and purpose clauses into a verification list the report answers row by row, on the supplied rows themselves.
stages: 01_literature_survey, 03_study_design, 06_analysis
---

---
name: every-claim-in-the-data-description-is-a-result
description: Use at literature survey and study design, when you first read the task's description of each supplied data file, and again at analysis. Covers turning the description's counts, values, shapes and purpose clauses into a verification list the report answers row by row, on the supplied rows themselves.
stages: 01_literature_survey, 03_study_design, 06_analysis
---

# The description of a supplied file is a list of claims you can test

The brief describes each file it ships: how many rows and columns, what a row
is, what value it centres on, what shape and span it has, what trend runs across
its columns — and, in the clause almost everyone skips, what the analysis it
stands in for is *for* ("such data are used to ...", "critical for understanding
... and for guiding ...", "used to evaluate ...").

Every one of those is a checkable assertion, and the purpose clauses are an
analysis specification. They are also the shortest route to the quantities a
reader of this task expects, because whoever wrote the description wrote it from
the analysis you are being asked to reproduce.

Two rules below carry most of the value and are the ones runs skip: a claim
about *spread* needs an interval drawn on the axes, not an adjective in prose;
and a verification list whose every verdict is "differs" is a fidelity audit,
which is a different document from the one you were asked for.

## The failure this prevents

A run profiled every supplied file in its first stage and wrote each median,
quartile, span and trend to a results JSON — the deliverable numbers existed on
disk within the hour. They reached the report only inside a deviation table,
measured against values the run had recomputed from an external release it had
found. So the descriptions' claims were never answered in the affirmative form:
no "the file's centre is X, as described", no shape check, no span check, and
not one purpose clause became a named analysis with a figure slot. Its coverage
table was complete — one row per demand, every row filled — and every row was
filled with the other population's number.

The tell is a verdict column with no "as described" in it.

Where a description said the scatter widens across an index, the run drew
interval bands on the external curves and no interval at all on the supplied
series, so the claim it was asked to check was not visible on any axes in the
report.

## What to do

1. At literature survey, write `notes/supplied_claims.json`: one row per
   assertion in each file's description, tagged by kind.
   - **structure**: row count, column count, what one row is, what one column is.
   - **numeric**: a stated centre, a stated range or span, a stated per-group
     value, a stated ratio between columns.
   - **shape/trend**: the distribution family, monotonicity across an index,
     "the scatter also grows", "a long tail toward".
   - **purpose**: the "such data are used to ..." clause, verbatim.
2. Test the structure, numeric and shape rows **on the supplied file itself**,
   one measured number each, and record `stated`, `measured`, `verdict`.
   - `stated` is the brief's own value and nothing else. Substituting a value
     you recovered externally — the release's number, the paper's number, your
     recomputation — turns a verification into a fidelity audit and guarantees a
     column of "differs". If you want that comparison, it is a fourth column
     called something else, in a later section.
   - Do not round the measured value onto the stated one. A brief that says a
     job takes "about 30 minutes" against a measured 32.4 minutes is an
     agreement worth printing, and 32.4 is the number you quote from then on.
3. A shape or trend claim needs a statistic, not an adjective. A named
   distribution family is a fit and a goodness measure; "the scatter grows
   across the index" is a named percentile interval at each index level and its
   width; "a long tail" is a quantile ratio. **Draw the interval on the figure**,
   not only in prose — a location curve with no band cannot show a claim about
   spread, and a reader checking a spread claim looks at the axes first.
4. Promote every purpose clause to a named analysis with its own figure slot at
   study design. "Used to assess the overall uncertainty of X" is an instruction
   to produce the overall-uncertainty statement for X. "Critical for
   understanding how A varies across B, and for guiding C" is two deliverables:
   the variation of A across B, and what it implies for C.
   The figure that discharges a purpose clause about file X is drawn from X's
   own rows and carries X's filename in the caption. A purpose clause answered
   from any other population — a bigger corpus, an authentic release, your own
   simulation — leaves the row open, no matter how much better that population
   is.
5. Where two descriptions refer to the same reference quantity, or one is
   described relative to another, the comparison between the files is itself a
   claim. Produce it: put the channels on one axis, mark the reference value as
   a labelled line, and state the ordering and the factor — measured on the
   supplied files, both sides.
6. Publish the verification list in the report as a short stated/measured/verdict
   table, and make sure each affirmative row also appears as a sentence or an
   in-panel annotation beside the figure it belongs to. A number that lives only
   in `outputs/` has not been reported, and a number that lives only in a
   coverage table has been reported to a reader who is not reading that table.
7. A claim you find false is a result: give the measured value, the direction and
   the size, and leave the affirmative rows standing around it. One falsified row
   does not license reframing the rest of the list as an exposé.

## Before you finish

Walk `notes/supplied_claims.json`. Every row needs a measured number in the
report, a verdict, and — for purpose rows — the named figure, drawn from that
file, that answers it. Then count the verdicts: if none of them is "as
described", you audited the data instead of using it.
