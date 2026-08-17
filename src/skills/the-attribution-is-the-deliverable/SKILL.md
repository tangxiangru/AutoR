---
name: the-attribution-is-the-deliverable
description: Use when the task statement names interpretability, explainability, feature importance, saliency or attribution among its outputs or objectives. The graded artifact is then the attribution map itself — per input unit, by the field's standard estimator, drawn as a figure — not a diagnostic about the model's internals and not an argument that the model is uninterpretable.
applies_when: interpretab|explainab|feature[-_ ]?importance|salien|\battribution\b|\bshap\b
stages: 02_hypothesis_generation, 03_study_design, 05_experimentation, 06_analysis
---

# If the brief asks what the model looked at, the answer is a map, not an opinion

A task that lists interpretability among its objectives is asking for an object:
a contribution per input unit — per feature, per atom, per bond, per region, per
token — aggregated into the domain's own groups and drawn. Everything else is a
substitute, and the substitutes are all cheaper than the thing.

Three substitutes show up reliably, and each one scores as an absence:

- **A different importance measure.** Gini or impurity importance, permutation
  importance, and attention weights are properties of the fitted model or of the
  training procedure. The brief asked which *inputs* drove which *predictions*.
- **A measurement on the model's parameters.** A spectrum of learned coefficients,
  a rank of learned filters, an ablation of architectural blocks: all
  interpretable, none of them an attribution.
- **An argument that the method is not interpretable.** This is the most expensive
  one, because it is often correct and it still delivers nothing. The finding that
  a method's explanations are unstable is a *result of running the attribution*,
  not a substitute for running it.

## Which estimator

Name the mapping explicitly at design time, in one line:

| the model | the estimator |
|---|---|
| fitted tree / gradient-boosted / tabular | SHAP (TreeSHAP), on the same rows the metrics use |
| neural network over graphs, images, sequences | input gradients ‖∂ŷ/∂x‖, occlusion or ablation, subgraph masking |
| anything, as a cross-check | leave-one-group-out retraining |

**Compute two and report their disagreement.** Rank correlation between a
gradient map and an occlusion map is a result you can publish even when the maps
turn out unstable — and it is what lets you say something instead of withdrawing
the arm when they do.

## No ground truth is the normal condition

There is usually no reference attribution to score against, and that is not a
reason to drop the arm. It is a reason to build the comparison you can:

- against the **source study's own published map**, where it has one, per unit
  with the source's indexing preserved;
- against a **trivial baseline** — a property of the input a domain expert would
  call irrelevant. If your map cannot beat "is this atom a hydrogen", say so;
  that is a finding;
- against **another estimator**, as above.

A map with a comparison is falsifiable. A map with none is still the deliverable.

## Aggregate into the domain's named groups, and print the table

The per-unit values are the computation; the group table is the result. Chemistry
groups by functional group (fluoro, amide, aromatic); behaviour groups by feature
family (distance, movement, shape); imaging groups by region. Print the group
means, and print the ranked top-N with the real entity names beside their values —
not indices, not `f_137`.

## Stratify by the factor the study ships, not by your own

If the design contrasts sites, cohorts, conditions or arms, compute the
attribution **separately within each** and put them on one axis so the difference
is readable. This is where the substitution is most tempting and most costly: a
run that stratifies by its own methodological axis — two evaluation protocols, two
preprocessing variants — has produced a comparison nobody asked for, and left the
one the design was built around empty.

Run the attribution on the object the source ran it on, too. The named molecule,
the named subject, the named sample.

## It has to be a figure

The map is graded as a picture. A CSV in `outputs/` does not discharge it, and
neither does a sentence reporting the top feature. Panel per stratum, group means
on the axis, values in the panel or the caption.

## Before you leave the analysis stage

Grep your own figure captions for the estimator's name. If the brief named
interpretability and no figure carries an attribution, the graded artifact does
not exist yet — go back to experimentation rather than forward to writing.

See also `the-unit-of-analysis` for choosing what a "unit" is before you aggregate,
and `run-the-conditions-the-source-ran` for keeping the strata the source used.
