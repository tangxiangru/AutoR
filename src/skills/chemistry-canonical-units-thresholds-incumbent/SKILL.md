---
name: chemistry-canonical-units-thresholds-incumbent
description: Use at study design and analysis when a chemistry result is about to be reported in the units your code happens to produce, or without the program the field already uses. Covers anchoring to the incumbent, converting to the canonical unit, and turning an error distribution into a threshold success rate.
---

# Anchor to the incumbent program, report in the canonical unit, convert error into a threshold success rate

A computational-chemistry number is only interpretable beside the program the field already runs, so budget baseline arms at design time: the established production code, the conventional architecture your method replaces, the explicit-parameter treatment your implicit one supersedes, and one deliberately cheap control (a geometric descriptor, an untrained network, a constant predictor) proving the added physics does work. Where the reference implementation is public and installable, install and run it on your systems instead of reimplementing it; a from-scratch reimplementation at a fraction of the original training budget cannot land on the published value, and only the same code path makes the comparison credible.

Report in the field's canonical unit with its canonical tolerance -- kcal/mol, meV/atom, eV/angstrom, angstrom, Debye, elementary charge -- and then convert error into a threshold success rate: fraction within chemical accuracy, fraction of poses under the accepted RMSD cut, fraction of systems inside the target band. A mean error alone hides the tail the field actually decides on.

Decompose every headline number along an axis the chemistry distinguishes and publish the decomposition, not just the pooled value: per dataset across the whole standard suite, per system or complex class, per charge and protonation state, per element, per interaction-distance regime, per functional group. Say how the rare, hard or imbalanced subset behaves. Repeat over seeds and splits with mean and standard deviation, and state the effective sample size when conformers, substitutions or targets cluster within families.

## Why this is here

Chemistry's absent rate is only 12%; the losses come from unanchored and unstratified numbers. It fixes the measured 'method reported alone' failure (4 of 4 tasks demand an accepted reference on the same inputs), the pooled-aggregate failure (4 of 4 tasks demand a chemical decomposition and a threshold-conditioned rate rather than a mean), and the reimplementation trap -- the single highest-scoring criterion in the discipline (56) came from installing and running the published software, and mirroring the authors' released data outscored shipped-data-only runs 25.8 vs 15.4/18.3.
