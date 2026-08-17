---
name: neuroscience-simulate-the-topologies-you-were-not-given
description: Use at study design when the claim is about recovering or preserving a continuous progression and you have been handed exactly one dataset. Covers why one file is one trajectory shape, how to generate the linear, bifurcating and tree cases you were not given, and what a synthetic ground truth buys that no real dataset can.
applies_when: neurodegeneration-related state transitions
stages: 03_study_design, 05_experimentation
---

# One dataset is one topology, and the claim is about a family of them

A method that recovers or preserves a continuous progression does not have one performance; it has one per shape of progression. A single unbranched clock, a fate decision with two arms, a lineage tree with several leaves and a cycle are four different problems, and a ranking of methods obtained on one of them does not transfer to the others — which is exactly why the literature reports these cases separately. The file you were given instantiates one of these shapes. Say which one, in the data section, in those words, and then treat the missing shapes as missing experiments rather than as scope you never had.

You generate the rest. Simulators for this exist and are cheap next to the analysis they feed; where none fits, a hand-built generator is a few dozen lines — draw a latent progression variable, place a small block of features that respond to it monotonically or in branch-specific ways, add uninformative features with matched marginals, then emit the counts or intensities with the noise model the assay has. Build one dataset per topology — at minimum linear, bifurcating and tree, plus the cyclic case if your real data is a cycle — and hold the cell count, feature count and informative-feature fraction fixed across them so that the only thing that changes is the shape. Vary the seed and generate several instances per topology, so a per-topology number has a spread rather than being one draw.

Run the *same* comparator ladder and the *same* metrics on every one, and report per topology, as rows or panels, never pooled. The pooled mean hides the case that matters: a method can lead on the linear case and be last on the bifurcating one, and if that happens it is the most interesting sentence in the section.

The reason to do this even when the real dataset is excellent is that simulation is the only place the ground truth for the *feature* question exists. On real data you know the cell labels but not which features are genuinely dynamic, so any precision-style metric has to be scored against a proxy reference — a supervised model's importances, a curated marker list — and a proxy reference makes the metric an agreement statistic rather than an accuracy. In a simulation you planted the informative features, so precision and recall over the selected set are exact, and the same run also gives you the true ordering to correlate a recovered pseudotime against. Say plainly which of your metrics are exact under simulation and which are proxy-scored on the real file.

Where the source study ran its own simulations, use its generator, its parameters and its topology names before adding one of your own; see `run-the-conditions-the-source-ran`.

## Why this is here

On this task the criterion asking for benchmark performance across linear, bifurcating and tree-structured trajectories scored 37.0, and the reviewer's stated reason was that the report "does not cover the full range of simulated datasets or distinct topology classes as in the original paper". The run knew about them: its literature survey names the source's two simulation studies and their generators explicitly, and each generator's name occurs exactly once across all sixteen of the run's stage files and zero times in its report — an inventory built to argue a novelty gap and then never read as an experiment list. The string "simulat" occurs zero times in both arms' reports; the comparator, which also ran only the shipped file, scored 47.7 on the same criterion at a weight of 0.25, so neither arm collected what this section is for.
