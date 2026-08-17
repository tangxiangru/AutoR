---
name: chemistry-a-cut-variant-takes-its-analyses-with-it
description: Use at study design and again at every descope decision when the source's method is a family — the same module dropped into two or more backbones, or one architecture published in several named variants — and you are about to run only one of them. Covers listing which of the source's downstream analyses were produced from which variant before any of them is cut, shrinking a variant rather than deleting it, and what a saliency map, case study or ablation computed on the surviving variant is and is not evidence for.
applies_when: Kolmogorov.{0,3}Arnold Graph Neural Network|KA-GNN
stages: 03_study_design, 05_experimentation, 07_writing
---

# An analysis inherits the model it was run on

A method published as a family — the same new module dropped into a convolutional
backbone and an attention backbone, the same architecture in a base and a "+"
version — spreads its evidence across the variants. The benchmark table has a
column each. But the *other* results are attached to one variant apiece: the
worked case study was run on one of them, the saliency figure was drawn from one
of them, the efficiency panel timed one of them. Those are not properties of the
method in general. They are properties of a model, and only that model can produce
them.

`rebuild-the-sources-headline-table-row-for-row` covers the table: one column per
variant, no empty legend entries, a published value in any cell you could not
fill. This is the part that skill leaves out — everything downstream of the table
also has a variant attached, and the attachment is invisible until you cut.

## Make the attachment explicit before you cut anything

At literature stage, write the source's variants down the side and its results
across the top, and mark which variant produced each: table row, ablation, case
study, attribution map, runtime panel, failure analysis. It is a five-minute
table and it is the only artifact that makes a descope decision visible. Then read
the brief's objectives against it. When an objective is answered in the source by
an analysis attached to one variant, that variant has become load-bearing for
something other than a benchmark cell, and cutting it costs more than a column.

## Shrink the variant; deleting is the last option

Price it early and cheaply — build it, count parameters, time two epochs on the
smallest dataset — and then treat the price as the input to a *shrink*. Fewer
layers, fewer heads, narrower width, one dataset instead of five, a subsample of
the rows, a tenth of the epochs, one seed. Each of those is a stated shortfall on
a row that exists. A variant at a tenth of the source's budget, labelled with the
budget it got, answers its criteria partially and can be argued with; an absent
variant answers none of them, and the paragraph explaining its absence scores like
silence. `train-the-named-architecture` says cut seeds and substrates before you
cut the model; this is the same rule inside a method that is plural — cut the
*size* of a variant, not the variant.

Measuring that a variant costs thirteen times the other one is a cost measurement.
Keep it, report it in the cost section, and let it justify the shrink. It is not a
result about that variant, and it does not entitle the arms table to a row.

## If you must substitute, say which model you are showing

Sometimes the cut is unavoidable and the analysis still has to ship. Then run it on
the variant you trained and be explicit, in the caption and in the first sentence
of the section, that the map is of that model. Add one clause on what running it on
the named variant would have cost, so the reader can price the gap you are asking
them to accept. Both cost a line and both are missing from every run that gets this
wrong; without them the report answers a question about one model with a picture of
another, and the substitution is discoverable only by someone who reads the code.

The substitution is also a claim about the family, and it is worth testing rather
than assuming. If you have both variants at any scale, computing the same
attribution on both and reporting the rank correlation between them tells the
reader how far a result on one transfers to the other — a cheap measurement that
turns an apology into evidence.

## Why this is here

Measured on Chemistry_000 of ResearchClawBench, scored with gpt-5.1 over three
draws. The source publishes its module in two backbones, and the criterion about
interpretability names the attention one; the run under study scored 38.0 on it
against 55.0 for bare Claude Code on the identical brief, and 27.3 against 30.0 on
the benchmark-table criterion that names both backbones.

Its artifacts: no arm whose name contains `gat` exists anywhere under
`outputs/campaign/` or `outputs/results/`. The attention variant appears in the
run exactly once, as `outputs/notes/convergence_and_gat_probe.json` — 560,180
parameters, 3.332 s per training epoch — a profile taken and then used to justify
the cut. The saliency analysis that answers the interpretability criterion was
therefore computed from the convolutional variant, against a published map drawn
from the attention one, and the report says in its limitations that the attention
variant's entry in the legend of the main results figure is empty. That figure was
one of the five put in front of the judge.
