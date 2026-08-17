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
afterwards.** A residual against the source's declared fiducial and a residual against
your own best fit produce panels that look alike and place the data differently against
the models: in one, the baseline curve carries structure and the points scatter about it;
in the other the baseline is identically zero by construction and every point is offset.
If the caption names a reference — a fiducial cosmology, a control condition, a baseline
run — that is the reference, and it does not change because Stage 05 found a better one.
Wanting your own baseline is legitimate: it is a second curve, or a second panel,
labelled, beside the one the caption specifies.

**Carry the colour key and the panel order unchanged.** A reader compares two figures by
superposition. Same model, same colour, same row: that is the whole mechanism, and
permuting the panels or reassigning the colours costs it entirely, at no benefit. The
model your residual is taken against keeps its name and its legend entry — demoting it to
an unlabelled grey dashed line at zero removes from the figure the very model the reader
was asked to judge.

**Take the units from the numbers.** A digitised block whose entries read `-0.020` is an
absolute difference; a block in magnitudes is in magnitudes. Rescaling an axis to per cent
because your own analysis is more comfortable there means the value the source's caption
and prose state cannot be read off your panel. And plot every measurement with its
uncertainty, in every panel: "the model lies within the errors" is the sentence these
panels exist to support, and points without error bars cannot support it.

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
`.autor/*/workspace/literature/target_paper_2503.24343_fulltext.txt`, which states the
panel order — distance modulus on top, isotropic distance scale in the middle, distance
ratio at the bottom — the colour key, that the supernova points have their weighted mean
set to zero, and that all three model curves are drawn "compared to the DESI 'fiducial'
model". The run's Stage 01 record even quotes that clause, writing that it relies on "the
figure caption naming the DESI fiducial as its reference". The figure it shipped is
titled "Distance residuals against the CMB+DESI ΛCDM best fit", carries the three panels
in the order isotropic distance scale, distance ratio, distance modulus, rescales two of
the three y-axes to per cent where the supplied block writes them as absolute differences
of order 0.02, draws its baseline as an unlabelled grey dashed line at zero, gives the
twenty-two supernova points no error bars, and stamps internal hypothesis codes across
its panel titles. The bare agent's figure labels the same axis "vs DESI fiducial",
carries the caption's panel order, and assigns the caption's own three colours to the
three models in its `code/figures.py`.
