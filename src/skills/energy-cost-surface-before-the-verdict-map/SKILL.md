---
name: energy-cost-surface-before-the-verdict-map
description: Use at figure planning and analysis whenever the deliverable is a spatially resolved cost, yield or performance model. Extends `the-canonical-figure` and the two energy skills on panels and per-layer effects with four things they do not cover: draw the modelled quantity before any pass/fail overlay, put the driver fields at the same extent beside it, count result panels against validity panels, and re-price a null you created by your own configuration choice.
stages: 03_study_design, 06_analysis, 07_writing
---

# Map the quantity, then its drivers, then the verdict — in that order

A spatially resolved cost or performance model has one primary exhibit: the
modelled quantity, over the whole domain, at the model's own cell. Everything
else — validation, sensitivity, decomposition, threshold counts — is an argument
about that exhibit and none of it substitutes for it.

**"The whole domain" means the domain the question names**, established by
`energy-build-the-domain-the-question-names`, not the extent of the supplied
sample. Read that first: a well-made map of the wrong area passes every check
below and still answers nothing.

This skill assumes three rules you already have and does not repeat them:
`the-canonical-figure` (a spatial field is expected as a map, and your own
figure does not replace the standard one),
`energy-canonical-configuration-before-the-enhanced-variant` (one plain panel
per headline claim, at the native spatial unit), and
`energy-counterfactual-pair-and-hierarchy-closure` (one quantified effect for
every supplied input layer, including the ones that turn out to be null). What
is added here is ordering, driver panels, slot accounting, and what to do with a
null you created yourself.

## The three substitutions that go wrong

**The verdict replaces the quantity.** The run computes the quantity per cell,
then draws which cells beat a benchmark. The reader gets a classification and
never sees the surface it was cut from. One run's only map of its headline
quantity was a small multi-panel of discrete markers, titled with a negative
finding, with the eye pulled to rings marking the handful of points that passed
a threshold. Its figure plan even had a slot named for the deliverable — the
slot was spent on the verdict. A reader who saw the whole set described it as
diagnostic plots.

**The diagnostics outnumber the result.** A figure set is read as a set. If most
of it argues about whether the run is valid — validation against published
values, tornado, lever decomposition, input-vs-measured comparisons, threshold
sweeps — the study reads as self-audit, whatever the text says.

**Points where the model has cells.** A scatter of site markers over a basemap
does not read as a field. Tessellate, bin or interpolate to the model's native
cell so a pattern is visible as a pattern.

## What to produce, at figure planning and analysis

1. **The quantity field.** One panel per scenario, whole domain, native cell,
   colour scale in the headline unit and labelled with it, shared across panels
   wherever levels are comparable. No pass/fail overlay on this panel. Excluded
   areas hatched and named in the legend, not deleted.
2. **The driver fields, same extent, same cell.** Every spatially varying input
   the model consumes gets a panel: each resource or supply technology
   separately, and each supplied distance or accessibility layer. This is what
   lets a reader lay the outcome over the cause. Without it, "resource quality
   drives cost here, infrastructure there" is an assertion.
3. **A priced effect for every supplied layer**, in the headline unit, computed
   by re-running the chain across the range that layer actually takes in the
   data with everything else held. That rule is
   `energy-counterfactual-pair-and-hierarchy-closure`'s; the addition is what to
   do when the effect comes out as an exact zero.
4. **A structural null you created is a design finding, not a fact about the
   world.** If a supplied layer prices at exactly zero because of a
   configuration you chose — a self-contained plant that connects to no network,
   an assumed connection where one is missing, an input met by a substitute —
   the sentence to write is not "this layer does not matter" but "this layer is
   inert *under the configuration we modelled*". Then run the configuration in
   which it binds and report both arms. That variant is a run, not a sentence,
   so plan it at design; discovered at analysis with the compute budget closed,
   it becomes one more caveat. A covariate you were handed and never priced at a
   non-zero value in any arm reads as an input you discarded.
5. **The verdict map, separately.** Threshold classification gets its own panel,
   the threshold value in the title, and a second panel over the plausible range
   of the threshold, because the class boundary usually sits on an assumption
   rather than on the terrain.
6. **Zoom panels at native resolution** for every region the deliverable names
   and for every region your sample concentrates in. Domain-wide panels hide
   sub-regional structure and readers of this field look for it first.

## Say what the pattern is, with numbers

"The quantity varies widely across the domain" is a caption, not a result. In
the panel and in the sentence under it:

- name the low-value areas with place names a reader can find on a map, never
  cell ids or row ids;
- print the minimum, the domain median, and the leader's margin below it;
- give the share of cells or area inside the leading decile, and state whether
  those cells sit together or lie scattered, with the statistic behind whichever
  you say — a claim about spatial structure needs a number, not an adjective;
- attribute each low-value area to a driver by pointing at the driver panel:
  which input field is extreme there, and what its priced effect is.

Title every panel with the finding it carries, stated positively and naming the
place. A title that states what is *not* true spends the panel's only sentence
on a negative, and negatives are what a reader remembers from a figure set.

## Before you finish

- Count the slots. How many show the modelled quantity or its drivers over the
  domain, and how many argue about the run's validity? If the second number is
  larger, move slots.
- Walk the data manifest column by column. For each spatial column: which panel
  shows it, and which number in the headline unit is attached to it?
- Could a reader who sees only your figures say where the quantity is low and
  why? If not, the map is not finished.
