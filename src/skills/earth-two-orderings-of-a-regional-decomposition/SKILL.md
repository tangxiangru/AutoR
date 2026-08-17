---
name: earth-two-orderings-of-a-regional-decomposition
description: Use at study design when the figure and table plan is fixed, at analysis, and again at writing, whenever the deliverable splits a global or basin-wide total into per-region parts and you are about to report each part as an absolute rate. Covers the two normalisations every row owes, the two rankings they produce and why their disagreement is the result, the denominators you have to build before you can compute them, and what a small-multiple grid puts inside each panel.
applies_when: 19 global glacial regions|regional and global glacial mass change
stages: 03_study_design, 06_analysis, 07_writing
---

# Earth: a regional table has two orderings, and both are results

A per-region decomposition reported as one absolute column per region is a
deliverable that has been computed and not read. Absolute magnitude is one of
three numbers each row owes, and it is the one that says least, because in every
regional decomposition this field produces it is dominated by how much of the
stock each region holds. The two questions a reader arrives with are which
regions supply most of the total, and which regions are changing fastest
relative to themselves. Those are two different columns and two different
orderings, and the gap between them is what the decomposition is for.

## Three numbers per row, not one

1. **The absolute change**, with its interval, in every unit the brief names. If
   the brief names two units, both belong in the exhibit; one on the axis and
   the other in a CSV is one unit reported.
2. **The row's share of the total**, in per cent, with the total stated. This is
   the attribution column and it is the one that decides where a reader looks.
3. **The change normalised by that region's own stock at the start of the
   record**, in per cent. This is the intensity column, and it is the only one
   in which small regions are visible at all.

Then rank the table twice, once by column 2 and once by column 3, and write both
lists out in prose with the region names the archive uses. Name the top four or
five of each. State the divergence explicitly: the regions that dominate the
total are large and slow, the regions losing the largest share of themselves are
small and fast, and a reader who has only the absolute column will draw the
wrong conclusion about which places are in trouble. That sentence is a result
and it costs one line of sorting.

## The denominators have to be built, so budget them at design

The archive hands you fluxes. Neither denominator is in it.

The share denominator is your own global total, which means the shares are only
as defensible as the aggregation that produced it - state the aggregation, and
state whether the regional rows sum to the global row or whether a basis
difference stands between them.

The intensity denominator is the region's stock at the start of the record, and
this is the one that gets skipped, because it is usually not in the archive at
all. An archive of change ships fluxes and areas, not stocks. Three places the
stock comes from, in order of cost: an area or volume column times a stated
conversion; the standard inventory the field maintains for this quantity; or the
source study's own headline table, transcribed row by row and attributed as an
external value the way `a-value-you-did-not-measure-still-has-a-source`
describes. All three are legitimate and all three are minutes of work; name the
constant or the source in the caption.

Obtain it at design time. Discovering at writing time that you never got the
denominator is discovering it one stage too late, and the column that would have
carried the entire intensity ranking is absent for want of one transcription.

Do not confuse the two normalisations. A share is a fraction of the aggregate
result; an intensity is a fraction of the region's own initial state. And the
interval on a share is not the interval on its numerator - propagate it or say
you did not.

## What goes inside each panel of the grid

A small-multiple grid over regions is where these numbers are read, because a
figure is read on its own far more often than the table beside it is.

- Annotate every panel with that region's own headline numbers - the absolute
  rate in each unit, and the fraction of its own initial stock - as text inside
  the axes. Three short lines in a corner. Someone reading only the picture
  should be able to quote a region's numbers without your table.
- Give the grid an **aggregate panel**, drawn in the same layout and visually
  distinguished, carrying the global numbers. A nineteen-region grid drawn on a
  four-by-five layout has a twentieth cell; if the legend is in it, you spent the
  total on furniture. Put the legend in a panel's empty corner and give the cell
  to the aggregate.
- Order the panels by a quantity, not alphabetically or by index, and say which
  quantity in the title. The ordering is free ranking information.
- The panel annotation is for the physical numbers. A residual against a
  reference version of your own series is not one of them; that belongs in the
  validation figure.

## Before you finish

Take your regional table and ask three questions of it. Can a reader name the
four regions that supply most of the total, with percentages? Can they name the
four losing the largest fraction of themselves, with percentages? Are those two
lists different, and does a sentence in the report say so? If the table has one
numeric column per unit and no per cent sign anywhere in it, the decomposition
has been tabulated and not interpreted.

## Why this is here

Two runs on the same regional-decomposition task drew the same nineteen-panel
grid from the same archive. One annotated every panel with three numbers - the
rate in Gt per year, the rate in metres water equivalent per year, and the
percentage of the region's year-2000 mass lost - put a global-total panel in the
twentieth cell in a different colour, and wrote two ranked lists into the
results prose. It scored 46.3 of 100 on the criterion asking which regions
contribute most in absolute and in relative terms. The other annotated every
panel with the maximum absolute residual between its rebuild and the published
release, put the legend in the twentieth cell, carried one of the brief's two
named units on the axis, and produced a per-region table built entirely out of
its own values set against the published ones - inside-or-outside verdicts and
signed residuals, no share column and no fraction-of-initial-stock column. The
share column was free: its own appendix already held every regional rate and the
global total. The intensity column needed one number per region that this
archive does not ship, and nothing anywhere in that run's workspace holds a
year-2000 mass. It scored 10.0.
