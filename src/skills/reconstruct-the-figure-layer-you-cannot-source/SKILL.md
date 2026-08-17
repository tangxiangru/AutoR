---
name: reconstruct-the-figure-layer-you-cannot-source
description: Use at study design and implementation when a figure you are reproducing carries a component whose exact inputs are not in the supplied data - points drawn over an aggregate, per-unit traces, a second method's series, a band, an inset. Covers enumerating a published figure's layers when you cannot see the rendering, deciding between omitting a layer and building a labelled reconstruction from the coarser quantity you already hold, and the three conditions that make a reconstruction evidence rather than decoration.
stages: 03_study_design, 04_implementation, 06_analysis
---

# A layer renders a quantity. Ask which quantity, not which dataset.

A figure you are reproducing is built from layers: a filled area or a bar, marks
drawn over it, a fitted line, an uncertainty band, an inset, a second method's
series. Each layer needs inputs. When one layer's exact inputs are not in the
supplied data, the cheap move is to drop that layer and write a sentence saying
why. That sentence costs you the requirement the layer belongs to, and it is
usually avoidable — because a layer is not the data the original authors held.
It is a *rendering of a quantity*, and the quantity is often already on your
disk at a coarser resolution.

This is the layer-level complement to `draw-the-source-figure-panel-for-panel`.
That skill decides which result owns a panel; this one decides what goes inside
a panel you have already committed to drawing.

## The failure this prevents

A run reproducing a published figure whose aggregate marks each carry one dot
per contributing record found that the record-level positions had come from an
input channel the release does not contain. It recorded "not reproducible" in
its design ledger, repeated it in its implementation ledger, painted it into the
figure's axes as a block of text, and repeated it in the caption. It shipped the
aggregate without the dots and was graded well below par on that requirement —
below a plainer comparator that shipped exactly the same single layer and never
mentioned the missing one.

Neither run held the record-level inputs. But the dots encode only that a larger
aggregate is made of more records, and the per-category counts were sitting in
the losing run's own results file, the same file the aggregate heights were read
from. Placing n dots inside a category is not a guess about which record is
which; it is the standard rendering of a count, and dots of that kind carried no
per-record information in the source either.

## Enumerate the layers before you decide anything

Work from the rendered figure when you can get it: fetch the source from its
DOI, its repository or a preprint mirror and look at the panel. When you cannot
— the workspace ships no rendering and the fetch fails — the source's own
caption and the sentence that introduces the figure are the enumeration. **Every
visual noun they name is a layer you owe**: the fill, the markers, the trend
line, the band, the inset, the secondary axis. A caption naming three visual
elements against a panel of yours drawing two is a missing layer, whether or not
you ever saw the picture.

Do not take the authors' released plotting script as the enumeration. It emits
what that script emits; see `verify-against-the-publication-not-the-authors-code`.

## Ask what the layer encodes

For each layer whose inputs you lack, write two things down: the finest claim
that layer can support in the source, and the coarsest quantity you already hold
that carries that claim.

| layer | inputs the source had | what it encodes | what you probably hold |
| --- | --- | --- | --- |
| one mark per record over an aggregate | per-record positions | how many records the aggregate is made of | the count itself |
| per-subject traces behind a group mean | subject-level series | spread within the group | the group mean and an observed dispersion |
| per-unit points along a curve | per-unit measurements | where units sit on the axis | each unit's bin |
| a comparison method's series | that method's outputs | ordering and offset against yours | the published values, transcribed |
| an uncertainty band | the full sampling distribution | how wide the estimate is | an interval you can compute |

If the two right-hand columns name the same quantity, the layer is
reconstructable and you build it. The input you lack was never the input the
layer's message rested on.

## Three conditions that make a reconstruction evidence

1. **Deterministic and sourced.** Positions or values are a function of a
   quantity you measured plus a seed fixed in the code, and the drawing script
   reads the same results artifact the rest of the figure reads. Never sample
   from a distribution the run did not measure.
2. **Named as a construction, in one clause, in the caption.** "One dot per two
   records, placed at random within each category; dot positions carry no
   within-category information." That is a caption clause. It is not a block of
   text inside the axes — see `disclose-by-construction-not-by-absence`.
3. **Unable to support a finer claim than its input.** Nothing is measured on
   the reconstructed layer, no individual mark is annotated, and no sentence in
   Results reads a pattern off it. Write that sentence down explicitly. If you
   cannot write it, the layer is not reconstructable.

## When to refuse, and how

If the layer's whole content is the information you lack — a measured field at a
resolution you do not have, an arm nobody ran — omit it. Then it costs one
sentence where the result would have gone: not a heading, not text inside the
axes, not a clause in the abstract, not a second pass in the caption. Price the
refusal at design time and record the single input that would have changed it.

## Checklist, at study design

- For every figure you intend to lay beside a published one, list its layers,
  one row each, with the input each needs and whether you hold it.
- For every row you do not hold, fill in the encoded-quantity table above.
- Mark each such row `reconstruct` or `refuse`, with its reason, in the plan. A
  row left unmarked becomes a refusal by default, which is how most refusals
  happen.
- `reconstruct` rows are built by the same script that draws the layer they sit
  under, and pass all three conditions.
- Before writing, count your panel's layers against the enumeration you built
  above — from the rendering if you have it, from the caption's visual nouns if
  you do not. A difference that is not on the refuse list is a defect, not a
  choice.
