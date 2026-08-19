---
name: a-scoreable-file-in-the-first-hour
description: Use at the first stage of a run whose deliverable is a predictions file, and again at every stage when one still does not exist. Covers why a trivial submission written early dominates a good one written late, what the first version should contain, and how to improve it in place without ever leaving it invalid.
applies_when: predictions will be scored
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design, 04_implementation
---

# Write a scoreable file before you write anything else

A predictions file that does not exist scores nothing. Not a low score — no score,
and on a benchmark that reports *valid submission rate* as a headline metric
beside the score, a missing file costs you on two axes at once.

So the first version is not a milestone to work toward. It is a thing to get out
of the way in the first hour, from whatever you can compute immediately, and then
improve in place for the rest of the run.

## Why this is not the obvious advice

The instinct is that a trivial submission is embarrassing and that a real one is
close, so it is better to wait. Two measurements say otherwise.

Every run of a scored arm on this benchmark hit its wall clock — nineteen of
nineteen — and none of them finished the pipeline they had planned. Six never got
past the first stage. Whatever a run intends to do at stage five, it should assume
it will not get there.

And a run on that arm shipped **1,137 rows where the split has 1,147** and scored
nothing at all on a task it had otherwise solved, because the file was written
once, late, and never re-checked.

## The first version

Build it from the training labels alone, with no model:

| task shape | first submission |
|---|---|
| regression | the training mean, or the per-group mean if a grouping column is obvious |
| classification | the majority class, or the class prior |
| ranking / retrieval | the identity ordering, or a length or frequency heuristic |
| generation scored by overlap | the most common training answer, or the input echoed |
| forecasting | the last observed value, or the seasonal naive |

Each of these is ten minutes of work and each is a real floor. Several of them
are not far off what a tuned model gets on a hard task, which is itself worth
knowing before you spend three hours on the model.

Then, in the same hour, write the check that keeps it valid — see
`the-row-count-comes-from-the-split-not-the-brief`.

## Improve in place, never in a branch

Every later model writes to the same path, and only after it has beaten the
current file on a validation split you built. The sequence for every improvement
is the same four steps:

1. score the candidate on your held-out split
2. compare against the score of what is currently in the file
3. if it wins, write it and record both numbers
4. re-run the shape check

Step 2 requires you to have kept the current file's validation score. Keep it in a
one-line file next to the submission; a number you have to recompute is a number
you will skip recomputing.

**Never move the file aside while you work.** The most expensive version of this
mistake is a run that deletes a valid submission to write a better one, then runs
out of clock in between.

## What to do with the rest of the hour

Once the file exists and the check passes, you have bought the right to be
ambitious for the remaining three hours, because the downside is now bounded by a
number you have already banked rather than by zero.
