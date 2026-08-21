---
name: material-power-the-contrast-you-invented
description: Use at hypothesis generation and study design when a contrast of your own design is about to define the observable, the plotted series or the framing of an experiment the task named, and again at writing when figures, sections and captions are being titled. Covers the pre-funding power check against the within-condition spread, and the slots a self-generated hypothesis may not occupy.
benchmarks: researchclawbench
stages: 02_hypothesis_generation, 03_study_design, 07_writing
---

# Power the contrast you invented, and keep it out of the named experiment's slot

A hypothesis you wrote yourself is allowed to be sharper, better controlled and
more interesting than the experiment the task named. It is not allowed to supply
that experiment's observable, its plotted series, its axis range or its title.

This extends `cover-what-the-task-named` (which gets the named experiment run)
and `material-as-specified-run-and-stage-diagnostics` (which keeps an audit of a
defective spec out of panel (a)). The case here is different and less obvious:
nothing is broken and nothing is skipped. A self-generated contrast quietly
becomes the thing the named experiment reports.

## How it happens

The task names an experiment of the form *does this artifact reproduce
<external reference> on <system>*. At hypothesis generation you write something
better posed: a contrast between two conditions you control — two cell sizes,
two densities, two preprocessing variants, with and without a correction. It is
internally controlled and genuinely falsifiable, which is why it wins the slot.
From then on it supplies, without anyone deciding to let it:

- **the observable** — the reported quantity becomes a ratio or difference
  between your two conditions instead of the agreement with the reference;
- **the plotted series** — the figure shows condition A and condition B, both
  yours, and the external reference survives as a vertical line, a floating
  marker, or nothing;
- **the axis range** — the range is whatever your control condition supports,
  not the range over which the reference is defined;
- **the title, the caption headline and the section heading** — all three become
  your hypothesis's identifier and its verdict;
- **the framing** — the named experiment is delivered as an inconclusive result
  about a question nobody asked.

The last step is the giveaway. A contrast designed as a control is usually
underpowered as a measurement: two conditions, two seeds, an effect smaller than
the seed-to-seed spread. So the slot ends up occupied by a non-verdict.

## Power it before you fund it

Every two-condition contrast of your own design gets this check before it enters
the design. It costs one smoke run.

1. Measure the within-condition spread of the observable across seeds — or
   restarts, shuffles, replicates, whatever the run's own randomness is — at the
   smallest size you would actually ship.
2. State the effect you expect, in the same unit.
3. If the expected effect is smaller than roughly twice that spread, the
   contrast cannot be resolved at that n. Raise n until it can, or demote it to
   a stated limitation. Running it anyway and reporting the non-verdict spends
   the compute and buys a sentence saying you learned nothing.
4. Write both numbers into the design document. If you catch yourself printing
   the effect-to-spread ratio in your own caption as an explanation of why the
   result is inconclusive, the check was not skipped by accident — the answer
   was available before the run and was not acted on.

The same check applies to any comparison whose point is to separate two
candidate values: the interval you can buy must be narrower than the gap you
intend to claim. Write that clause per deliverable before running, in the form
*to separate A from B I need an interval narrower than |A − B|*.

## Slot rules

A hypothesis you generated may not take, for an experiment the task named:

- **the figure's subject or title.** The figure is about the named comparison.
- **both plotted series.** One series is your result, one is the reference the
  task named. Your second condition is a third series or its own figure.
- **the axis range.** Set it by the range the reference spans, at the resolution
  the comparison needs. A range truncated by a geometric limit of your own extra
  condition removes part of the named result.
- **the caption's first clause.**
- **the section heading.** Sections are headed by the named experiment and the
  system it ran on. A heading of the form *H4, inconclusive* names your
  bookkeeping, not a result.
- **the abstract's first result sentence.**

## Say what the named experiment showed

Before any verdict on your own hypotheses, the named experiment's paragraph
answers the task's question in the task's own terms, positively: what was run,
on what system, at what configuration, against which external reference, whether
they agree and by how much, and what capability that demonstrates about the
artifact under test. That last clause is a sentence, and it is the one most often
missing from a run that is otherwise correct — an inventory of hypothesis
verdicts leaves the reader to infer the claim the study was for.

"Inconclusive" is a fact about your design, not a finding about the artifact.

## Checklist

- [ ] Every experiment the task named is stated as a one-line question that
      contains an external reference, before any hypothesis is written.
- [ ] Each self-generated contrast has a measured within-condition spread and an
      expected effect recorded beside it.
- [ ] No contrast whose expected effect is under ~2× the spread was funded.
- [ ] For each named experiment: one series is the reference; the axis range is
      the reference's.
- [ ] No figure title, caption headline or section heading is a hypothesis id or
      a verdict word.
- [ ] The abstract's first result sentence is about a named experiment.
- [ ] Each named experiment has a sentence stating what its result demonstrates
      about the artifact, in the terms the task's goal is written in.
