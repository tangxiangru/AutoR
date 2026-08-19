---
name: a-ceiling-is-not-a-null
description: Use at study design when choosing instance difficulty, and again at analysis before reporting that an effect is absent. Covers how to tell "the effect is not there" from "my instances cannot show it", the pilot that separates them, and what to write when the ceiling is real and time is gone.
stages: 03_study_design, 05_experimentation, 06_analysis
applies_when: accuracy|error rate|performance|compare|comparison|contrast|effect|degrad|sensitiv|robust|bias
---

# An arm that scores at the top of the scale has measured your instances, not the effect.

A study that generates its own problems chooses their difficulty, and that choice
decides in advance which effects it can see. If the strong arm answers everything
correctly, every condition is 1.000, every difference is 0.000, and the analysis
that follows is arithmetically sound and about nothing.

The result reads exactly like a null. It has the shape of a finding — conditions
compared, spread reported, difference within noise — and nothing downstream can
tell it from one.

## The failure this prevents

Measured on one task of a rediscovery benchmark, by a pipeline that did the
methodology well:

> 112 generated problems × 9 orderings × 2 models, 694 billed calls per arm, a
> corrupted-premise control at 0.15 accuracy confirming the items were real, CI95
> on every cell, a pre-registration, and a `published` vs `ours` table whose own
> rules forbade reporting the recalled column as measured.

Its strong model scored **1.000 in every one of the nine conditions**. The run
noticed — it wrote "the stronger model is at ceiling rather than demonstrably
invariant" — and then concluded that the manipulation did not move accuracy.

A second run, on the same question with a fifth of the wall clock, ran a small
pilot, saw the same ceiling, **generated a harder pool** (longer chains, more
premises), and found the effect at sign-test p = 0.0001.

The difference between them was not rigour and was not time. It was one pass back
to instance difficulty after the pilot said the instrument was saturated.

## The test

Before any conditions are compared, ask of the *baseline* condition alone:

1. **Is the strongest arm below ceiling?** If its accuracy is at or near the top of
   the scale, the design cannot show a decrease. Nothing measured afterwards will.
2. **Is the weakest arm above floor?** The same failure upside down: at chance, no
   manipulation can show a further drop.
3. **Does a deliberately corrupted item score badly?** If a broken item still
   scores well, the scorer, not the model, is answering.

Run this as a **pilot of tens of items, not hundreds** — it is a property of the
design, and paying for the full grid before checking it buys a precise number for
a question the instances cannot answer.

## What to do when it is saturated

Escalate difficulty along the axis the question is about, not a random one: longer
inputs, more steps, more distractors, more compositional depth. Re-pilot. Only
commit the full budget once both arms are off their limits.

## What to write when the ceiling survives

Do not report a null. A null claims the effect is absent; what you have is that
**your instances could not have shown it**. Those are different statements and only
one of them is true. Say which conditions were saturated, say what difficulty range
was reachable, and state the finding as bounded by the range you tested — or report
the arm that was *not* saturated and say the other was out of range.

An honest "not measurable on these items" is worth more than a null that is
indistinguishable from a real one, because the null will be read as the answer.
