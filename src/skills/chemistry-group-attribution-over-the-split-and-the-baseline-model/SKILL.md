---
name: chemistry-group-attribution-over-the-split-and-the-baseline-model
description: Use at study design, experimentation and analysis when the deliverable includes which substructures, functional groups or motifs drive the model's predictions, once the attribution estimator is already chosen. Covers widening from the one molecule the source drew to the whole evaluation split with per-molecule normalisation, running the identical attribution on the comparator model so a claim of better interpretability becomes measurable, and treating a learned edge or subgraph mask as a first-class output.
stages: 03_study_design, 05_experimentation, 06_analysis
---

# A group ranking from one molecule has no n, and "more interpretable" is a comparison

This picks up after the estimator is chosen. `the-attribution-is-the-deliverable`
covers which estimator to use, computing two of them and reporting their
disagreement, the trivial-feature control, and the fact that the output has to be
a figure. None of that is repeated here. What that skill leaves open, and what
loses the interpretability criterion, is three things: the population, the
comparator model, and the mask.

The failure shape is always the same. The source drew a saliency map for one named
molecule; the run computes its own map for the same molecule, sums the per-atom
scores into the named functional groups, gets a different ranking from the
source's, and reports the disagreement. Both halves fail. A ranking of a few
groups derived from the atoms of a single molecule has no sample size, so a
disagreement cannot be distinguished from that molecule's noise. And the claim
under test is comparative -- the method highlights chemically meaningful
substructures *more than the conventional architecture does* -- which one model's
map cannot address at all.

## 1. The population is the evaluation split, not the drawn molecule

Write a SMARTS pattern for every group the analysis names and match it against
**every molecule in the held-out split** (`Chem.MolFromSmarts`,
`GetSubstructMatches`). Report one table:

- molecules containing the group (n) and matched atoms (m);
- mean attribution of matched atoms, **normalised within each molecule before
  averaging across molecules**. Raw scores are not comparable between molecules;
  per-molecule max-normalisation or a z-score is the difference between a
  statistic and an artefact of molecule size;
- the dispersion across molecules, so the ranking carries an interval;
- the same figures for atoms matched by no named pattern, as the contrast.

State the normalisation and the overlap rule -- an atom matched by two patterns is
assigned to both, or to neither -- in the caption. A source's group totals are
frequently not reconstructible from its per-atom column without them, and when
your ranking disagrees with the published one, the normalisation and the
population are the first two suspects, ahead of the model.

The molecule the source drew keeps its own panel and its own numbers. Widening to
the split is additive, never a replacement. If that molecule is in your training
split, say so and add one that is not.

## 2. The comparator model gets the identical attribution

Same estimator, same molecules, same normalisation, run on the conventional
architecture already sitting in your main results table. You trained it; the
attribution is a forward and a backward pass. Put the two group tables side by
side and report the per-group delta.

Without that column, a claim that the method is more interpretable than the
conventional one has no measurement anywhere in the report. With it, the answer is
a result in either direction: a map no more concentrated on the named groups than
the baseline's is a finding, and a stronger one than a ranking that merely fails
to match the source's.

## 3. The learned mask is an output, not a sentence

Where the method or the source produces a learned edge or subgraph mask, that mask
is a second deliverable and takes the same three treatments as the atom map:
aggregated over the split, computed on the comparator model, and drawn. A
correlation coefficient between your mask and a deposited one, reported in prose
and never plotted, discharges nothing.

- Extract the mask per molecule over the split; state the sparsity or size
  constraint and the optimisation budget.
- Describe the retained subgraph as chemistry: how many edges retained, which
  named groups the retained edges fall in, ring versus acyclic, by bond order.
- Report agreement two ways: against the source's mask where one is deposited,
  and against your own atom-level map. Whether two estimators of your own select
  the same substructures is the internal-consistency check, and it exists whether
  or not the source deposited anything.
- Draw the retained subgraph on the structure for the depicted molecules.
- Run the identical extraction on the comparator model.

Bond-level attributions get the same aggregation: by bond order, ring versus
acyclic, and by the groups at each end. A per-bond correlation with nothing
aggregated behind it is a diagnostic, not a result.

## 4. Depiction, and choosing what to depict

At least one panel shows the attribution painted on a rendered 2D structure
(`Draw.SimilarityMaps.GetSimilarityMapFromWeights`, or `MolToImage` with
`highlightAtomColors`), not only scatters and bar pairs.

Pick the depicted molecules by a **stated rule** -- the median-agreement molecule,
the best, the worst, the highest-scoring true positive -- and name the rule in the
caption. Choosing the exemplar by which one came out well is selecting the exhibit
on the outcome; naming the rule costs one clause and removes the objection.

## Order in the report

Set-level statistic first as the evidence, the source's named molecule second as
the illustration, in the figure layout and in the prose. State the group ranking
with its n and its spread, then show the molecule that exemplifies it.

## Checklist

- [ ] A SMARTS pattern is written for every group the analysis names, with its
      match count over the held-out split.
- [ ] Per-molecule normalisation applied before cross-molecule averaging, and
      named in the caption, along with the overlap rule.
- [ ] The group table carries n and a dispersion per group, not bare means.
- [ ] The identical attribution is computed on the comparator model and tabulated
      beside the proposed one, with a per-group delta.
- [ ] The learned mask, if the method has one, is aggregated over the split,
      computed on the comparator, and appears in a figure.
- [ ] At least one panel shows attribution on a rendered chemical structure.
- [ ] The rule used to pick the depicted molecules is stated.

Related: `the-attribution-is-the-deliverable` for estimator choice, two
estimators, the trivial-feature control and the figure requirement;
`chemistry-ranked-entities-and-property-curves` for the named-entity ranked list.
What is here and not there is the population, the comparator-model arm, and the
mask as an aggregated, compared, drawn output.
