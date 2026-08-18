---
name: astronomy-the-caption-is-the-figure-specification
description: Use at literature survey the moment you have the source's full text, and again when the plotting code is written, whenever you are reproducing a figure whose rendering you cannot see. Covers mining each numbered caption for the panel order, the series and their colours, the reference model the residuals are taken against and how the data were normalised, and holding those fixed against a later stage that finds a better choice.
applies_when: baryon acoustic oscillation
stages: 01_literature_survey, 04_implementation, 06_analysis
---

# When you cannot see the figure, its caption is the build specification

The study you are reproducing is often not in your workspace: `related_work/` holds
neighbours, and the source itself reaches you as a fetched arXiv or publisher page. That
fetch usually loses the rendered panels and never loses the captions — and a caption in
this field is not a description, it is a specification. It names how many panels there
are and in what order, what quantity each one shows, which curves appear and in what
colours, which dataset supplies the points in each panel, what the curves are plotted
*relative to*, and what was done to the data before plotting. Every one of those clauses
is a line of plotting code that you will otherwise write differently, and every one of
them changes what a reader sees when your panel is laid beside the source's.

**At literature stage, copy each relevant caption verbatim into notes and split it into
build clauses.** One row per clause: panel index and position, y-quantity and its unit,
each series with its colour and line style, the reference model, the data normalisation,
the abscissa and its range, whether the points carry error bars. Do this for every
numbered figure the task or the supplied data points at — a supplied data block labelled
"extracted from Figure N" is a pointer to Figure N even when nothing else in the brief
mentions it. This complements `draw-the-source-figure-panel-for-panel`, which builds the
same row list off the *rendered* figure and warns that captions can disagree with it:
when the rendering is unobtainable the caption is what you have, and a caption-derived
specification beats a specification you invented.

**The reference model is the clause that goes wrong most often, and it is invisible
afterwards.** A residual against the reference the caption declares and a residual
against your own best fit make panels that look alike and are not the same figure. Take
the reference from one of the models you are comparing and that model stops being a
curve: it is the flat line at zero by construction, a reader cannot see where it sits
against the points, and a three-curve comparison quietly becomes a two-curve one. Take it
from the external reference the caption names and every model, yours included, stays a
drawn series that can be read against the data. If the caption names a reference — a
fiducial cosmology, a control condition, a baseline run — that is the reference, and it
does not change because a later stage found a better-fitting one. Wanting your own
baseline is legitimate: it is a second curve, or a second panel, labelled, beside the one
the caption specifies.

**Carry the colour key and the panel order unchanged.** A reader compares two figures by
superposition. Same model, same colour, same row: that is the whole mechanism, and
permuting the panels or reassigning the colours costs it entirely, at no benefit. The
model your residual is taken against keeps its name and its legend entry **in every panel
it appears in**: a reference drawn as a bare line at zero, named in the first panel and
anonymous in the rest, is an unexplained rule to a reader looking at the second.

**Decide what each supplied block is a difference _in_ before you choose its axis.** A
column of small numbers beside a curve is one of three things — a fraction of the
reference, a percentage of it, or a difference in the quantity's own unit — and the
block's own header usually says which, in the same words the caption uses. The magnitude
is the cross-check, because a fractional deviation and a per-cent one differ by a factor
of a hundred; get it backwards and your curves and your points land two orders apart,
which is obvious in the panel and invisible in the code. Whichever it is, a reader has to
be able to find the caption's own quoted values on your axis. And plot every measurement
with its uncertainty, in every panel: "the model lies within the errors" is the sentence
these panels exist to support, points drawn without error bars cannot support it, and a
caption that calls them *points with error bars* has already specified them.

**Before you save the figure, read the caption back clause by clause against the panel**,
and write your own caption in the source's words for the panels and quantities. Then
check the one thing the caption cannot tell you: that the series the source drew are all
present. A supplied series you disqualified stays on the axes, annotated.

## Why this is here

Measured on Astronomy_001 of ResearchClawBench, rescored with gpt-5.1 over three draws.
The image criterion for the three-panel distance-comparison figure carries 0.4 of the
task and is where the largest single loss sits: the AutoR run scored **32.3 out of 100**
against **48.0** for a bare agent, on a task it lost overall by 15.8 to 27.9.

The source's caption for that figure was on the run's own disk. It fetched the paper to
`.autor/*/workspace/literature/target_paper_2503.24343_fulltext.txt`, whose Figure 6
caption states the panel order — distance modulus on top, isotropic distance scale in the
middle, distance ratio at the bottom — the three model colours, that the supernova points
are "points with error bars" with their weighted mean set to zero, and that all three
curves are drawn "compared to the DESI 'fiducial' ΛCDM model". The run's Stage 01 record
quotes that last clause, writing that it relies on "the figure caption naming the DESI
fiducial as its reference".

The figure it shipped is titled "Distance residuals against the CMB+DESI ΛCDM best fit",
and substituting its own best fit for the caption's fiducial costs it the ΛCDM curve
outright: in each of the three panels ΛCDM is an `axhline(0, ...)`, so the model the
paper's argument is about is not a drawn series at all and only two of the caption's
three curves appear. It also permutes the panels to isotropic distance scale, distance
ratio, distance modulus; draws the twenty-two supernova points with `plot` rather than
`errorbar`, so they carry no uncertainties; moves the seven supplied digitised points off
the figure onto a separate validation panel; and writes its own hypothesis codes into one
panel title and two in-panel text boxes.

The bare agent's middle and bottom panels divide by the DESI fiducial — its
`model_comparison.py` builds them as `c.DV_over_rd(z) / dv_f - 1.0` against the cosmology
its own comment calls "the reference curve of Fig. 6" — so its ΛCDM stays a drawn purple
curve, about a per cent below the baseline at low redshift rather than being the
baseline. Its panels are in the caption's order and its colour dictionary gives ΛCDM, EDE
and w₀wₐ the purple, green and black the caption names. Its top panel does take residuals
against its own ΛCDM, so it did not get the reference clause right everywhere.

Two things were checked and are **not** what separated the arms, which is why neither is
in the craft above: both arms plot the same two panels in per cent, and both draw a grey
zero line. The reference model, the panel order, the missing error bars and the exiled
supplied points are the differences that remain.
