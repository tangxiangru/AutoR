---
name: astronomy-the-joint-posterior-is-the-parameter-result
description: Use at study design when the figure slate is fixed, and again at analysis and writing, when the deliverable is constraints or posterior distributions on parameters for two or more competing models. Covers why one overlaid triangle plot over the source's own parameter list is the exhibit that answers it, which parameters get an axis, and why a row of one-dimensional error bars reads as the figure never having been drawn.
applies_when: posterior distributions? of\s+\w+\s+parameters
stages: 03_study_design, 06_analysis, 07_writing
---

# One set of axes, every model, every parameter the source tabulates

When the claim under test is that two models absorb the same data by shifting the
parameters in *different directions*, the claim does not live in any marginal. It lives
in the joint distribution: which way each model moves in the expansion-rate–matter-density
plane, whether a shift runs along a degeneracy or across it, how far apart two models'
contours are in the plane where they are closest, whether they overlap at all. The
exhibit that carries that is one figure — the triangle plot, every model overlaid on one
set of axes, filled 68% and 95% contours below the diagonal, the one-dimensional
marginals on it — and it is the first thing a reader in this field looks for.
`the-canonical-figure` gives the general rule; this is the version with the decisions in
it.

**The parameter list is the source's, not your sampler's.** Take the axes from the
columns the source tabulates for every model, in the source's order and under the
source's symbols, then add each model's own extra parameters. Two consequences follow and
both get made backwards by default. A parameter your own likelihood never constrains
stays on the grid, carrying the published constraint alone — see
`astronomy-sample-the-published-table-into-chains` for where its samples come from — and
a parameter of your own parameterisation that the source does not tabulate stays off it,
because a reader has nothing to check it against. A grid whose axes are the intersection
of the source's table with your sampler's free parameters is a comparison of your
analysis to itself.

**Every model in the comparison is a contour with a legend entry**, including the one the
others are being compared to and including a model you only hold as published numbers.
Draw all of them once, in one figure; two separate corner plots side by side answer a
different question, because the whole content is where the contours sit relative to each
other.

**What does not substitute, in descending order of how convincing it looks:** a row of
one-dimensional error-bar panels, one parameter each; a table of means and intervals; a
scatter of best-fit points in one plane with no contours; a pair of separate corner
plots. Every one of these carries the marginals and throws away the correlations, which
is the part that was asked for. The error-bar row is the specific near-miss that gets
built when the triangle plot is not in the plan: it is quick, it is honest, it shows the
same numbers, and it reads to anyone laying it beside the source's figure as the figure
not existing.

**Fix the slot at design time.** Figure plans get frozen before results exist, and in a
run with a stamped plan the standard figure cannot be added later without editing a
digest. Put the joint-posterior slot in the plan before any hypothesis of yours claims
one, and bind it to the source's result rather than to a claim id.

**Then say in prose, immediately beside the panel, what it shows**, with numbers and in
the source's terms: which model sits higher in the expansion rate and by how much, which
in the clustering amplitude, which is lower in the matter density, and whether the two
remedies push in opposite senses. The contours are the evidence; the direction sentence
is the result, and it belongs in the paragraph that introduces the figure rather than
forty thousand characters later.

## Why this is here

Measured on Astronomy_001 of ResearchClawBench, rescored with gpt-5.1 over three draws.
The image criterion asking for the reproduced triangle plot carries 0.4 of the task. The
AutoR run scored **6.7 out of 100** on it against **11.7** for a bare agent — the judge's
words are that the report "does not include a triangle plot of 2D posteriors ... instead
it shows separate 1D error-bar panels", which is exactly what it shipped:
`fig2_parameter_constraints.png`, five one-dimensional error-bar panels over matter
density, expansion rate, clustering amplitude, physical matter density and spectral
index. Of those five, physical matter density is the run's own sampler parameter and is
not a row of the supplied table; the table's optical depth and log primordial amplitude,
both shipped with a 1-sigma error for all three models, get no panel. The run reported
the direction result correctly in prose and in that figure's sub-labels and still lost
the criterion.

Two skills that would have caught it were installed and one of them was read. The whole
run made three `Skill` calls: `citation-discipline` at Stage 01, then
`astronomy-figure-is-the-unit-of-result` and `the-canonical-figure` — whose text names
the corner plot as the expected exhibit for Bayesian parameter inference — at Stage 06,
the stage that *draws* the slate, after Stage 03 had fixed it and stamped it with a
digest. `draw-the-source-figure-panel-for-panel` was never opened. The general rule was
present, arrived at the wrong stage, and lost to a plan whose every slot was already
bound to one of the run's own preregistered hypotheses.
