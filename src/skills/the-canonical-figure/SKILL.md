---
name: the-canonical-figure
description: Use when planning figures, at study design and again before writing. Covers the figures a paper in this field is expected to contain, why an original figure does not substitute for a standard one, and how to decide what to draw first.
---

# Draw the field's standard figure before your own

Every field has one or two figures a paper of that kind is expected to contain.
A reader looks for them first, and their absence is read as the analysis not
having been done — even when the same information is present somewhere else, in
a table, in prose, or inside a figure you designed yourself.

Some examples of the shape, not a checklist:

- Bayesian parameter inference is expected to show the joint posterior — a corner
  or triangle plot over the parameters — not only marginal summaries or a table
  of medians and intervals.
- An iterative optimiser is expected to show objective against iteration, log
  scale, your method and the baseline on the same axes.
- Anything trained is expected to show the learning curves: training and
  validation loss against epoch, on the same panel, so overfitting is visible.
- A spatial field is expected to be shown as a map, per epoch or lead time,
  beside the reference field — not summarised into one error number.
- A classifier is expected to show the curve its threshold moves along, not one
  operating point.

## Why your own figure does not substitute

You will usually find something more interesting than the standard plot, and it
is right to show it. But an original figure answers a question the reader did
not ask yet. The standard one answers "did the thing work, in the way this field
checks that". Publish both, standard first.

## How to decide

At design time, before any results exist, ask: what figures does a paper making
this kind of claim always contain? Put those in the plan as the first slots.
Then add the figures your specific angle needs.

If you cannot produce a standard figure — the run does not have that quantity —
say so where it would have gone, in one sentence, rather than leaving the reader
to notice the absence.
