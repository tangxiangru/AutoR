---
name: information-check-the-steps-yourself-not-only-their-scores
description: Use at implementation and experimentation when the deliverable is a multi-step symbolic or analytic calculation whose correctness would otherwise rest on a grader, a rubric or a similarity score. Covers the cheapest mechanical check that applies to each class of step, the time cap that stops checking from displacing the write-up, and reporting the table with one worked failure beside the grader's verdict.
benchmarks: researchclawbench
stages: 04_implementation, 05_experimentation
---

# A step you only scored is a step nobody checked

When the deliverable is algebra or a symbolic pipeline, correctness is usually
established by comparison: score each step against a reference with a model
instrument, a rubric, a string or embedding similarity, a human key. That gives a
rate. It does not give a reason, and it inherits the instrument's weaknesses -
graders of this kind accept an object of the right shape for the wrong problem,
and reject a correct expression written in different index names.

A cheap mechanical check per step buys three things the rate cannot: a reason, a
located failure, and a case where you and the grader disagree.

## Cheapest check that applies, in this order

Do not build one check per step, and do not build the expensive kind first.

1. **Numeric instantiation.** Default, and it applies to most steps. Build one
   small explicit instance - the smallest system with more than one of every index
   - fix sizes, parameter values, seed and tolerance once, and evaluate both sides
   of the step on it. This catches dropped factors, wrong normalisations,
   transposed indices and sign errors, which are the common failures.
2. **Brute-force enumeration.** For any step that reduces or renames indices under
   a constraint: enumerate a small index set, evaluate the unreduced and the
   reduced form, assert equality. Overapplying a constraint is exactly the failure
   here and it is invisible in the final expression.
3. **Symbolic term comparison, only with a library that does the bookkeeping.**
   Where an established symbolic package covers your algebra, expand both sides
   and compare term sets with signs. Do not hand-roll a term algebra for a
   one-off; that is a multi-hour build and its own source of errors.
4. **Invariants and limits on the assembled object.** Symmetry, positivity,
   dimensional consistency, conserved counts, and the limit in which a parameter
   goes to zero and the object must collapse to the simpler known one. If the
   object is defined by a fixed-point condition, iterate it and report whether it
   converges and to what.

Reuse the one small instance across steps so the checks compose: the output of
step k is the input of step k+1 on the same numbers.

## The cap, and what outranks the check

Time-box each check. If it is not working inside the box, stop, write the
operation account for that step, and move on. **The check never displaces the
prose that names what the step did** - that prose is the graded object, the check
is evidence for it. A run that spends its budget building verification machinery
and ships no step accounts has repeated the failure it was trying to avoid, one
level up.

Build the checks against the reference material first, before your own output. A
check that fails on the known-correct expression is a bug in the check, and
finding that out afterwards costs you the result.

Where no cheap check exists, one line saying so and why is a result about the
step, not a gap.

## How to report it

One table in the report body:

| step (the source's name) | check | what it would catch | result |

and then **one failing check written out in full**: the term, the index, the sign,
the value on each side, and the condition under which the two would agree. A table
of green ticks is worth much less than a single worked failure, because the
failure is what proves the checks have teeth.

If the task also asks for graded or scored outputs, produce them - a task-named
deliverable is never withheld on principle. Report the grader's rate with the
mechanical check beside it wherever a cheap check exists, and reconcile them.
Every disagreement is a second, sharper result: a measured case where the
instrument accepted a wrong object or rejected a right one, with the object
attached.

## Rules

1. A rate whose only support is a model's judgement is reported together with the
   check, where a cheap check applies. Where none applies, say which steps are
   grader-only.
2. Checks live in `code/` behind a single entry point, and its summary line goes
   in the report, so a reader knows the table came from a program rather than from
   reading.
3. The check's job is to locate a failure, not to award a mark. Report which term
   is wrong, not how many steps passed.

## Boundary with the neighbouring skills

`reproducibility-check` is about your pipeline re-running and yielding the same
numbers; a perfectly reproducible pipeline reproduces wrong algebra forever.
`evidence-not-assertion` is about sourcing each number to a file this run wrote.
This skill builds an independent oracle for the deliverable itself, so the report
can say the derivation is right rather than that it was scored as right. Its
output feeds the `Delta` and `vs ref` lines of
`information-transformation-ledger-for-a-multi-step-derivation`.
