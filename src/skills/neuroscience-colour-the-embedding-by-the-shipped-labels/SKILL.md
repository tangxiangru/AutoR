---
name: neuroscience-colour-the-embedding-by-the-shipped-labels
description: Use at study design when a figure specification fixes what a low-dimensional embedding is coloured by, and again at analysis and writing when that projection is drawn. Covers the metadata-label inventory that decides the panel grid, the unreduced and size-matched-random arms that belong in the same figure, and rendering each panel's scores into its axes.
stages: 03_study_design, 06_analysis, 07_writing
---

# Colour the embedding by the labels the file ships

## The failure this prevents

A run produces one low-dimensional embedding figure and colours it by whichever
covariate the surrounding narrative is built on — an inferred continuous
ordering, an age, an acquisition index — because that is the variable the
section happens to be about. The discrete state label the file actually ships
never becomes a colour.

The figure then looks like a result and shows nothing. A continuous gradient
along an arc tells a reader the embedding has a direction. It cannot tell them
whether the representation **separates the states**, which is the question the
biology is about and the only thing an embedding of a selected feature set is
evidence for. Two panels that both show a gradient are indistinguishable; a
panel with clean state blocks beside a panel that is a smear is a result you
can see in one glance.

Two companion failures travel with it. The scores that would settle the
question are computed elsewhere in the run and land in an appendix, framed as
agreement with a published value rather than as this figure's claim — and a
figure is routinely read on the picture alone, without text that sits tens of
kilobytes away. And the colouring was frozen into a figure specification at
design time, before any data was seen, after which plan fidelity kept it.

## 1. The label inventory

This is the part of this skill that nothing else in the library carries. Do it
before you draw anything.

Enumerate every metadata column the file ships. For each: dtype, number of
distinct levels, count per level, fraction missing. Print the table into the
log and keep it as an artifact.

Any column with roughly 2–15 levels and a usable majority non-missing is a
**colouring**, and you owe the reader a panel in it. Decide from this table,
not from the section you are currently writing. The column you had no plans for
is often the one the source's own figure is coloured by — the people who built
the file put it there for a reason, and a column you enumerated once and never
plotted is the cheapest requirement in the task to lose.

Continuous columns are colourings too, and they are *additional* rows — never a
substitute for the categorical ones. If the file's level set disagrees with the
source's prose, draw the file's levels and say so where the figure is
introduced.

## 2. A grid, not a panel

The minimum grid is `{selected set, full unreduced set, size-matched random
set} x the primary categorical label`, drawn as **one figure** with shared
axes, shared embedding hyperparameters and one shared legend.

The unreduced arm is what makes "the selected features preserve the structure"
a comparison rather than an assertion. The random arm at the same size is what
separates reduction from selection. If you are comparing several methods, each
gets a small panel in the same grid — never one large figure per method, which
makes the comparison a memory exercise. Add a row per further categorical
label from the inventory.

This is the paired-panel rule of
`neuroscience-comparator-ladder-and-per-unit-predictions` widened to the whole
comparator set: the deliberately poor panel is a required deliverable, not
something the good panel excuses.

## 3. Numbers rendered into the axes

Compute each panel's scores in the same script that builds the embedding, write
them to a JSON beside the image, and render them **from that JSON into the
axes**, so the picture and the file cannot disagree and the numbers cannot be
separated from the panel they describe. A caption is text; it travels
separately, and sometimes it does not travel.

Per panel, at minimum: agreement between this embedding's clustering and the
panel's label, a supervised accuracy for that label under one fixed simple
classifier, rank correlation against any continuous ground truth the file
carries, and `n`.

`draw-the-source-figure-panel-for-panel` covers the rest — printing the
source's named constants as labelled values, and stating each panel's key
numbers in the prose that introduces it, in the results section, early. Follow
it; do not defer those numbers to an appendix because they already exist there
under another framing.

## 4. Re-open a frozen figure specification

A colour, a panel count or a covariate chosen before the data was seen is a
guess. Before the figures are final, re-read every frozen figure spec against
the inventory. Plan fidelity protects a plan from drift; it does not protect a
guess from evidence.

If a spec's colouring is not in the inventory's categorical list, change the
spec and record the change and its reason. Adding the panel is cheaper than
defending its absence. A figure slot that supports no hypothesis is the one
most likely to be wrong and the least likely to be checked — quality rules
scoped to "figures that support a verdict" never reach it.

## Checklist

- [ ] **study design** — figure specs name a categorical colouring, not only a
      continuous one, and are marked revisable once the inventory exists.
- [ ] **analysis** — the label inventory is printed and kept; the panel grid is
      derived from it.
- [ ] **analysis** — the grid holds the unreduced set and a size-matched random
      set on shared axes, shared hyperparameters, one legend, one figure.
- [ ] **analysis** — every categorical column in the inventory has a colouring
      somewhere; continuous colourings are extra, not substitutes.
- [ ] **analysis** — per-panel scores computed in the same script, written to
      JSON, rendered into the axes.
- [ ] **writing** — the paragraph that introduces the figure states the
      selected / unreduced / random numbers, in that order, per metric.
- [ ] **writing** — no frozen spec survives that the inventory contradicts.
