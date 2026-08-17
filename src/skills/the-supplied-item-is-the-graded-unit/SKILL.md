---
name: the-supplied-item-is-the-graded-unit
description: Use at study design whenever the task ships a specific named object in data/ — one paper, one structure, one instance — and again before writing. Covers reporting that item's own numbers under its own name, choosing the worked example by the task's pointer rather than by your result, and how to widen scope without dropping it.
stages: 03_study_design, 06_analysis, 07_writing
---

# The item the task ships is the unit the reader is checking

When a task hands you one named object, the questions asked of your work are
written about *that* object, often naming its identifier. Widening to the corpus
it came from is frequently better research. Concluding that it is a negative
control is frequently correct. Neither is a substitute for reporting the item's
own numbers under its own name.

## The failure this prevents

A run read the one paper shipped in `data/`, recovered the fifteen-paper
benchmark it belongs to, and priced the two scopes honestly: one paper gives a
±28-point interval, fifteen give ±8.5. It locked scope to fifteen and recorded
*"Scoping to the shipped paper. Priced and rejected above; it withdraws four
hypotheses."* Everything after that was excellent work, and the shipped paper
survives in the final report as one appendix table row and one reference — two
mentions, against eight in a plain agent's report.

The graded object was that paper's assembled Hamiltonian. The run generated it,
wrote it to `outputs/`, and never printed it. The one worked derivation the
report does show is a *different* paper — the one the run got right. Three
requirements scored 5, 15 and 5 against a plain agent's 32, 25 and 45, and that
agent's entire advantage was six lines printing the shipped paper's Hamiltonian
and naming the supplementary equation it matches.

The second shape: a structure task ships one pair, and every arm correctly finds
it is a monomeric negative rather than the paper's case. The arm that still
tabulated the pair's own sequence identity, alignment scores and runtimes scored
25/25/45/40. The arm that reframed it as a true negative and reported those
named quantities nowhere scored 0/15/25/5. Both were right about the biology.

## What to do

1. List every entry in `data/` by name at design time. Give each its own
   subsection in the report, with the identifier in the heading.
2. In that subsection report, **for that item alone**, every quantity the task's
   output list names, in the source's units. Widening is additive: the corpus
   arm is a new section, never a replacement, and the shipped item keeps its own
   values even when the corpus gives a tighter interval.
3. Print the object itself — the derived expression, the fitted parameters, the
   transform matrix — in the report. A path under `outputs/` does not discharge
   a deliverable.
4. **Choose the worked example by the task's pointer, not by your grade.**
   Showing the case you got right and burying the supplied case you got wrong is
   selecting the exhibit on the outcome. If the supplied case is the one that
   failed, that is the one to work through, and the failure is the finding.
5. If the item contradicts the paper, report the named quantity anyway, then say
   why it is what it is. "This pair is a monomeric negative" is a conclusion that
   needs the numbers under it, not instead of it.

## Before you finish

Search the report for each identifier in `data/`. A single-digit count, or hits
only in a reference list and an appendix row, means the graded unit is not in the
document.
