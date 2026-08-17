---
name: material-landmark-scalars-in-physical-units
description: Use at analysis when a materials result exists as a curve, a distribution or a trajectory and is about to be reported as one. Covers extracting the landmark scalar a reader compares — peak position, transition temperature, barrier height — in the property's physical unit, against a reference value.
stages: 03_study_design, 06_analysis, 07_writing
---

# Extract the landmark scalar, report it in the property's physical unit, and anchor it to a reference

Materials results are judged as physical quantities, not as fit quality. For every curve, spectrum, surface or trace you compute, extract the landmarks the field quotes and print them as numbers: peak position and height, onset or threshold, fitted slope, equilibrium lattice parameter, transition temperature, iterations-to-target, yield above a property cut. Report accuracy in the property's own unit first -- meV/atom, eV, K, angstrom, GPa -- and only then any dimensionless goodness-of-fit. An R-squared, a rank correlation or a distributional divergence reported in place of a physical error reads as though the physical error was never measured. State the literature accuracy band for that property in the same unit and say whether you are inside it.

Every landmark needs an independent anchor computed on the same inputs: an experimental value, a higher-fidelity calculation, a published range, or a deliberately naive control (mean predictor, random selection, chance enrichment). Annotate the value, its uncertainty, N and the anchor directly inside the figure panel, and restate it in the abstract.

Never report only the pool. Give the number per material, per composition, per target value, per iteration budget, plus the aggregate over the full prescribed set, and check that the ordering across operating points matches the physically expected one. Separate interpolation from extrapolation explicitly: state where the training data's composition and property range ends, and report the error outside that range as its own number.

## Why this is here

Addresses Material's two largest scoring mechanisms that are not absence: metric renaming (reporting R-squared/MMD where the field's quantity is an error in eV/atom or kelvin, which the judge reads as the demanded quantity being missing), and aggregate-instead-of-per-point reporting (three deep worked examples with no set-level statistic, a converged value with no iteration-indexed trace). It also forces the landmark out of prose into an annotated panel, which is where 10/13 image-typed Material criteria are read, and forces the separately-scored extrapolation/transfer number that 4 of 4 tasks demand.
