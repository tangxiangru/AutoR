---
name: the-reproduction-is-a-hypothesis
description: Use at Stage 02 and Stage 03 whenever the task is to reproduce, re-implement or verify a published study and the hypotheses you are drafting are all about something else. Covers how to write the reproduction itself as a falsifiable frozen commitment, why a self-invented question crowds it out, and how to budget between the two.
stages: 02_hypothesis_generation, 03_study_design
---

# "This reproduces" is falsifiable, and it is usually the hypothesis that matters

A hypothesis has to be able to fail. That test is easy to apply badly to a
reproduction, because "we will re-implement the paper" is an engineering goal
with no plausible failure and no surprise in either direction — so the drafting
stage rejects it, and the run goes looking for a question of its own.

The question it finds is often a good one. It is also, reliably, not the task's
question, and once it is frozen it becomes the only contract the run has. Every
later stage adjudicates it, the figure plan is drawn around it, and the report is
organised by it. The reproduction the task actually asked for survives as a
subsection, or as a comparison table, or not at all.

## Write the reproduction as a hypothesis, properly

The engineering-goal objection is right about the *phrasing* and wrong about the
*content*. "We will re-implement X" fails the test. These do not:

- **H: The published value is recoverable from the supplied inputs.** Supported if
  our estimate falls within the source's stated uncertainty of its value; refuted
  if it differs by more than that. This can fail, it fails often, and when it
  fails you have a finding the field would want.
- **H: The published effect survives the ablation the source did not run.** The
  source reports A beats B; our reproduction holds the budget equal and asks
  whether the ordering survives. Refutable by construction.
- **H: The mechanism the source proposes is the one carrying the effect.** Their
  explanation predicts a specific quantity behaves a specific way; measure that
  quantity.

Each of these is the reproduction, and each names an outcome that would surprise
someone. A reproduction that lands on the number is a confirmation with a
tolerance; one that misses is a discrepancy with a magnitude. Both are results.

## The budget rule

When the task names a reproduction, **the reproduction's hypotheses are frozen
first and get the larger share of the compute.** Your own question is an
extension, it is frozen second, and it is budgeted from what is left. This
ordering is not modesty — it is what makes your extension interpretable. An
improvement measured against a reproduction you did not complete cannot be
attributed to the improvement.

Count the hypotheses you are about to freeze. If the task's outputs are three
things and you are freezing eighteen propositions, none of which is "the three
things come out right", the contract you are signing is not the one you were
given. Freezing more hypotheses is not more rigour; it is a longer list of
questions the grader did not ask.

## Do not let a Stage 01 conclusion close the question

The literature survey will sometimes establish that exact numeric agreement with
the source is not well posed — the seed is unstated, the data has moved, the
hardware differs. That is worth recording. It is **not** a reason to replace the
reproduction with a study of why reproduction is hard. Record the obstacle, set a
tolerance that accounts for it, and reproduce against the tolerance. A conclusion
reached before the first experiment should widen an error bar, never delete an arm.

## The check before Stage 04 approval

Read the task statement's list of outputs, then read the frozen hypothesis set.
Every named output should be adjudicated by at least one hypothesis whose decision
rule mentions a quantity from the source. If the two lists share nothing, go back:
the run is about to spend its whole budget proving something nobody asked.

See also `reproduce-then-extend` for the shape of the comparison, `cover-what-the-task-named`
for enumerating the outputs, and `close-the-gap-to-the-published-number` for what
to do when the reproduction lands off the published value.
