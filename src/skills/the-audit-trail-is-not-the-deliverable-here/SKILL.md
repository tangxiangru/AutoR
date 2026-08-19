---
name: the-audit-trail-is-not-the-deliverable-here
description: Use at every stage of a run graded on a predictions file, whenever a gate is asking for manifests, claims, sources, coverage or provenance. Covers producing each artifact once at the size the gate accepts, the difference between satisfying a gate and elaborating one, and the specific elaborations that have eaten whole runs.
applies_when: predictions will be scored
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design, 04_implementation, 05_experimentation, 06_analysis
---

# Satisfy the gate. Do not develop a relationship with it

This pipeline asks every stage for machine-readable evidence: sources and claims
that cross-reference, a hypothesis manifest with decision rules, a report plan, an
experiment manifest, coverage entries, provenance. Those gates exist for good
reasons and they are not optional — a refused stage costs more clock than the
artifact would have.

They are also, on a task graded by a metric over a predictions file, worth exactly
zero. The correct relationship is: produce each one once, at the size that passes,
and return to the model.

## What over-service looks like

These are real, from a scored arm, and each was a defensible act:

- Resolving the DOIs for two architectures the run had already decided not to
  build, then rewiring its claims to cite them.
- Building "an independent verifier for every stage number" — a second
  implementation of the pipeline's own checking, written in the last hour.
- A "full integrity sweep of all artifacts", twice.
- Four calls locating and removing a parenthesised backtick from a notes file.
- Forty-one appends to a claims ledger on a task whose score is a mean absolute
  error.

On the worst-affected task, 294 of 427 tool calls were of this kind and they all
came after the predictions file had stopped changing. The run was not idle and it
was not careless. It was doing the wrong job carefully.

## The test before you write

Before any call that touches a manifest, a claim, a source or a coverage entry,
answer one question:

> Is a gate currently refusing me, or blocking the stage I am trying to leave?

- **Yes** → write the minimum that clears it. One entry, one claim, one path.
- **No** → this call is optional, and the deliverable is older than it was.

There is no third answer. "It would be more complete" and "the record should
reflect what I found" are both descriptions of a document nobody scores.

## Write it once, at gate size

A useful default for each artifact class:

| artifact | what clears the gate |
|---|---|
| sources / claims | the sources you actually used, each cited by one claim that needs it |
| hypothesis manifest | one hypothesis per thing you will actually measure, each with its decision rule |
| report plan | the figures you will really produce, named, each against a claim |
| experiment manifest | the runs you really executed, with their numbers |
| coverage | one entry per demand in the task statement, quoting it verbatim |

In every row, the sizing word is *actually*. An artifact describing work you did
not do is both more expensive and more likely to be refused, because the validator
checks that the paths resolve and the numbers appear in a results file.

## The one exception worth making

Recording a **measured number** is never over-service, even when no gate is asking:
the validation score of the model currently in the submission, the wall clock a
fit took, the row count you checked. Those are inputs to the next decision about
the deliverable. The distinction is not "artifact versus model" — it is whether
the thing you are writing will change what you do next.
