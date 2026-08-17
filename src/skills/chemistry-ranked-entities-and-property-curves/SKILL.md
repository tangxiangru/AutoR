---
name: chemistry-ranked-entities-and-property-curves
description: Use at analysis and figure planning when the computation ranks entities — molecules, poses, fragments, atoms — or sweeps a property along a coordinate. Covers printing the named ranked list and the property-versus-coordinate curve, the two artifacts most often computed here and least often reported.
---

# Print the named-entity ranked list and the property-versus-coordinate curve -- chemistry's two most-computed, least-reported artifacts

Two chemistry deliverables are routinely computed and never printed. Plan both into the report skeleton.

First, the ranked list. Whenever the method scores individual entities -- per-residue scans, per-atom or per-fragment attributions, per-pose scores, per-molecule rankings -- the deliverable is an explicit table of the leading entities by chemical identifier with their scores and units, plus the scan's bookkeeping: how many entities were scanned and the observed minimum and maximum. An aggregate ranking metric (AUC, precision@k, a correlation) does not substitute for the named list. If a per-entity file exists in your outputs, sorting its head into the report is the result. Then map those entities back onto chemistry -- which contacts, which functional groups, which charges or multipoles -- and state whether that is what a chemist would expect.

Second, the curve. Where a property depends on a governing physical or protocol coordinate -- bond length, intermolecular separation, cutoff radius, temperature, training-set size, number of sampling steps -- sweep it and plot the continuous curve with the reference overlaid, then read the derived constants off it and report their errors: equilibrium geometry, well depth, barrier height, asymptotic decay exponent, sum rules and conservation checks. A bar chart of RMSE by model variant answers a different question and does not replace it.

Make both artifacts self-supporting: metric value, N and the comparison annotated inside the panel, and the headline restated in the abstract in the field's units.

## Why this is here

These are the two documented computed-but-never-printed failures. One run's per-entity output file already held the exact ranked list and range the hidden criterion wanted; the report published a pooled AUC and precision@k instead and scored 18 and 0 across two runs -- one sort-and-head away from the answer. Separately, a right result delivered as a bar chart of RMSE by variant instead of the energy-versus-separation curve with the reference overlaid scored 45, 5, 5 across three runs. It also forces the interpretation-onto-named-chemical-entities demand that appears in 4 of 4 tasks.
