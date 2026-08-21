---
name: the-earliest-measurement-was-taken-by-the-least-informed-run
description: Use at implementation and experimentation, and again at the head of analysis, when a run keeps learning how its tools behave after it has already measured something with them. Covers the log of tool facts and which earlier measurements each one puts in doubt, re-executing the named deliverable's own script last instead of first, and reading an unchanged diff as a result rather than as wasted time.
benchmarks: researchclawbench
stages: 04_implementation, 05_experimentation, 06_analysis
applies_when: database format
---

# What you learn about a tool is owed backwards, to the measurements you already took

The task's named deliverable is usually the first thing a run computes. It is
well specified, it is cheap, and getting it out of the way early feels like
discipline. It is also, for exactly that reason, the one measurement in the
whole run taken by the version of you that knew least about the tool — before
you read the methods paragraph closely, before you found the default that
silently filters, before you learned the wrapper rebuilds a database on every
call, before you discovered the report format is configurable and its default
drops half the columns.

Everything learned after that is applied forwards, to the experiment currently
running. Nothing applies it backwards. Hours later the run holds a detailed
understanding of its own instrument and a graded deliverable produced under the
worst configuration it ever used.

## Keep a tool-facts log

`notes/tool_facts.jsonl`, one line each time you learn something about a tool
that a measurement could depend on: a flag the source's methods names, a default
that filters or truncates, an output mode with more columns, a fixed
per-invocation cost, a thread count, a normalisation, a units convention, a
version difference. Each line carries three things — the fact, where you learned
it, and **the measurements already on disk that were taken without it**.

That third field is the whole point and it takes ten seconds to fill, because at
the moment you learn the fact you know exactly what you have already run. Filled
in later, from memory, it is guesswork.

Three kinds of fact invalidate an early measurement more often than the rest: a
default that removes rows before you see them; an output format that omits
fields unless asked; and a wrapper whose fixed setup cost is comparable to the
work it wraps.

## One script per deliverable, re-executed last

Every named deliverable is produced by exactly one script, with its inputs,
flags and output path in one place — not a sequence of shell calls in a stage
transcript that nobody can replay. Then, at the head of analysis, walk the
tool-facts log and re-execute that script under the configuration you now
believe is correct.

Diff the new output against the old, field by field. Every difference is a
result and goes in the report. **No difference is also a result**: one sentence
saying the deliverable is unchanged under everything the run learned about the
tool is worth more than the original number alone, because it is what lets you
say the value is the method's answer under the source's own configuration rather
than under a first guess. A re-run that changes nothing has not been wasted; it
has converted an assumption into a check.

Two rules keep this cheap. Re-run the deliverable through the same script and
the same output schema as the controls and the extra instances, so the diff is
mechanical. And schedule it: the deliverable is the *last* thing recomputed in
the run, not the first thing computed and then abandoned.

## Checklist

- [ ] `notes/tool_facts.jsonl` exists and each entry names the measurements taken before that fact was known.
- [ ] Each named deliverable has exactly one producing script, runnable from a clean shell.
- [ ] That script was re-executed at the head of analysis under the current configuration.
- [ ] The old and new outputs were diffed field by field and the diff is in the report — including when it is empty.
- [ ] No measurement remains on disk whose configuration the run has since learned was wrong.

## Why this is here

Measured on a structural-alignment task. The run produced the task's named
deliverable at 14:57 on its first afternoon, two hours into a thirteen-hour run,
from a script with its invocations already frozen. Over the following eleven
hours it established that the source's methods paragraph specifies four settings
it had not used, that its wrapper pays a roughly constant per-call cost of about
four seconds, and that the method's own report carries a per-pair transform and
a per-pair sequence identity. Every one of those facts was applied to the
experiments then in flight and none was applied back to the deliverable, which
reached the report unchanged: no runtime for the shipped instance, no per-pair
transforms, no per-pair identity. All three were criteria the report was graded
on, and its per-instance timings — 1.135 s and 2.865 s for the two engines on
that pair — were sitting in the deliverable's own JSON, measured and never
printed.
