---
name: material-the-command-timeout-is-not-the-training-budget
description: Use at study design when a training arm is costed against a per-command or per-stage time limit, at implementation when the training script is written, and at experimentation whenever a generative or surrogate metric comes back far below the published one. Covers checkpoint-and-resume so training accumulates across invocations, reading a metric off its curve rather than its endpoint, and asserting the denominator before any threshold is allowed to fire.
benchmarks: researchclawbench
applies_when: \bvitrimer\w*\b
stages: 03_study_design, 04_implementation, 05_experimentation
---

# The command timeout is not the model's training budget

A harness that kills a command after N seconds has told you how long one invocation may run. It has not told you how long you may train. The two get confused quietly: you size a single training call to fit inside the limit, the call succeeds, the model is undertrained, and every number downstream is a statement about the harness. The give-away is a training run that happened exactly once, for almost exactly the cap.

Write the training script resumable from its first line. Checkpoint at the end of every epoch — weights, optimiser state, RNG state, and a cumulative counter of steps, epochs, examples presented and seconds carried *inside the checkpoint file* rather than inferred from a log. On entry, load the newest checkpoint and continue from it. Then invoke it as many times as the stage allows, and report the accumulated totals against the source's: examples presented, epochs, wall clock. Two hours of training delivered as six twenty-minute calls is the same two hours, and it is available under any per-command limit.

Cost the arm the same way. A feasibility table that prices "one epoch" against "the stage timeout" is asking the wrong question; price the epoch, then say how many invocations the run can afford and what epoch count that buys.

## Read the metric off the curve, not off the endpoint

Evaluate the metrics that matter at every checkpoint — reconstruction, sample validity, held-out error — and append them to a file as you go. Then no statement about the model is ever made from a single point. If the last two evaluations are still improving, the endpoint is a lower bound and is reported as one: "0.5 % at 3 epochs and still rising" is a different claim from "0.5 %", and only the first is true.

Generative metrics in particular are steep in the training budget and nearly worthless at the start of the curve. Before concluding anything from a low validity or reconstruction figure, plot it against epochs and look at the slope. If your report contains both the sentence "the loss was still falling when the cap bound" and a verdict phrased as a property of the architecture, one of them is wrong, and it is the verdict.

## A threshold is decided by the smallest denominator it was evaluated at

A rule of the form "at least K of N samples" has to be evaluated at N. If a time cap inside the evaluation truncates sampling to fewer than N draws, and the code requires `n_drawn >= N` before it will report the favourable branch, then the cap has decided the branch and the model was never asked. This is invisible in the result: the artifact records a verdict, not the denominator it was reached at.

So assert the denominator. Every quantity a decision rule reads carries the n it was computed over, and the rule refuses to evaluate when that n is smaller than the one it names. When a truncation is discovered after the fact, repair it forward-only — re-run the evaluation at the declared denominator against the same frozen checkpoint, no retraining — and let the verdict stand only on the repaired number.

## Why this is here

Measured on Material_003. The run's graph VAE trained for **1,201.8 s, 912 batches, 3 completed epochs, in a single invocation with no epoch accumulation across attempts**, against a 1,200 s cap chosen to fit the `--stage-timeout 1800` on the run's own command line; the design describes the checkpointing as resumable and it was never resumed. The whole run lasted 42,864 s, so the model the brief names got **2.8 %** of the clock. Its own figure caption records the training loss "still falling when the 1,200 s cap binds, so the shortfall is affordability, not architecture" — while the experimentation summary adjudicating the same run's 0.5 % decode validity records that the branch "stands - now as a statement about the model". The evaluation had also been truncated: 700 of a declared 1,000 samples drawn under an 80 s cap, while the code sets the favourable branch only when `n_drawn >= 1000`, so, in the run's own words, "branch A was unreachable by construction". A bare agent on the same task finished in 12,172 s and spent 2,901.3 s of epoch time on its main model alone — 23.8 % of its clock, 12 unsupervised and 18 joint epochs — climbing from 15.8 % to 85.9 % reconstruction and 59.3 % sample validity. The criterion resting on the generative arm scored **3.3** against **43.3**.
