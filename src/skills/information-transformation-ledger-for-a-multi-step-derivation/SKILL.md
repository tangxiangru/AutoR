---
name: information-transformation-ledger-for-a-multi-step-derivation
description: Use at study design, analysis and writing whenever the result is produced by a chain of named steps - a symbolic derivation, a transform pipeline, a staged extraction. Covers lifting the step list verbatim from the supplied material, the per-step block that states the operation and not only the object, which steps earn a full block, and the stop condition on how much of the chain actually reached the report.
stages: 03_study_design, 06_analysis, 07_writing
---

# A chain is graded step by step, and the operation is the sentence

A multi-step result reported by its last line is an unshown derivation. So is one
reported as a pass/fail column, a per-step score, or a pointer to a file of
workings. What reads as an account of the work is the ledger: for each step, what
went in, what operation was applied, what came out, and what is different about
the output.

## The headline rule

An exhibited object with no sentence whose subject is the operation is read as a
dump. A verdict with no object is read as a score. Neither is an account of how
the result was obtained, and a criterion asking how the transformations were
carried out is scored near zero against either.

Every step you show carries both halves. The sentence is the cheaper half - one
line - and it is the half missing from nearly every report that loses this.

## The step list is not yours to invent

Lift it verbatim - from the annotation file with one record per step, the prompt
template, or the source's numbered equations and supplement headings - print the
count, and use those exact strings as headings. Your own stage names and your
arm labels destroy the correspondence. See `use-the-sources-own-names`.

## The block per step

```
### Step k - <verbatim step name from the source>
In:    <the object this step consumes, in symbols>
Does:  <the operation, as a rule a reader could apply to a different input>
Out:   <the emitted object, inline, in the source's notation>
Delta: <one sentence: which index was summed or renamed, which basis or domain
        the object now lives in, which approximation entered, which term
        vanished and why>
vs ref:<if a reference exists: the difference at the level of one symbol, index
        or argument, and what would have to hold for the two to agree>
```

`Does` and `Delta` are the lines that get read as mechanistic. Write `Does` so it
would apply to a different input - "each <object> is replaced by <what> under
<condition>" - not "we transformed the expression".

## Which steps get a full block

A long chain does not need a full block per step. Every step gets one table row
carrying its emitted object in compact form. Full blocks go to four classes:

- **Representation change** - the object moves to another basis, domain,
  coordinate system or index convention, or a compact form is written out in
  components. State the convention and the direction.
- **Approximation or truncation** - state what is neglected and the parameter or
  regime that makes it small.
- **Index reduction under a constraint** - a conservation condition, selection
  rule or symmetry collapses a sum or identifies two indices. State the
  constraint and the range it leaves behind.
- **Assembly** - the step that combines the pieces into the final object. Say
  which earlier step contributes which term, and what distinguishes each term
  from its neighbour.

Those four are what a specialist checks. Steps that only restate definitions can
stay table rows.

## Never a pointer

A side file of any size is not in the document a grader reads. If the report is
getting long, cut method and instrument prose, never the chain. See
`information-exhibit-the-intermediate-objects`.

## Divergence is content, not a tick

When your chain disagrees with a reference, the disagreement is the most valuable
thing you hold, and it is a sentence about a term: which symbol differs, which
index or argument carries the difference, and the condition under which the two
would coincide. A column reading `incorrect` communicates none of that. Neither
does a defect list about your own output - that is a verdict, and a verdict is
graded as quality control, not as analysis. Write the account of what the step
does first, then the verdict.

## Budget

This extends `run-the-requested-analysis` for the case where `data/` ships the
harness for an underlying procedure: prompt templates, gold answers, per-item
human scores, a released results notebook. The study of the harness is then
legitimate and usually requested. The failure is that it crowds out the chain.

- Before writing, count body characters spent on the chain against those spent on
  the harness, its aggregation and its graders. At least a third of the body, and
  at least one figure slot, belongs to the chain.
- Every finding about the instrument gets a second sentence whose subject is the
  object. Not "the correction loop is worth k points" alone, but "without it the
  chain survives the change of basis and fails at the index reduction; here is the
  expression it produces and the one it should". Keep both sentences.
- Anything you compute per step is plotted and tabulated against the step's own
  name, never against an integer position, so the axis and the caption carry the
  vocabulary too.

## Stop condition

Count the steps whose emitted object **and** operation sentence both appear in the
report body, over the number of steps in the source's list. Below one half, fix
that before touching anything else. A couple of blocks out of many steps is a
summary, whatever exists under `outputs/`; `publish-what-the-run-already-computed`
is the sweep that finds the objects the run already produced.
