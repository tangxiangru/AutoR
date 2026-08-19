---
name: one-visible-line-per-quantity-the-answer-owes
description: Use at hypothesis generation when a part of the sheet is discharged by a count, a balance or a set of competing contributions, and the totals are about to stand in for the terms that produced them. Covers the per-part ledger with one visible row per quantity, why two opposing effects must never share a row that says they cancel, where the verdict sentence goes, and carrying the constraint into the writing rather than leaving it to chance.
applies_when: intermediate derivations
stages: 02_hypothesis_generation
---

# A total is not the terms, and only the terms can be checked

When a part is discharged by counting things — carriers, charges, equivalents,
contributions, competing effects — the terms are the answer and the total is a
summary of it. An answer that reports the total, however correct, has withheld
the thing that was asked for. A reader looking for a particular count in a
particular part cannot recover it from a number that folded it in with three
others, and does not try.

**Decide this at framing time and carry it as a written constraint**, not as a
style you hope you will remember. It has to survive into the finished answer,
so state it once, explicitly, as a rule the answer follows: each contributing
quantity is displayed on its own visible line rather than folded into a total.

## The per-part ledger

For every part discharged by counting or balancing, build a small table for
**that part**, not one table for the whole sheet:

- one row per contributing quantity, named the way the sheet names it;
- its value with its sign and its unit;
- a bolded total row underneath.

Repeat the table for each part even when the rows barely change between parts.
The near-duplication is the point: a part is answered where it is asked, and a
reader comparing part three with part two needs both tables, not one table and
a sentence saying what changed.

Give the same treatment to a balance you carried out but that your final choice
does not use. A set you computed and then set aside goes into a labelled
section with its numbers intact — suppressed working scores as working never
done.

## Never merge two opposing effects into one row

The costliest single row in this trial read as one line covering two competing
requirements and concluded that they cancel. The physical reasoning was
defensible; what was asked for was the weighing of the two, and the merged row
deleted it.

So: when two effects push opposite ways, they get **two rows**, each with its
own magnitude and its own sign, and then a sentence saying which dominates and
why. Simplify after you have displayed, never before. The same holds for a chain
of steps: the step that gets its own row is the step that can be marked.

## The verdict goes first inside its own part

Each part gets a heading, and under it, before the qualifications, one
unhedged sentence that answers it. Then the conditions, the failure modes, the
margins. A part whose closing sentence walks the verdict back has answered the
opposite of what it meant to: a reader takes the last sentence in the section as
the position.

Qualify **forward** — "no measurable consequence here; the margin that makes
this true is X, and if X is exhausted the failure is not slower but different" —
never backward.

## Before you close the stage

- Every counting or balancing part has its own table, not a shared one.
- Every contributing quantity is on its own row, with sign and unit.
- No row contains two opposing effects and the word cancels.
- Every part opens with one unhedged verdict sentence under its own heading.
- No section's last sentence contradicts its first.
- The display constraint is written down as a rule the answer follows, not left
  to habit.

## Why this is here

Measured on the sixty-task FrontierScience-Research trial, one draw per task,
judged by gpt-5.1 at high effort. Chemistry is the one subject where the
pipeline arm beat the control — 80.0% against 60.0%, mean +0.799 points per task
over sixteen pairs, +0.586 after removing one task whose four-point gap is
judge sampling variance rather than any content difference. Three of the four
surface features measured do not separate the arms — character ratio 1.21,
table ratio 0.96, heading ratio 0.93 — and the fourth, boxed-result ratio 0.41,
does separate them and is not the thing being claimed here. **The separation
this section claims is the constraint**, and
in sixty tasks it was recorded exactly once — as a typed claim from one ideation
lens on one task, which then survived into the writing stage. This skill exists
to stop that from being luck. The three tasks below are all chemistry, and in
each of them it is the pipeline arm that moved.

**fs:022, +3.500.** The control produced the totals, and the working that led to
them, but nowhere put the individual contributions where a reader could take one
off the page; four items of the same shape were scored against it, three and a
half points between them. A judgement of that shape, generalised off the task,
runs: the answer provides the totals and a detailed derivation, but does not
anywhere state the individual quantities — award 0 pts. The one part it did
expand took the credit. The pipeline took all four with the per-part ledger this
skill describes, and its own text states the rule it was following: the
contributing counts are displayed on separate lines throughout rather than
folded into a total. The rule is traceable from a lens output through the
stage's locked decisions into the synthesis prompt, where the phrase appears
twice.

**fs:036, +1.500, two items attributed, and the attribution is one-sided.** Only
the control arm's per-item judgement survives on disk here; the pipeline's was
overwritten, so what is described below is the control's and what is said about
the pipeline is its recorded total against a reading of its answer. The control
lost one item, one point, to exactly the merged row this skill's second section
forbids. The pipeline split the same reasoning into two rows with separate
signed magnitudes — while its substantive conclusion was no better than the
control's, so if it took that item it was paid for by the display and not by the
content. Granularity, not correctness. The second of the two items is a
different shape altogether, nothing this skill teaches, and it sits inside the
same delta: read the +1.500 as an upper bound on what splitting the row bought,
not as its price.

**fs:034, +2.500.** The control stated the verdict a part asked for and then
qualified backwards at length; the judgement quoted the section's closing
sentence back as the position the answer took, and scored the item `0.0`. The
verdict was there, and it was read off the end of the section instead of the
top. That is one item, and the +2.500 is again a bound on what the change
bought rather than its price. The pipeline put a bolded unhedged verdict at
the top of a dedicated Answer subsection under every part and qualified
afterwards.

**This is the guardrail on the other four skills.** Three chemistry passes sit
at exactly 7.0 against a 7.0 threshold, and the recorded single-draw judge noise
is about ±0.33 — larger than the margin. So advice that shortens, merges,
simplifies before displaying, or moves a verdict into a closing summary is
advice with three tasks inside the noise band of a fail. If all three dropped,
chemistry would go from 93.8% on complete pairs to 75% — that is the arithmetic
of 15/16 against 12/16, a bound on the exposure and not a measurement of any
run. In the other direction nothing here was measured to lower a physics or
biology score, and no counterfactual can be: what is checkable is that every
instruction in this skill adds a row or moves a sentence earlier, and none of
them removes anything.

It differs from `information-transformation-ledger-for-a-multi-step-derivation`,
which builds one ledger for a whole chain at study design and analysis: this one
is a table per printed part, at the only stage a single-stage configuration runs.
