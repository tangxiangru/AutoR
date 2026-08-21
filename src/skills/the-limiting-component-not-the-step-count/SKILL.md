---
name: the-limiting-component-not-the-step-count
description: Use at implementation and experimentation when a training run is far from the number the source published and the obvious fix is more optimiser steps. Covers decomposing the headline metric to find the component that actually limits it, diffing your loss schedule against the source's training script before diffing step counts, running two cheap optimisation trials against that component, and finishing the training-set-size pilot into a plotted learning curve. Budget arithmetic itself lives in `close-the-gap-to-the-published-number`.
benchmarks: researchclawbench
stages: 04_implementation, 05_experimentation, 06_analysis
---

# Find the component that limits the metric before you buy more steps

## What goes wrong

An arm lands far from the number the source published, and the diagnosis is "not enough compute".
That diagnosis is usually half right and always expensive. Steps are the costliest knob available:
buying them scales the whole model, and the shortfall is very often concentrated in one part of it.

A model trained with a compound objective is not one thing. Each output the loss touches, plus any
auxiliary head and any regulariser, trains at its own rate under one weighted loss, and it is
routine for one of them to sit an order of magnitude from where it needs to be while the others are
fine. The aggregate number hides that, the report quotes the aggregate, and the run spends its whole
budget scaling a model whose bottleneck was a weight in the loss.

The second half of the same failure: a decision rule fires on an arm that never converged. It then
reports the budget, not the method. Record such an arm as undertrained and leave the clause
unresolved.

## 1. Name the limiting component

Before requesting more steps, decompose the headline metric into the quantities the loss actually
optimises and, for each one, write three things down:

| component | current value | target (source's, or the task's own units) | trend over the final third |
|---|---|---|---|

The trend is what makes this actionable. A component that is far from target and still moving is a
schedule problem: it may close with steps, and you can extrapolate how many. A component that is far
from target and flat will not close with steps at all — no multiple of the current budget fixes it —
and the aggregate error is pinned by it. That is the component to work on.

## 2. Diff your loss schedule against the source's, before you diff your step count

If the source released training code, open it and read the parts that are *not* the architecture:

- the relative weights of the loss terms, and whether they are constant for the whole run;
- staged phases — several sequential loops with a weight, a learning rate or a frozen set changing
  between them;
- target normalisation and per-element or per-group offsets, and whether they are learned;
- separate learning rates for particular parameter groups;
- what is held fixed early and released later.

Runs copy the architecture constants out of that file — widths, basis sizes, radii — and leave the
optimisation to their own defaults, then attribute the resulting gap to budget. A single fixed loss
weighting held from the first step to the last, where the source's script runs several phases with
weights that change by orders of magnitude between them, is a *different training procedure*, not a
shorter one, and no number of extra steps converts one into the other.

## 3. Try two changes against the limiting component, and report which moved it

At pilot length, on the pilot arm, change one thing at a time:

- rebalance the loss weights, including staging them so the weighting changes partway through;
- normalise or rescale the target the weak component predicts;
- give that component's parameters their own learning rate;
- change its initialisation scale;
- change what each head is permitted to explain early in training, so a channel that would otherwise
  be ignored has to carry signal.

Two of these, run at pilot cost, are cheaper than one extra full arm. Report the comparison: a small
table of what was changed and what it did to the limiting metric is a result in its own right, and
it is the evidence that the final configuration was chosen rather than inherited.

## 4. Turn the training-set-size pilot into a curve

Almost every run does a two-point data-size sanity check during design and leaves it in a JSON file.
Finish it. On the headline arm, at fixed steps, sweep four or five log-spaced training-set sizes from
the smallest that trains at all to everything you have, and plot every error the study reports
against N on log axes. Overlay the source's curve as thin lines if it published one.

This costs less than one additional arm and pays three times: it separates data-limited from
step-limited for the budget argument, it is directly comparable to a published figure, and any claim
about sample efficiency is read off this panel and nowhere else. Two numbers in an artifact file are
not a learning curve and are not readable as one.

## Budget arithmetic, briefly

Write the source's schedule and yours side by side as a ratio; price the study as steps-to-plateau ×
arms; and when it does not fit, cut seeds, sweep points and secondary arms before cutting the depth
of the headline arm. A matrix of undertrained cells supports no comparison, because the differences
between the cells are dominated by how far each is from convergence. The rest of this argument is
already written: see `close-the-gap-to-the-published-number` §"Spend the budget where the gap is" for
the cheap discriminators and the collapse-to-a-constant check, and `train-the-named-architecture` for
the cut order and the training log. Do not restate them; do the diagnosis above instead.

## Checklist

- [ ] The headline metric is decomposed by component, each with a target and a trend.
- [ ] The limiting component is named before any request for more steps.
- [ ] The source's training script has been read for its loss schedule, not only its architecture
      constants, and the differences are listed.
- [ ] Two optimisation changes were run against the limiting component and their effect reported.
- [ ] A training-set-size curve exists for the headline arm and is plotted, not tabulated.
- [ ] Every unconverged number carries its step count and its fraction of the source's schedule, and
      no verdict is read off one.
