---
name: neuroscience-comparator-ladder-and-per-unit-predictions
description: Use when the research task is in neuroscience — neural recording, decoding and brain-model comparison — at study design, analysis or writing. Two-sided comparator ladder, the negative-control representation panel, and per-unit predictions
---

# Two-sided comparator ladder, the negative-control representation panel, and per-unit predictions

Three deliverables a computational-neuroscience claim must carry; plan them before fitting.

A two-sided comparator ladder. Horizontally, a bank of named alternative methods spanning the families in use (supervised, correlation based, variance based, single-modality). Vertically, variants of your own model that each delete one information source your thesis says is necessary - structure or connectivity, task optimisation, temporal order, one modality - plus a granularity sweep that coarsens the entity taxonomy (fine type, family, broad class) until performance collapses. Same metrics, same split, every rung.

The paired representation panel. Show the low-dimensional projection twice on identical axes and colouring: once under the untreated, shuffled or degraded condition and once under the treated one, quantified with the same gap metric in both. The deliberately poor control panel is a required deliverable, not something the good panel excuses.

Per-unit publication. Give the model's per-unit quantity for the whole population as a ranked table or figure, partitioned into units where an independent measurement exists (report agreement as k of n) and units where the model issues an untested prediction, labelled as novel predictions, with the coverage fraction stated. Pair it with a mechanism established by intervention - property P of upstream unit A sets property Q of downstream unit B, shown by silencing or re-weighting A - closing with a prediction an experimentalist could test.

Each must appear as a labelled figure with its numbers in the panel or caption. A quantity computed into a results file but never plotted counts as not done.

## Why this is here

Three tasks each demand the comparator ladder, the paired projection with its deliberately-bad control panel, and the intervention-based mechanism statement; three demand the per-unit table split into validated versus novel predictions with a stated coverage fraction. Bare runs ran textbook single-input ablations instead of the variant grid, never ran a taxonomy-coarsening sweep, and never drew the negative-condition panel. The closing rule targets the largest measured single loss in the discipline: per-feature attributions written to a diagnostics JSON, never plotted and never named in the report, taking 0.60 of one task's weight to zero.
