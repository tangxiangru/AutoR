---
name: math-an-unused-hypothesis-is-a-stronger-theorem
description: Use at analysis and writing when your system emits proofs, derivations or certificates for problems that arrive with stated hypotheses, and you are about to report how many of them closed. Covers reading the minimal premise set off each proof you already wrote to disk, publishing the per-problem premise-usage table, deleting a hypothesis nothing used and re-running to confirm the generalisation, and why an internal soundness check does not answer this question.
applies_when: machine-verifiable|human-readable proofs
stages: 06_analysis, 07_writing
---

# Every proof also tells you which hypotheses it did not need

A solved-count throws away nearly everything a proof contains. The proof is a
dependency graph rooted at the goal, its leaves are the hypotheses that were actually
used, and the problem statement gives you the hypotheses that were *allowed* to be
used. The difference between those two sets is a mathematical result, and it costs
one pass over an object your run has already written to disk.

## Compute the difference, per problem, and publish the table

For each problem the system closes: the premises the problem states, the premises the
proof's dependency graph reaches, and the set difference. Three columns and one row
per problem. The rows where the difference is empty are informative — they say the
problem is tight — and the rows where it is not are the interesting mathematics in
your run.

This is not an extra experiment. If your engine prints a proof at all, it has already
computed the minimal premise set, because that is what pruning the derivation to the
goal means. The work is reading it out and joining it against the input statement.

## A hypothesis no proof needed is a stronger theorem, so state it as one

Do not leave it as a table cell. Take the problem, delete the unused hypothesis from
the input, re-run the solver from a freshly sampled instance, and confirm the goal
still closes. Then write the weakened statement out as a theorem, in the source's own
identifier — *problem X asks for this under conditions A, B and C; the machine proof
uses only A and B, and the conclusion holds without C* — and give it a subsection in
Results with a sentence on what the generalisation means. Competition problems in
particular carry conditions their conclusions do not need, put there to make the
problem findable rather than because the mathematics requires them, and a machine
that notices this is doing something a solved-count cannot express.

Do this before you invent an extension of your own. It is the cheapest new
mathematics available in the run: it is derived from the deliverable you already owe,
it needs no new compute beyond one confirmation re-run per candidate, and it is the
one kind of result a reproduction can have that the source's headline number does not
already contain.

## A module in the release named for this is a deliverable, not a utility

Reference implementations name their files after what the authors thought the system
produced. A module called `trace_back`, `explain`, `minimise` or `attribute` is not
plumbing for the pretty-printer — it is the component that recovers which assumptions
a conclusion rests on, and the authors built it because the answer was worth having.
If your harness imports such a module only to hand it to the release's own renderer,
you own the tool and none of its output. Call it yourself, over your own results, and
put what it returns in the report.

## An internal soundness check answers a different question

Verifying that every cited fact resolves, that citations point strictly backwards,
that no identifier is introduced twice and that the last line is the goal establishes
that the proof is *well-formed*. That is worth doing and it is worth controlling with
deliberate mutations. It says nothing at all about whether the problem needed all of
its hypotheses, and a run that ships the well-formedness audit and not the premise
audit has done the harder engineering and skipped the mathematics.

## Why this is here

Measured on Math_003 of ResearchClawBench, gpt-5.1 judge, three draws. The checklist
item asking whether the run's dependency-traceback found an unused premise in a named
benchmark problem and turned it into a more general theorem (weight 0.25) scored
**0.0 for AutoR against 8.3 for bare Claude Code** — 2.1 of the 9.2 weighted points
the task lost. The words "traceback", "trace_back" and "unused premise" appear **zero
times in AutoR's 42 KB report** and "unused premise" zero times across every one of
its stage notes, while its own `code/ag_harness.py` imports the release's `trace_back`
module and passes it straight to the release's proof renderer — the only reference to
it in the whole of `code/`. The run built 14 proof objects, wrote a
`check_proof_objects.py` that verifies every citation resolves and points backwards,
controlled that checker with four deliberate mutations, and never asked which of the
supplied premises any proof had used. The bare agent scored its 8.3 by calling
`trace_back.get_logs` for minimal premise sets while building its corpus — the same
call, pointed at the generator instead of at the benchmark's own problems. The
installed skill `run-the-conditions-the-source-ran` lists this failure among its
examples and did not change the outcome; what is here and not there is what to
compute, how to confirm it, and where it goes in the report.
