---
name: information-exhibit-the-intermediate-objects
description: Use at analysis and writing when a multi-stage pipeline is about to be reported by its end-to-end metric alone. Covers exhibiting each stage's intermediate object, and re-running the source's own demonstrations on the source's own inputs rather than on yours.
---

# Show every stage's intermediate object and re-run the demos on the original's own inputs

In systems and modelling work the mechanism is the claim, so the intermediate objects are the evidence. For any multi-stage derivation, pipeline or multi-module framework, plan one exhibit per stage inside the report: the object that stage emits, in the source's own notation - the intermediate expression, the region proposals, the retrieved set, the routing assignment, the repaired candidate. A correct final number with the chain omitted is graded as an unshown derivation, not as a result.

Add the field's canonical diagnostics of the internal representation, not only outcome curves: a low-dimensional projection of the embeddings, a pairwise correlation or covariance heatmap, per-class feature-distribution overlap, and attention or saliency maps overlaid on the inputs - each shown before and after the intervention, on the same axes.

Reproduce qualitative demonstrations on the source's own showcase inputs and prompts, and quote the system's verbatim output: the transcript, the generated artifact, the before-to-after answer change. Your own prompt set may demonstrate the capability but does not reproduce the demonstration, and aggregate statistics never substitute for it.

Reproduce the claims in the original's framing first, then add disagreements additively - a demonstration that a claim is a protocol artifact must still carry that claim's evidence in the original's units and plot types beside it.

Everything that counts lives in the single report document: stage outputs, the derivation, and each figure's headline numbers in its caption. Work parked in a side document or a results directory, however good, is not part of the paper.

## Why this is here

Covers the three remaining Information mechanisms. The largest single measured loss was a 162 KB derivation with all intermediate steps written to a side file while the report never used the terms at all - three criteria scored 28/18/32 for work that was done. Three criteria demand representation diagnostics (embedding projections, correlation structure, attention maps, before/after distributions) that no report drew, and two demand the showcase demonstration verbatim, where substituting the agent's own prompts scored 0. The reproduce-then-critique ordering addresses the runs that pivoted to refuting the source and earned 5-25.
