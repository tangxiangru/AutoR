---
name: decide-the-input-or-the-deadline-decides-it
description: Use at study design, and again at every stage boundary after it, when the run's own notes still carry an open question about which file or which system one of the named experiments will run on - the shipped stand-in, the authors' release, or one you generate from the Methods. Covers writing the default outcome beside every open question, ranking the list by that default rather than by difficulty, and the three-route ladder for a system the task did not ship.
applies_when: binding energy curves?
stages: 02_hypothesis_generation, 03_study_design, 05_experimentation
---

# Deferring a decision is choosing its default

An open question in a run's notes reads like rigour. The alternatives are named, the
trade is stated, nothing has been settled prematurely, and the entry says it is being
carried forward rather than decided by default. But a run has a clock and the clock
decides. A question that survives to the last stage is not resolved by argument; it is
resolved by whichever branch requires nobody to act, and that branch is almost always
"we did not do it".

So the entry in the list is not the question. Beside each one write the outcome that
occurs if nobody ever comes back to it, and the stage by which it has to be closed.
Then rank the list by that outcome rather than by how hard the question is. A hard
question whose default is "we report the smaller test set" can wait a stage. An easy
question whose default is "an experiment the task named never runs" is not open at all:
it has already been decided, in the worst direction available, and the only thing left
to do is notice.

The shape that costs the most is a question about *which data a named experiment runs
on*. Everything downstream is built around whichever file is on disk when
implementation starts - the loader, the training script, the figure slot, the section
heading, the row in the comparison table - and rebuilding all of that around a
different file once experimentation is under way costs far more than the question was
ever worth. That question closes in study design or it does not close.

## The three routes, in order

When the task ships a file that is a stand-in for the system the source actually used,
you have three routes and they are not equal.

**The authors' release.** Groups working in this area deposit their training sets,
their training scripts and often their trained models. Look for the deposit before you
look for a workaround; an hour of searching buys you the system the criterion is
written about, in the source's own units, with the source's own splits.

**Generate it from the Methods.** The Methods section states the composition, the
geometry, the coordinate that is scanned and its range, and the reference Hamiltonian
or level of theory. That is a specification, and a specification you can implement is a
dataset. This route is far cheaper than it looks, and it is nearly free in the common
case where you have *already written a generator* - to make labels for a control arm,
to build a null, to construct an analytic reference. The demonstration the task asked
for is then one more call to code that already exists. Label the generated set as
generated, state the parameters you identified and how you identified them, and put it
beside the shipped file rather than in place of it.

**The shipped stand-in, run and reported as a control.** This is a legitimate arm and
often a good finding. It is never on its own the answer for an experiment the task
names. A study that proves the supplied file cannot exhibit the effect and then trains
on it anyway has published an audit of a file where a reproduction was asked for.

`run-the-conditions-the-source-ran` is the instruction to build the counterfactual when
a precondition fails. This page is why that instruction gets executed: the
counterfactual is never built by a run that is still deciding whether to build it.

## A blocker is not a research question

A licence, a missing dependency, a download that needs a login, a file format you have
not parsed before: none of these is a question about the science and none of them
belongs in the same list as one. Move it out, give it an owner and a date, and write
down what happens when the date passes. Most are closed by an hour of reading - the
terms either permit the use, in which case you state them beside the data, or they do
not, in which case you take the next route down the ladder and say so. What a blocker
must never do is quietly change which experiment you run.

## Before you leave study design

Write one sentence per named experiment: which file it runs on, where that file came
from, and whether that is settled or still a default. Any "to be decided" in that list
names the experiment that will be missing from the report, and it is cheaper to fix now
than at any later moment in the run.

## Why this is here

Measured. A reproduction was shipped three datasets, one of them a stand-in for the
source's charged-molecule pair. The run established in its first stage that the shipped
file was not the paper's system, wrote down all three routes above by name - use the
authors' files with the terms stated, regenerate from the Methods, or keep the stand-in
- and then carried the choice as an open question through three consecutive stages,
twice recording that it was "carried forward unresolved rather than decided by
default". Its closing decision record reads: *"Carried and now decided by default rather
than by argument: the authentic charged-dimer files ... were never used ... the budget
is now spent."* Both arms were then trained on the stand-in, both landed on an analytic
floor the run had computed before any model trained, and the criterion covering that
experiment scored 27.3 against 61.0 for a plain agent that fetched the authors' files
and reported a binding-curve error of 14 meV on the source's own system. The same run
had already written and used a data generator, for a control arm.
