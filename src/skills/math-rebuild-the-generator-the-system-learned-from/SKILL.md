---
name: math-rebuild-the-generator-the-system-learned-from
description: Use at study design and implementation when the source system's headline rests on a training corpus its public release does not ship — millions of machine-generated examples, a self-play archive, a synthesised problem set — and what was released is only the solver or the evaluator. Covers why the generator is a build item and not a scope boundary, how to reconstruct it from the Methods description using the released solver as its inner loop, and which statistics make a corpus a thousand times smaller comparable to theirs.
applies_when: without human demonstrations|no human demonstrations
stages: 03_study_design, 04_implementation, 05_experimentation
---

# The corpus is not an artifact you were denied, it is an algorithm the paper prints

A system whose whole claim is that it learned without being taught got its training
data from somewhere, and that somewhere is a program. When the public release
contains the solver and not the pipeline that generated the examples, the study
design decision in front of you is not "can I obtain a hundred million examples"
but "can I run their loop for an hour". Those have different answers, and only the
first one is expensive.

## Price the mechanism, not the paper's configuration

The trap is a table with two rows in it: *rebuild the published system, needs a
hundred thousand CPU workers for three days*, against *run the released solver,
needs two hours*. Written that way the choice makes itself, and the run scopes out
the half of the system that carries the paper's actual thesis. The row that is
missing is the one worth having: **their loop, your budget, their statistics.** A
generator is a few hundred lines. Its cost is linear in how long you leave it
running, and there is no threshold below which it stops producing valid examples —
it just produces fewer of them.

Put that third row in the design table before you cost anything, and cost it in
worker-hours you actually have. If a machine-hour of generation produces tens of
thousands of examples, you have a corpus, and every downstream arm that was blocked
on "no training data" is now unblocked.

## Read the loop out of Methods and rebuild it with the released solver inside it

Methods sections describe generation procedurally because that is the only way to
describe it: sample a random starting object, run the engine to exhaustion, harvest
every consequence it derived, and turn each consequence into an example by splitting
what was assumed from what has to be supplied. Write those steps down as steps and
implement them one at a time.

The reconstruction is much cheaper than it looks, because **its inner loop is the
release you already have running**. The engine you benchmarked is the engine the
generator calls; the dependency-tracking utility that renders a proof is the utility
that tells you which part of an example is the premise and which is the target. If
you have reproduced the solver, you are one script away from the generator, and that
script is the only unreleased thing standing between your run and the paper's
contribution.

Two guards are worth writing before the first shard lands, because both silently
halve the yield: reject a sampled object that fails its own numerical or consistency
check rather than letting it into the corpus, and drop any example whose target
refers to something absent from its own prompt. Count both rejection rates — they
are the first honest statistics you have about your own pipeline.

## Validate against the corpus statistics the source publishes, never against its size

You will not match their size, and matching their size is not what makes your corpus
a reconstruction of theirs. What makes it one is that it has the same *shape*. Papers
that generate data report scale-free properties of it — what fraction of examples
require the hard step, how long the derivations run, which categories of conclusion
dominate — and those are the quantities to put in a table beside your own. A rate
within a factor of two of theirs is evidence you rebuilt their pipeline; a rate off
by an order of magnitude means you rebuilt a different one, and finding that out is
worth the hour it costs.

Then state your scale as a ratio, and put it where the reader meets your downstream
numbers rather than in a methods footnote: *N examples generated in H worker-hours,
one thousandth of the source's corpus*. A ratio lets a reader place every later
result. A missing corpus with an apology lets them place nothing.

## "Not available in this environment" is a sentence about the artifact

It is true, and it is not an answer. The artifact is unavailable; the method is
published; the question a reader has is what your run did about that. The honest
answers run from "rebuilt it at a thousandth scale and matched its reported rates"
down to "did not attempt it", and writing the unavailability into Limitations while
building nothing puts you at the bottom of that range while sounding like the top of
it. If the generator genuinely cannot be rebuilt — the procedure is not described, or
its inner loop is the component that will not run — say which of those two it is, in
one line, after an attempt you can describe.

## Why this is here

Measured on Math_003 of ResearchClawBench, scored per checklist item with a gpt-5.1
judge over three draws. The item about the source's hundred-million-example synthetic
corpus (weight 0.35) scored **11.0 for AutoR against 29.3 for bare Claude Code** —
6.4 of the 9.2 weighted points the task lost, more than the other two items together.
AutoR's Stage 03 design note prices "rebuild the full system" at 100,000 CPU workers
x 72 h, adopts a symbolic-only reading, and the word "synthetic" then appears **zero
times across every one of its stage notes** and once in its final report, in a
sentence saying the corpus is unavailable. The bare agent, in 12,441 s of wall clock
against AutoR's 50,732 s, re-implemented the generator from the paper's Methods with
the released solver as its inner loop and wrote `outputs/synth/`: 170 shards, 85,973
machine-proved theorems, an auxiliary-construction rate of 0.199 against the ~9% its
report attributes to the paper's corpus, and the size ratio to the published corpus
quoted in its abstract. Same benchmark, same released code, same missing artifact;
one run treated the generator as a build item and the other as a boundary.
