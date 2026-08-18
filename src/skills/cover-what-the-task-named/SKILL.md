---
name: cover-what-the-task-named
description: Use at study design and again before writing, to check that every deliverable the task statement names has been produced. Covers how to enumerate what was asked for, why partial coverage scores worse than it feels, and what to do when a named deliverable is out of reach.
stages: 03_study_design, 07_writing
---

# The task named its outputs. Produce all of them.

Read the task statement and list, literally, every output it names: each model
to be built, each dataset to be evaluated on, each baseline to compare against,
each quantity to report. Write that list down at design time, before you have
results, and carry it to the end.

This matters more than it looks. A study that does one arm of the task
thoroughly and skips the other two does not score two-thirds — evaluation of
research asks, per requirement, whether the work is there, and a requirement
with nothing behind it scores zero however good the rest is. Depth on one arm
does not pay for absence on another.

## The failure this prevents

The common shape is: the task names three experiments; the run finds the first
one interesting; the report is an excellent study of the first one and does not
mention the other two. From the inside this feels like focus. From the outside
two thirds of the work is missing.

The second shape is subtler: the task names a comparison ("against the
incumbent method", "across both datasets") and the run reports its own numbers
without the comparison. A number with nothing to compare to is not a result.

## What to do when something is out of reach

Some named deliverables genuinely cannot be produced — the data is not supplied,
the compute is not there, the reference implementation is not public. That is a
real answer, and it is worth writing down properly: name the deliverable, say
exactly what is missing, and say what you did instead. One paragraph.

What is not acceptable is silence. A deliverable that is neither produced nor
mentioned reads as one the run forgot.

## Before you write

Go back to the list. For each entry: produced, or explained. Nothing unmarked.
