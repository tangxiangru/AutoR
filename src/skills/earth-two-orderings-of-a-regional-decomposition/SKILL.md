---
name: earth-two-orderings-of-a-regional-decomposition
description: Use at study design when the figure and table plan is fixed, at analysis, and again at writing, whenever the deliverable splits a global or basin-wide total into per-region parts and you are about to report each part as an absolute rate. Covers the two normalisations every row owes and why their disagreement is the result, where the intensity denominator has to be captured before you need it, and what the spare cell of a small-multiple grid is for.
benchmarks: researchclawbench
applies_when: 19 global glacial regions|regional and global glacial mass change
stages: 03_study_design, 06_analysis, 07_writing
---

# Earth: a regional table has two orderings, and both are results

`earth-report-the-lattice-and-show-the-field` tells you to build the per-stratum
grid and to name and rank the regions that dominate the total and the ones
carrying the largest relative change. Follow it. This skill is what that one
instruction actually costs, because those are not one ranking but two, over two
columns, with two different denominators — and only one of the two denominators
is free.

A per-region decomposition reported as one absolute column per region is a
deliverable that has been computed and not read. Absolute magnitude is the number
that says least, because in every regional decomposition this field produces it
is dominated by how much of the stock each region holds. The two questions a
reader arrives with are which regions supply most of the total, and which regions
are changing fastest relative to themselves. The gap between those two answers is
what the decomposition is for.

## Three numbers per row, not one

1. **The absolute change**, with its interval, in every unit the brief names. If
   the brief names two units, both belong in the exhibit; one on the axis and the
   other in a CSV is one unit reported.
2. **The row's share of the total**, in per cent, with the total stated. This is
   the attribution column, and it decides where a reader looks.
3. **The change normalised by that region's own stock at the start of the
   record**, in per cent. This is the intensity column, and it is the only one in
   which small regions are visible at all.

Then rank the table by column 2 and again by column 3, write both lists into the
prose with their percentages, and **say in a sentence that the two orderings
disagree** — the regions that dominate the total are large and slow, the regions
losing the largest share of themselves are small and fast, and a reader who has
only the absolute column will draw the wrong conclusion about which places are in
trouble. That sentence is a result and it costs one line of sorting.

Do not let the two normalisations blur into one. A share is a fraction of the
aggregate result; an intensity is a fraction of the region's own initial state.
They rank differently, which is the entire point. And the interval on a share is
not the interval on its numerator — propagate it or say you did not.

## Capture the intensity denominator when it passes through your hands

The share denominator is free: it is the total row of your own table, so the
shares are exactly as defensible as the aggregation that produced it. State the
aggregation, and state whether the regional rows sum to the global row or whether
a basis difference stands between them.

The intensity denominator is a **stock**, and it is the one that goes missing,
because an archive of change ships fluxes and areas — not stocks. So it arrives,
if it arrives at all, through a side door: the source's own headline table, which
you will parse early for its published rates and which in this field almost
always carries an area column and an initial-mass column beside them.

**When you parse the source's table, keep every column, including the ones your
analysis plan has no use for.** That plan was written to reproduce the source's
rates; the columns it ignores are the denominators of statistics you have not
decided to compute yet. A column dropped at parse time — or parsed, recorded, and
marked "not reproducible from the inputs" — is a whole ranking you cannot produce
at writing time, and by then the table is three stages behind you.

If it genuinely is not in the source's table, the stock is an area or volume
column times a stated conversion, or the standard inventory the field maintains
for this quantity. Both are minutes of work. Whichever route you take, name the
constant or the source in the caption, and attribute an external value the way
`a-value-you-did-not-measure-still-has-a-source` describes.

## The spare cell, and what does not go in a panel

Two things the lattice skill does not settle, both of which decide whether the
grid carries the numbers above:

- **Give the grid an aggregate panel.** A nineteen-region grid drawn on a
  four-by-five layout has a twentieth cell. If the legend is in it, you have spent
  the total on furniture. Put the legend in a panel's empty corner, give the cell
  to the aggregate, and draw it in the same layout so it reads as a member and not
  a caption.
- **The panel annotation is for the physical numbers** — the absolute rate in each
  unit, and the fraction of that region's own initial stock. A residual against a
  reference version of your own series is not one of them. It is a validation
  statistic, it belongs in the validation figure, and a grid annotated with it
  tells a reader how well you rebuilt something without telling them what the
  thing is.

Order the panels by a quantity rather than by index or alphabetically, and say
which quantity in the title. The ordering is free ranking information.

## Before you finish

Take your regional table and ask three questions of it. Can a reader name the
regions that supply most of the total, with percentages? Can they name the ones
losing the largest fraction of themselves, with percentages? Are those two lists
different, and does a sentence say so? If the table has one numeric column per
unit and no per cent sign anywhere in it, the decomposition has been tabulated and
not interpreted.

## Why this is here

Two runs on the same regional-decomposition task drew the same nineteen-panel grid
from the same archive, and the criterion covering the regional split separated
them by 36 points.

The one that scored well annotated every panel with three numbers — the rate in
each of the brief's two units, and the fraction of that region's initial mass
lost — put an aggregate panel in the twentieth cell in a contrasting colour, and
wrote two ranked lists into its results prose with a clause saying the second ran
the other way to the first.

The other annotated every panel with the maximum absolute residual between its own
rebuild and the published release, put the legend in the twentieth cell, carried
one of the brief's two units on the axis, and shipped a per-region table made
entirely of its own values set against the published ones: inside-or-outside
verdicts and signed residuals, no share column and no intensity column.

Both columns were within reach. Its own appendix table already held every regional
rate and the aggregate row, so the shares were a division away in a grid of
numbers it had already typeset — computed afterwards from that table alone, the
largest shares land within a percentage point of the ones the source published.
And the stock was not missing either: the run had parsed the source's headline
table into its own literature directory, third column `Mass in 2000 (Gt)`, and had
written the global figure into its own notes under the status `n/a`, on the
grounds that it could not be reproduced from the supplied inputs. Searched by
byte, the phrase appears in six of that run's 227 literature files and in none of
its 43 code files, none of its 44 results files, none of its 10 figures and none
of its 11 report files. The arm that scored well carried the same column out of
the same table into three of its thirteen scripts, into its output table, and into
every panel of its grid.
