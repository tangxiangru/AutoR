---
name: information-state-the-technique-and-what-it-discards
description: Use at analysis and writing whenever the work invokes a standard technique of the field by name - a transformation, an identity, an approximation, an estimator, a decomposition. Covers stating the rule and its convention before applying it, naming what the technique costs, showing the expansion it generates before simplification, and what to do with conditional steps you skipped.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
---

# Naming a technique is citing it; the report has to show it executed

Standard machinery gets invoked in one clause - "applying <technique>, we obtain"
- and the next line is the result. The technique is named and never stated, the
intermediate expansion never appears, and the assumption it introduced is never
written down. From that, a reader cannot tell whether you executed the technique,
copied its output out of the source, or asked a model for it.

This is the loss that survives after the objects are printed. A chain of correct
expressions with the operations only implicit in them is graded as equations
without analysis: the criterion asks how the operation was performed, and the
report answers what came out of it.

## What an account of a technique contains

Four parts, for every named technique the work invokes. Together they are a short
paragraph plus one displayed expansion - not a section.

1. **The name the field uses**, not a paraphrase, and the source's words for it
   where the source names it. A report that says "we transformed the expression"
   is unsearchable by anyone looking for the technique.
2. **The rule, stated once in general form, before it is applied**, together with
   the convention you adopted: sign, ordering, prefactor, normalisation,
   direction, discretisation, boundary or gauge choice. Most standard techniques
   have two or more conventions in circulation, and an unstated convention is
   where two otherwise correct derivations silently disagree.
3. **What it costs.** Exact identity or approximation? If exact, name the property
   of your object that licenses it. If approximate, name the neglected object and
   the parameter or regime that makes it small, and say what the result would look
   like if that parameter were not small. "Standard" is not a licence; a technique
   applied outside its condition is the most common wrong step in a long chain.
4. **The applied instance, shown before simplification.** The complete set of
   terms the rule generates on your input - all of them, with signs - and then the
   surviving set, with one clause per dropped term saying why it went.

## The pre-simplification expansion is the proof of execution

A final expression can be copied from anywhere. A full expansion cannot: it has
the right number of terms, the right signs and the right index structure only if
the rule was applied to your object. Where a technique generates several terms and
only some survive, the intermediate costs a few lines and is the whole difference
between a derivation and an assertion.

Put it at the step where it happens, inside that step's block, not in a methods
appendix and not in a preamble. The account and the object are read together or
neither is read.

## Conventions, collected

Keep one small table: technique, convention chosen, where it is first used. It
costs five minutes and it catches the failure that no correctness check finds -
the same technique applied twice under two different conventions, each locally
right, the composition wrong.

## Conditional and skipped steps

Procedures written as templates contain steps that apply only to some instances.
A conditional step you skipped still needs its line: name it, say it does not
apply here, and give the property of this instance that makes it unnecessary. An
omitted conditional step is indistinguishable from a forgotten one.

## Provenance per step

If a step's output was produced by a tool, a solver or a model rather than by you,
say so at that step. That does not excuse you from parts 1-3 - the rule, the
convention and the cost are still yours to state - and it makes part 4 the object
you checked rather than the object you claim to have produced. A step whose
provenance is unstated is read as your own work and graded as such.

## Checklist

- [ ] Every technique the chain invokes appears in the report body by name. Grep
      for each one; zero hits means the step is invisible, whatever ran.
- [ ] Each has its rule in general form and its convention, stated before use.
- [ ] Each says exact-or-approximate, and the approximate ones name what they
      discard and under what condition that is safe.
- [ ] At least the techniques that generate multiple terms show the expansion
      before simplification.
- [ ] Conditional steps that were skipped are named with the reason.
- [ ] No technique is introduced for the first time in a figure caption or an
      appendix.

## Boundary with the neighbouring skills

`information-transformation-ledger-for-a-multi-step-derivation` is coverage: one
entry per step across the whole chain, so nothing is missing. This skill is depth
at the few steps that invoke standard machinery, and it is what fills their
`Does`, `Delta` and pre-simplification lines. `use-the-sources-own-names` covers
carrying the source's names for reproduced objects; a technique needs its name
*and* its statement, because the name alone is a citation.
