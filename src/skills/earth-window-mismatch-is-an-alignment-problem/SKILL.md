---
name: earth-window-mismatch-is-an-alignment-problem
description: Use at study design, and again when planning figures, whenever a comparator you hold - a model projection ensemble, a scenario run, a prior published assessment, a sibling record - is reported over a different period, baseline epoch, initial state or unit than your result, and you are deciding whether the comparison can be made at all. Covers re-baselining onto a common start date, plotting an ensemble that publishes only horizon endpoints, reading the crossing date, expressing prior assessments as revisions, and where a genuine refusal belongs.
stages: 03_study_design, 06_analysis, 07_writing
---

# Earth: a window mismatch is an alignment problem, not a reason to decline

A comparator that does not line up with your result - different period, different
baseline epoch, different initial state, different unit - is the normal case in
this field, and aligning it is part of the analysis rather than a precondition for
it. Every time you are about to write "no comparable estimate exists for our
window", check that you have not just described an offset.

## The failure this prevents

A run was handed several model-projection papers alongside its observational
archive. It read them properly: it converted their ensemble aggregates into its
own unit with the constant those papers cite, found that their published horizon
begins years after its own record starts and is stated relative to an initial
state at that later date, and quoted the sentence saying the models' pre-horizon
trajectories are mutually inconsistent. It then closed the whole comparison in a
design note - "no ensemble aggregate exists for the observed window even in
principle" - and substituted a scalar agreement test against a single historical
calibration target, on the argument that the models calibrate to it. Because the
clause was recorded as *declined with evidence*, no later stage reopened it. The
shipped report contains no projection curve, no pathway, and no horizon past the
last observed year.

The source study did the comparison anyway, and said how in one clause of a
caption: the projections were **offset at their own start date onto the observed
cumulative value** and drawn on the same axes as the observations. One line of
arithmetic against the obstacle the run had ruled fatal.

The mechanism is general. The run required *the same estimator over the same
window* before it would call two things comparable. Almost no external comparator
satisfies that. Alignment is what makes them comparable; refusing to align is
refusing the comparison, and a comparison refused in an internal note is
indistinguishable, in the report, from one nobody thought of.

## The alignment operations

Which comparators you owe - rival techniques, prior assessments, operational
baselines, projection ensembles - and the obligation to carry the analysis to the
comparator's horizon and state the ordering across pathways are in
`earth-comparator-set-lives-outside-the-supplied-archive`. This skill is only the
arithmetic that puts a mismatched one onto your axes.

1. **Work in cumulative or anomaly space.** Levels rarely align; changes almost
   always do. Re-express both series as change since a common reference epoch. If
   there is no overlap at all, offset the comparator at its own start date onto
   your value at that date, and say so in the caption in those words.
2. **Bridge units with the comparator's own constant** - the conversion it cites,
   not one you pick - and record the constant and where you read it.
3. **One set of axes, with x extended to the comparator's horizon.** Your line
   stops where your data stops; the comparator carries on past it. The part of the
   panel your data does not reach is the point of the figure.
4. **When the comparator publishes only endpoints, plot the endpoints.** Most
   ensembles report an aggregate at one or two horizons with an interval and no
   annual trajectory you can trace. That is a plotting problem, not grounds for
   falling back to a scalar agreement test. Anchor each pathway's aggregate at the
   comparator's own start year onto your cumulative, draw it as a marker or a
   wedge carrying its published interval, and label any segment you draw between
   anchor and horizon as a straight-line reading aid. Report the pathway values in
   the comparator's own normalisations - fraction of the initial state, the
   field's impact unit - as well as in yours.
5. **Read the crossing.** Invert the comparator at your last observed value: on
   what date does each pathway's central estimate reach the level you have already
   measured, and which pathways has the observation already overtaken? "The
   observed value has already reached the level projected for date D under pathway
   P" is a statement no agreement test produces, and it is usually the most
   quotable sentence in the study. Where the comparator is resolved per unit of
   analysis, give the same reading per unit and name the units on which
   observation and ensemble fall on opposite sides.
6. **Treat prior assessments as a lineage.** Order the successive published
   assessments of your quantity by date and report your value as a signed
   percentage revision to each. An interval test says whether you disagree; the
   percentage says how far the assessment moves, which is what a benchmark exists
   to do. Publish both and lead with the percentage. Where a comparator has an
   updated or re-calibrated version, plot both and say which way the revision
   moves.
7. **If a comparator genuinely cannot be aligned**, the refusal belongs in the
   report: one paragraph in Results naming the comparator, quoting the sentence
   that rules it out, and stating the alignment you attempted and why it fails. A
   decline recorded only in a design note reads as a comparison nobody attempted.

## Before you finish

At design, write one row per external series you hold - quantity, unit, window,
baseline epoch, and the transformation that puts it on your axes - and claim a
figure slot per comparator family before your own hypotheses claim the slots. At
the end, walk those rows: each is either aligned and plotted, or refused in the
report text. Any row whose only trace is an internal note is a comparison you did
not make. Then look at the x-axis of your main figure. If it ends at your last
observation in a study whose subject has a projected future, you have drawn the
record and not the comparison.
