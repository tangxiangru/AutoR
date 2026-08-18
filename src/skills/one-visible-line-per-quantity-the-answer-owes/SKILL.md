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
judge sampling variance rather than any content difference. Surface features do
not separate the arms at all: character ratio 1.21, table ratio 0.96, heading
ratio 0.93, boxed-result ratio 0.41. **The separation is this constraint**, and
in sixty tasks it was recorded exactly once — as a typed claim from one ideation
lens on one task, which then survived into the writing stage. This skill exists
to stop that from being luck.

**fs:022, +3.500.** Five criteria are per-part counts. On four of them the
control was scored, verbatim: `the answer provides [the totals] and a detailed
pathway, but does not anywhere state the specific combination ... Award 0 pts` —
0 of 3.5. Its one expanded part took the credit. The pipeline scored 10.0/10
with a separate row-per-contributor table under each part, each with a bolded
total row, and its own text states the rule it was following: the contributing
counts are displayed on separate lines throughout rather than folded into a
total. The rule is traceable from a lens output through the stage's locked
decisions into the synthesis prompt, where the phrase appears twice.

**fs:036, +1.500, both points attributable.** The control's own step table
merged two opposing requirements into one row ending `(cancellation)` and was
scored `their net conclusion is opposite to what the rubric specifies. Score:
0.0 / 1.0`. The pipeline split the same physics into two rows with separate
signed magnitudes and took the point — while reaching a net conclusion no closer
to the expected one. Granularity, not correctness. The second point came from
naming the cycle as its own step sequence where the control was scored `Score:
0.5 / 1.0` for using a different one in its main line.

**fs:034, +2.500.** Item 3 asks for a plain verdict. The control was scored `The
student states ... "[the verdict the part asks for]," but then devotes a long
section to ways in which [the stated interval] can fail ... and concludes: "...
a probabilistic, not deterministic, loss." This explicitly asserts there *can*
be consequences. Score: 0.0`. The pipeline put a bolded unhedged verdict at the
top of a dedicated Answer subsection for each of the five parts and qualified
afterwards.

**This is the guardrail on the other four skills.** Three chemistry passes sit
at exactly 7.0 against a 7.0 threshold, and the recorded single-draw judge noise
is about ±0.33 — larger than the margin. Any advice that shortens, merges,
simplifies before displaying, or moves a verdict into a closing summary takes
chemistry from 93.8% on complete pairs to 75%. Nothing in this skill can lower
a physics or biology score: it adds rows and moves a sentence earlier.

It differs from `information-transformation-ledger-for-a-multi-step-derivation`,
which builds one ledger for a whole chain at study design and analysis: this one
is a table per printed part, at the only stage a single-stage configuration runs.
