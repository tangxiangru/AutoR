---
name: draw-the-system-not-your-study
description: Use at study design when allocating figure slots, and again at analysis and writing, on tasks where the source's own rendered figures are not available to copy. Covers the four slots reserved for the system before any hypothesis claims one, drawing the loaded arrays instead of their counts, why a panel that reports a shortfall is not the panel carrying the result, and why a deliverable marked covered_by an artifact path is not covered.
stages: 03_study_design, 06_analysis, 07_writing
---

# Draw the system, not your study

If the source's own figures are on disk, follow `draw-the-source-figure-panel-for-panel`
first and use this skill only for the slots it leaves unassigned. This one is the
index to use when they are not: the target paper is absent from the supplied
related work, the task is specified in prose, or the field has no standard figure
for this object. Then the system itself is the only index available, and a plan
built by walking your own hypothesis list will pass every coverage check it owns
while leaving a reader unable to see the thing that was studied.

## Three rules that decide this before the slot list does

**A count belongs in the caption; the array belongs in the panel.** If your
caption can state how many entities, edges, samples, atoms or pixels there are,
then you are holding an object with that many of something, and you can draw its
matrix, its distribution or its map. A bar whose height *is* a count carries only
the number you already wrote beside it. The usual form of this failure is a
"data overview" figure whose source is an inventory or a file-hash manifest --
a document about the data -- rather than the arrays the run loaded to do the work.

**A panel whose caption is a verdict on your own preregistration is not the
panel carrying the result.** If a slot's plan already contains an *if refuted*
branch, that slot has been spent on your study's bookkeeping. Put the per-entity
result in the panel and the shortfall in one sentence underneath. A reader who
cannot find the positive result reads the caveat as the whole finding.

**A ledger row whose `covered_by` is an artifact path is not covered.** A
coverage validator returning zero problems on `covered_by: outputs/*.csv` is
checking that a string is non-empty. Every named deliverable maps to a figure
panel *and* a sentence that states its numbers. Rewrite any row that points at a
path, a directory, or "prose" -- especially the rows carrying the most weight,
which are the ones most likely to name an object rather than a statistic.

## The slots to reserve before any hypothesis claims one

All four are drawn from arrays you must already have loaded to run at all.

1. **Structure at full entity resolution.** The interaction, adjacency or
   coupling matrix with every entity labelled and the sign kept; the repeating
   unit and how it is replicated across the domain; the composition or lattice;
   the boundary conditions. Not the counts -- the arrays.
2. **The degrees-of-freedom budget.** How many quantities the supplied data
   fixes, how many you fit, and the sharing, symmetry or tying rule that reduces
   one to the other. One panel, and usually the clearest single statement of
   what the study is.
3. **The governing equation, printed**, with every symbol marked as fixed by the
   data or free and fitted.
4. **One worked forward pass**: input, internal state, output, and the reference
   the output is compared against.

Then one slot per primary phenomenon, one row or one point per entity. Only
after all of that: ablations, nulls, readout-convention checks and your refuted
hypotheses. Between them they get at most a quarter of the budget and none of
the first slots.

## The audit

Open the plan. Read the justification field of every slot and count the ones
whose subject is the *system* rather than one of your own hypotheses, controls
or conventions. If that count is zero, the plan is wrong and no amount of
execution will fix it -- rewrite the plan before running anything. Repeat the
count before writing, on the figures that actually exist.

Two failure signatures to look for in your own plan: every slot's justification
is a claim id, and the object under study appears nowhere except as counts in a
sentence.

## Write the structure script at implementation

Write it as soon as the loader works, before any experiment runs. It is the
cheapest correctness check you have: drawing the interaction matrix at full
resolution exposes a transposed index, a dropped sign convention, a duplicated
block or an entity list in the wrong order -- failures every downstream number
inherits silently. Diff its totals against the figures quoted in the supplied
documentation.

## Checklist

- [ ] Count of plan slots whose subject is the system, not a hypothesis: greater than zero, and they come first.
- [ ] Structure panel drawn from the loaded arrays, full entity resolution, entities labelled, signs kept.
- [ ] Free-versus-fixed degrees of freedom shown as a budget, with the sharing rule named.
- [ ] Governing equation printed, every symbol marked fixed or fitted.
- [ ] One worked forward pass: input, internal state, output, reference.
- [ ] No named deliverable discharged to an artifact path or to prose; each has a panel and a sentence.
- [ ] Nulls, conventions and refuted hypotheses occupy at most a quarter of the slots and none of the first.
- [ ] No panel title or caption is a verdict on your own preregistration.
- [ ] Structure script written at implementation and its totals diffed against the supplied documentation.
