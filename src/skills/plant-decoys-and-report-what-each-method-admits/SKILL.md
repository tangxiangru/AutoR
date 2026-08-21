---
name: plant-decoys-and-report-what-each-method-admits
description: Use at study design and again at experimentation when a source claims robustness, resilience or degradation under worsening conditions, and the shipped data carries no knob to turn — or when the thing under test selects or ranks features rather than predicting a label. Extends run-the-conditions-the-source-ran: covers building a surrogate corruption axis, calibrating its worst level, and measuring what each method admits rather than only what it scores.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Plant decoys and report what each method admits

This extends `run-the-conditions-the-source-ran`, which says: enumerate the
stress axes the source names and run each one by name. Read that first. This
skill covers the two things it does not — what to build when the source's
stress generator is out of reach, and what to measure when the thing under
test selects or ranks features rather than predicting a label.

## The failure this prevents

A source's robustness claim gets answered with one statistic computed on the
matrix as it shipped: a count of selected features associated with a nuisance
column, a neighbourhood mixing purity, a variance ratio — each with a
permutation null, a size-matched threshold and a negative control. All of that
rigour describes **how much nuisance the supplied file happens to carry**. It
is one point on an axis. It cannot rank methods by resilience, it cannot be
plotted against anything, and a reader who asks "which of these survives a
worse experiment" gets nothing back.

The second shape is quieter. The run reads the source's stress protocol at
literature stage, records it accurately, finds that reproducing it needs a
generator or an accession it does not have, and never opens the row again. The
claim ends the run with no producer, no figure slot and no line in any budget —
not cut, just never scheduled.

## Order of preference

1. The source's axes, the source's generator, the source's levels.
2. The source's axes, your own generator, fewer levels. Say which is yours.
3. A surrogate axis you build, when the modality supports no version of the
   source's. Name the axis you could not build and what you varied instead.

A single-level statistic is never any of these. It is a description of the
fixture.

## Build the axis

* One function, `corrupt(X, family, level, seed)`. Level 0 returns the input
  bit-identical — assert it, in code.
* At least four levels including 0, and the far end severe.
* **Calibration rule:** at the worst level, at least one comparator must reach
  the chance floor. If everything is still near ceiling you have measured
  nothing and paid for it; extend the axis and rerun before writing a word.
* Everything except the input is frozen across levels: same splits, seeds,
  neighbourhood sizes, roots, metric code, hyperparameters.
* Repeat each cell over seeds and carry the spread onto the plot. A crossing
  between two curves inside the seed spread is not an ordering.

## Decoy families

Where the corruption is *planted features* rather than degraded ones, build at
least two families:

* **unstructured** — draws with no relationship to anything, and
* **structured** — a decoy shaped like what the method keys on: a smooth
  function of the embedding coordinates, a step keyed on a grouping column, a
  real feature with its association to the quantity of interest permuted away.

Unstructured decoys alone are too easy. Nearly every method rejects them, the
curves sit on top of each other, and the ordering you publish is an artifact of
having chosen the easy family. Structured decoys are what separate methods.

## What to measure for a selector or a ranker

The downstream metric is the second readout, not the first.

* **Admission.** At each level, the fraction of each method's output that is
  planted decoy, against the chance fraction (decoys / candidates) drawn as a
  line. A method whose downstream score holds while its output fills with
  planted decoys is failing in a way that score hides.
* **Stability.** Overlap between each method's selection at this level and its
  own selection at level 0.
* **Downstream cost.** The task's own metric, recomputed on each method's
  selection at each level.

Three curves, one story: what it lets in, whether it keeps its mind, what that
costs the analysis.

## Run the whole ladder at every level

Every comparator the source names, plus a random-selection arm as the
degenerate floor, at every level of every family. The result *is* the ordering
of the curves. If the budget will not carry the grid, cut levels and families —
never comparators. A curve with nothing beside it is a shape, not a finding.

## Report

* One figure per family: level on x, the metric on y, one line per named
  method, chance line drawn, seed spread shown, n in the panel.
* One table: per method, value at level 0, value at the worst level, the
  absolute drop, and the level at which it crosses chance ("never" is a
  result). Rank on the drop.
* One sentence in prose naming which comparators fall fastest and which is
  flattest, with their numbers. That sentence is the finding; the curves are
  its evidence.
* An axis you could not build still gets a subsection: what the source varied,
  what you varied instead, and why the substitution is fair.

## Checklist

- [ ] **study design** — the sweep is a row in the plan with a budget in
      `families x levels x methods x seeds`, before any of your own variants
      are costed.
- [ ] **study design** — state which of the source's axes the shipped modality
      cannot support, and the surrogate for each.
- [ ] **experimentation** — level-0 identity assertion passes; every cell is
      recorded, including the ones that collapse.
- [ ] **analysis** — confirm something broke at the worst level; if not,
      extend and rerun.
- [ ] **analysis** — admission, stability and downstream cost, each per method
      per level, each against its chance or level-0 reference.
- [ ] **analysis** — the sweep figure is a results figure, not an appendix
      figure.
