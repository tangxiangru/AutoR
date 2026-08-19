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
nine average −0.058.

**fs:006, −1.575, confirmed.** The sheet's Hamiltonian is printed with two
symbols. The pipeline's Stage 02 stage document uses a substitute symbol 30
times and the sheet's two symbols **0 times each**; its answer inherits the
substitution 72 times against a single use of the printed symbol, while the
control uses the printed symbol 25 times and the substitute 0. The renaming
touches six separate criteria. On item 3 the grader wrote of the control `the
specific form ... is not written. Score: 0/0.5`; on item 6 the control's summary
table gave the printed form with its rate variable intact and was marked `This
matches exactly` for the full 0.5, while the pipeline substituted the rate away
and produced an algebraically equivalent pair that does not contain it. On
item 13 the pipeline solved a different differential equation, because it took
its limiting case in the substituted variable rather than in the printed one —
so the structure the criterion asks for could not appear at all, and one
function in the printed set appears **0 times** in the answer.

Record the counter-evidence: fs:006 is not monotone. On item 8, worth 1.0, the
control was marked `The specific [equations that item names] are not written
anywhere in the answer. Score: 0/1.0` while the pipeline wrote part of that set.
This skill is about which symbols, not about how much.

**fs:009, −3.000, inferred, and the inference is flagged.** The pipeline arm's
per-item reasoning was overwritten on disk and cannot be quoted; what follows
is a comparison of the two answers against the criteria. Item 3 carries 3.0 of
the task's 10 and the control was scored `This is the complete solution for [the
dynamics item 3 names] ... Score: 3.0/3.0`. The structurally identical solution
is present in the pipeline answer at 26% of the document — and 400 characters
later it is replaced by a boxed limiting form, under a principal section
heading naming the approximation, with the exact solution carried through only
under a route labelled a cross-check at 69% of the document. The
approximation's name appears 9 times against the control's 2. The pipeline
scored 1.0 of 10. The
placement is measured; the causal link to item 3 is not, because the reasoning
file is gone.

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
made, and no advice here is designed against it. On fs:036 the control merged
two opposing contributions into one row and scored 0.0/1.0; nothing here
licenses that merge. The rule against renaming is the same rule chemistry needs.
