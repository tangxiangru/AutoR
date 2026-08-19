---
name: the-submission-is-the-only-artifact-that-scores
description: Use at every stage of a run whose deliverable is a predictions file scored by a fixed metric, and especially when a stage has been running for a while without changing that file. Covers how to tell work that moves the score from work that moves the record, the one measurement that separates them, and what to do when the deliverable has stopped moving.
applies_when: predictions will be scored
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design, 04_implementation, 05_experimentation, 06_analysis
---

# One file is scored. Everything else you produce is overhead you chose

On this kind of task the grader opens exactly one artifact: the predictions file.
No report, no figure, no manifest, no claim, no source entry, and no coverage
table is read by anything that produces a number. That is unusual — most of what
this pipeline is built for is graded on the write-up — and it inverts the normal
allocation of effort.

It is easy to agree with that in principle and violate it for four hours.

## The measurement that catches you

Over nineteen tasks of a scored arm, the median run spent **43% of its tool calls
after the last time it changed the predictions file**, and the median gap between
that last change and the end of the run was **93 minutes of a 240-minute budget**.
On the worst task, 294 of 427 calls came after the deliverable stopped moving:
resolving DOIs for two architectures the run had decided not to build, rewiring
claims to sources, running "a full integrity sweep of all artifacts", and fixing a
stray backtick in a document. Every one of those calls was competent work. None of
it could change the score.

The control arm — the same model, same brief, same clock, no pipeline — went two
minutes between its last submission write and the end of its run, and beat this
arm on 16 of 19 tasks.

## The rule

**Keep the age of the deliverable in front of you, and treat it as the run's
health metric.**

```bash
# how long since the graded artifact last changed
echo "$(( ($(date +%s) - $(stat -c %Y submission.csv)) / 60 )) min"
```

Run it at every stage boundary and after every long-running command. Read the
number as follows:

| age of the submission | what it means |
|---|---|
| under 20 min | you are working on the deliverable |
| 20–45 min | you are between attempts; know what the next write will be |
| over 45 min | you are working on the record; stop and say why that is right |
| over 90 min with budget left | the run has changed jobs without deciding to |

The last row is not a warning to note in a summary. It is an instruction to go
back to the model.

## What still gets produced

This is not licence to skip the stage artifacts. The gates are real, a stage that
does not produce them is refused, and a refused stage costs more budget than the
artifact did. Produce them — at the size the gate accepts, once, and then leave
them alone. The failure mode is not writing them; it is *returning* to them.

Two symptoms that you have returned:

- You are editing a file you already wrote to make it read better. Prose quality
  is worth zero here and the gate does not measure it.
- You are adding evidence for a claim about work you have already finished. The
  claim was accepted when you made it.

## When the deliverable genuinely cannot move

Sometimes it cannot: a training run is in flight, or the next idea needs data you
are still building. That is a legitimate reason for the age to climb, and the
thing to do is make it explicit rather than let it drift:

1. Write down what the next write to the file will be and what has to finish first.
2. Put the long job in the background and keep the foreground on something that
   changes the file — a second model, a blend, a better validation split.
3. If nothing can change the file for the next hour, the honest move is to spend
   that hour on the cheapest thing that might: another method, not another audit.

A run that ends with three hours of impeccable bookkeeping and a submission it
wrote in its first hour has produced one hour of research and called it four.
