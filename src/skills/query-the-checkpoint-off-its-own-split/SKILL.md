---
name: query-the-checkpoint-off-its-own-split
description: Use when a trained or fitted model checkpoint exists and every number you can currently report is an average over your own held-out split. Extends `chemistry-ranked-entities-and-property-curves` with what to do with the saved model itself: build configurations that appear in no split, push the grid past the edge of the training data, draw one curve per discrete condition with the separation between them stated as a number, and audit every supplied system the way you audited the first one.
stages: 03_study_design, 05_experimentation, 06_analysis
---

# A checkpoint is an instrument, not a score

This extends `chemistry-ranked-entities-and-property-curves`. That skill already says to sweep the
governing coordinate, overlay the reference, read the derived constants off the curve, and never let
a bar chart of error-by-variant stand in for it; `chemistry-canonical-units-thresholds-incumbent`
owns the unit the curve is plotted in and `material-landmark-scalars-in-physical-units` owns the
landmarks you read off it. Assume all of that. What follows is the part none of them says: what to do
with a saved model once you have one.

## The failure

Training finishes. The checkpoint is written, reloaded, and verified to reproduce its own energies to
the last digit — the provenance is airtight — and then it is asked exactly one question: what is the
error on the held-out slice of the frames it was trained on. Every table in the report is an average
over that slice. The model file is never opened again.

Hours of compute produce a number that a scatter of the training data could have produced. The tell
is mechanical: grep your results artifacts for a number that came from a configuration you
constructed rather than sampled. If there is none, the model was scored and never used.

Verifying that a checkpoint reloads is not querying it. A reload check confirms a file. It produces
no physics.

## 1. Build configurations that exist in no split

A random test split is a sample of the same distribution the training data came from, so it can only
tell you how well the fit interpolates its own sampling. The results people compare against are
statements about a coordinate: where the minimum sits, how the interaction decays, how far apart two
states are.

Construct the grid yourself. Freeze the internal geometry and translate one fragment; stretch one
bond symmetrically; scan the one degree of freedom the brief's data description says the
configurations vary in. Twenty to sixty points is enough. Evaluating a trained model on sixty
geometries is inference — minutes against the hours the training cost — and it is the only step here
that needs no new data.

## 2. Take the grid past the edge of the training data

Find the range of the coordinate that your training configurations actually cover, and extend the
scan beyond it on at least one side. Draw that edge as a vertical line on the figure and report the
error inside and outside it separately.

Nearly every claim worth making about this class of model is a claim about the far side of some
boundary — the sampled range, a cutoff, a receptive field, an interaction radius. A grid that stops
where the training data stops cannot express any of them, and a reader cannot tell from the figure
whether you tested extrapolation or avoided it.

## 3. One curve per discrete condition, on one pair of axes

When the study contrasts a discrete condition — charge state, phase, protonation, spin state,
solvent, isotope — the usual output is one aggregate error per condition, side by side. That reports
how well each was fitted. It does not report the thing the experiment exists to show, which is the
*difference between the conditions* as a function of the coordinate.

Put both curves on the same axes. Then state their separation as a number with a unit, at the
coordinate value where it means something: at the minimum, at the crossing, in the asymptote. If the
condition enters your model as an input rather than as a separate fit, this scan is the only evidence
that the input did anything at all — per-condition error tables are equally consistent with the model
ignoring it.

## 4. Substitute for one supplied system, audit all of them

Tasks that ship data usually ship several systems. It is common to discover that one shipped file is
a surrogate — wrong species, frames duplicated across conditions, no label for the quantity the
experiment is about, values in code units — and to mirror the source's deposited data for that one,
while the others stay on whatever arrived. The system left behind loses everything downstream of it,
and the loss is invisible because the rest of the study looks authentic.

Before training, write one line per supplied system: what the task says it is, what the file actually
contains (species, net charge, frame count, label units, duplicate frames), and which file the study
will use. Decide substitute-or-not the same way for every row, in one sitting.
`train-the-named-architecture` covers the other half of this — a degenerate file is audited and then
trained on, not skipped.

## Checklist

- [ ] Every checkpoint has been evaluated on at least one configuration set that appears in no split.
- [ ] Each scan crosses the edge of the training range, and that edge is marked on the figure.
- [ ] Each discrete condition has its own curve on shared axes, and their separation is stated as a
      number with a unit.
- [ ] Every supplied system has an audit line, and one decision rule covered all of them.
- [ ] No named experiment's only output is an aggregate over its own random split.
