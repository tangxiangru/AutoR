---
name: information-fill-the-whole-results-grid
description: Use when the research task is in information — machine learning, retrieval, multimodal and agent evaluation — at study design, analysis or writing. Reproduce the whole (variant x backbone x dataset x metric) grid, reduced-N where you must
---

# Reproduce the whole (variant x backbone x dataset x metric) grid, reduced-N where you must

The contribution of an AI/ML systems paper is a grid: method variants x backbones or base models x datasets x metric families, plus one ablation per named component and the qualitative demonstrations. Completeness of the grid is audited; nothing pays for extra depth in one cell. At design time, write the grid out as a table of empty cells and schedule the cheapest run that fills each one.

Widening is additive, not a substitution: the item the task actually ships keeps its own named
subsection with its own values, in the source's units, even when the full grid gives a tighter
interval. A run that priced the two scopes honestly, chose the fifteen-paper corpus, and left the
one shipped paper as an appendix row scored 5/15/5 where an agent that simply printed the shipped
paper's own result scored 32/25/45. See `the-supplied-item-is-the-graded-unit`.

Treat a single supplied example file as a smoke-test fixture for the *grid*, not as the evaluation
set and not as something the report may drop: obtain the released implementation, the pretrained weights, the full benchmark suite and the baseline systems from the public release. When a cell cannot be run at full scale, run it at reduced N or one seed and label it as such. A crude arm counts; a Limitations sentence declaring the arm out of scope reads as the experiment never having been attempted.

Ablate each named component one at a time and report its metric delta; report every algorithmic variant of the same component side by side; use the source's own names and abbreviations throughout.

Report the sub-field's full metric set per cell rather than one scalar: a threshold metric and a ranking metric for classification, a clustering-quality metric alongside accuracy for representation claims, the paired before/after for interventions. Then decompose each aggregate per class, per difficulty stratum and per regime (in-distribution, unseen, low-data), with mean and standard deviation over seeds, and include an off-the-shelf general-purpose model as a baseline with its latency and parameter count beside its accuracy.

## Why this is here

Information's failure is breadth: the two heaviest criteria of one task were the same experiment on two backbones and the agent ran one arm well and put the other in Limitations (46 and 0). It also fixes the 'half a metric pair' loss (F1 given, clustering metric omitted -> 12) and the 'scoped to the one supplied exemplar' loss, where every task ships one file against a full benchmark grid. Converting 'out of scope' into a labelled reduced-N arm turns structural zeros into partial credit, which is where the 43% absent rate lives.
