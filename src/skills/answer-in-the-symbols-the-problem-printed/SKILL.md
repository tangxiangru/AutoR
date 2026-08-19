---
name: answer-in-the-symbols-the-problem-printed
description: Use at hypothesis generation when the sheet prints its own symbols, Hamiltonian or coordinates and the run is about to freeze a notation of its own for everything downstream. Covers transcribing the printed symbol table before any framing, why an algebraically equivalent expression in renamed variables reads as a missing expression, and keeping the exact or general result on the main line instead of demoting it behind the approximation you prefer.
applies_when: intermediate derivations
stages: 02_hypothesis_generation
---

# A correct expression written in your own symbols is an expression nobody can find

When a sheet prints a Hamiltonian, a coordinate pair, a coupling constant or a
rate, those symbols are part of the question. An expression that is
algebraically equivalent but written in variables you introduced is not a
partially correct answer to that question — it is read as the expression not
being there. The equivalence is obvious to you because you did the substitution.
To a reader holding the printed form against your page, it is absent.

This is not a rounding error at the margins. A notation frozen early propagates
into every line written afterwards, so one renaming decision at framing time
reappears in six or eight separate places in the finished answer.

## Transcribe before you frame

Before any hypothesis, any decomposition, any lens on the problem, copy out of
the sheet:

- every symbol it prints, with the quantity it denotes;
- every equation it prints, verbatim;
- every named coordinate or basis it works in.

That table is fixed for the rest of the run. Do not rename to a symbol you find
clearer. Do not silently drop a printed quantity because your framing does not
need it — dropping one is worse than renaming one, because everything that
depended on it disappears with it. If your treatment genuinely needs a different
variable, define it **from** the printed one in one line, and give the final
result in the printed symbols as well.

Never let a downstream stage inherit a notation nobody checked against the sheet.
The renaming is invisible at the point where it happens and unfixable afterwards.

## Give the printed form, then yours

For every quantity the sheet asks for:

1. Write it in the printed symbols, in the printed basis, in the printed form.
2. Then write your own version if you have one, and say they are the same thing.

The cost is one extra line each. The saving is every expression the sheet asked
for being findable at the place it was asked for.

## The exact result goes on the main line

The second half of the same failure is placement. A general or exact result that
is derived and then, four lines later, replaced by a limit — an elimination, a
steady state, a leading order — has been demoted. What the document then argues
is the approximation; the exact statement survives as a step that was passed
through, and cross-checks placed two thirds of the way down under a heading that
calls them cross-checks are read as cross-checks.

So:

- **Derive the general result and keep it as the result.** Give it its own
  heading, in the sheet's own vocabulary.
- **Then take the limit, in its own separately headed subsection**, labelled as
  the approximation it is, with the condition under which it holds.
- **Check the condition and say whether it holds here.** A sheet that supplies
  parameters is frequently supplying them so you can find that the standard
  approximation is not licensed. A run whose principal section is named after
  the approximation has answered the question it wanted.
- If you run several routes, the route that carries the exact result is the main
  route. Name it for the result, not for the method.

## Before you close the stage

- The printed symbol table is transcribed and nothing in the answer renames a
  symbol in it.
- No printed quantity has been dropped.
- Every asked-for expression appears once in the printed form and basis, in the
  section that owes it.
- The general result has its own heading and precedes any limit of it.
- Each approximation is labelled, its condition stated, and the condition checked
  against the numbers the sheet gave.

## Why this is here

Measured on the sixty-task FrontierScience-Research trial, one draw per task,
judged by gpt-5.1 at high effort. Two physics tasks carry **4.575 of the 5.100**
points the pipeline arm lost across eleven complete physics pairs; the other
nine average −0.058. Bracketed material inside a quoted judgement is a redaction
and not the grader's words.

**fs:006, physics, −1.575 against the pipeline arm, confirmed.** The sheet
prints its own symbols for the quantities it asks about. The pipeline's Stage 02
stage document uses a substitute symbol 30 times and the printed notation **not
at all**; its answer inherits the substitution 72 times against a single use of
a printed symbol, while the control uses the printed symbol 25 times and the
substitute 0. The renaming reaches criteria spread across the whole sheet rather
than one corner of it. The grader's judgements on the affected items run in both
directions: on one, `the specific form ... is not written. Score: 0/0.5` against
the control; on another, `This matches exactly` for full credit where the
control had kept the printed form intact and the pipeline had substituted it
away for an algebraically equivalent expression. On a third the pipeline
answered a different question from the one asked, having carried its own
variable into a step the criterion was checked against in the printed one; the
structure the criterion asks for could not appear at all, and one of the printed
quantities appears **0 times** in the answer.

Record the counter-evidence: fs:006 is not monotone. On one item worth 1.0 the
control was marked `The specific [expressions that item names] are not written
anywhere in the answer. Score: 0/1.0` while the pipeline wrote part of what was
asked for. This skill is about which symbols, not about how much.

**fs:009, physics, −3.000 against the pipeline arm, inferred, and the inference
is flagged.** The pipeline arm's per-item reasoning was overwritten on disk and
cannot be quoted; what follows is a comparison of the two answers against the
criteria. The heaviest single item on the sheet went to the control at full
marks, on a judgement of the shape `This is the complete solution ... full
marks` — one of several shapes seen in the trial wherever an exact result was
written out on the main line. The structurally identical solution is present in
the pipeline answer at 26% of the document — and 400 characters later it is
replaced by a boxed limiting form, under a principal section heading naming the
approximation, with the exact solution carried through only under a route
labelled a cross-check at 69% of the document. The approximation's name appears
9 times against the control's 2. The pipeline took a tenth of the available
points. The placement is measured; the causal link to that item is not, because
the reasoning file is gone.

Two candidate explanations are excluded quantitatively and must not be designed
against: the pipeline's physics answers are **not shorter** (unique-content ratio
median 1.10 against the de-duplicated control, longer on 6 of 11 pairs) and not
less mathematical (display-equation density 1.11 against 1.22, with the whole
gap coming from two tasks that write their formulas in plain text blocks).

**Checked against what chemistry pays for.** Every instruction here adds a line
and removes none: the printed form *in addition to* your own, the general result
*before* the limit. That is the same granularity chemistry is paid for. Where a
sheet's criteria ask for intermediate quantities in the units the sheet itself
works in, an answer that silently carries them in another unit system loses
those items; the trial has one task where that happened to **both** arms at
once, so it is an observation about the failure mode and not a gain either arm
made, and no advice here is designed against it. On fs:036 the control collapsed
content the criteria credited separately into a single row and scored 0.0/1.0
for it; nothing here licenses that collapse. The rule against renaming is the
same rule chemistry needs.
