---
name: chemistry-ablations-and-curves-without-an-accelerator
description: Use at study design after you have priced a scaled-down training arm and found the machine cannot carry it — no accelerator visible, or no wall clock for one arm. Covers the one-row-per-named-component table with the inference switch that removes each part, why an input ablation does not answer a component criterion, and the ladder of curves that still ships when nothing can be trained.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Ablations and curves when the sandbox has no accelerator

**Price the training arm first.** `train-the-named-architecture` is the primary
instruction: when the brief names an architecture, a small honest re-implementation
trained at whatever scale you can afford answers every architecture-shaped criterion.
So before this skill applies, measure the machine — device query, cores, RAM, wall
clock left — and price one scaled-down training arm against it, in writing. What
follows sits **on top of** that arm wherever it is affordable, and replaces it only
where there is genuinely no accelerator and no time.

## What goes wrong

The task names an architecture by its parts. The run uses a released implementation,
decides that removing a part means retraining, prices retraining, finds it
unaffordable, and records the ablation as *not attempted*. The report then describes
the parts in prose and labels the description as not a measurement made in this run.
Nothing in the run varies the thing the task is about, and every prediction it makes
is made at one identical configuration.

Two habits make the omission permanent:

- **The ablation serves no hypothesis, so the descope ladder cuts it first.** Arms
  that buy breadth across targets survive; the one arm that would show which part
  carries the result is the cheapest thing to drop and the first thing dropped.
- **A slot is refused because it has no content yet.** Declining to reserve a table
  row or a figure slot for an arm you have not run guarantees the arm is never run,
  because nothing downstream is missing it.

## One row per named component, switch or no switch

Take the component list from the nouns in the brief's architecture sentence and from
the reference method's own block diagram. Every one gets a row, written before
anything runs:

| component | switch available at inference | what the arm is no longer | if no switch: price of the real arm |

A component with no inference switch does not fall off the table. Its row reads "no
switch exposed; the only arm is a trained control, priced at N accelerator-hours" —
that sentence is the deliverable for that component, and it is worth much more than
silence.

Switch shapes present in most released implementations:

| component shape | the switch | what the arm is no longer |
|---|---|---|
| iterative sampler or denoiser | step count to its minimum | an iterative process; it is single-shot |
| recycling or refinement loop | iterations to zero | iteratively refined; it is one forward pass |
| submodule behind a config flag | switch it off | using that submodule |
| learned head or scorer | replace with the trivial predictor it was introduced to beat | learned at that stage |
| ensemble or multi-sample selection | one sample, fixed seed | a selection over candidates |
| internal data-dependent feature | shuffle or randomise it, keeping shapes | using the information in that feature |

Write the third column **before** you run the arm. That sentence is what makes the
run an ablation of a named component rather than a hyper-parameter change, and it is
the claim the report will make.

**Removing an input is a different experiment.** Withholding an alignment, a
template, a conformer, a charge set or an auxiliary channel is an *input* ablation.
It is worth running and worth reporting, and it does **not** answer a criterion about
a component — `train-the-named-architecture` is explicit on this point. Give it its
own row, labelled as an input ablation, and do not let it stand in for a component
row.

**Say what the proxy cannot show.** A sampler turned down to its minimum step count
tests the module's use at inference, not its contribution during training. One honest
sentence on the row; a measured row with a stated limit beats an absent row.

## Budget rule

Reserve one arm per named component before buying any breadth in the main panel. All
the components on a fixed subset of a handful of targets is almost always cheaper
than one more stratum, and it is the difference between a report that measures the
architecture and one that measures a dataset. Run every ablated arm on exactly the
targets the full arm ran, so the deltas are paired. If the plan has a descope ladder,
the component arms sit above the breadth arms on it and the plan says why.

Report the arms in the shape `math-equal-effort-baselines-and-knob-sweeps` already
specifies — degradation ranked, quality paired with cost. Add one thing to it: a
geometric or validity statistic beside the accuracy (extent, spread, output norm,
validity rate). A collapsed, averaged or truncated output can score well on a
permissive metric, and a degenerate arm that wins is worse than no arm at all.

## At least one curve ships

A learned or iterative model is expected to be shown against its own counter, and "no
accelerator" does not discharge that. Work down this ladder, shipping the first rung
you can reach and any further rung that is cheap:

1. **A toy training run on the hardware you actually have.** Loss and one validation
   metric against step, appended inside the loop, every arm overlaid on one axis. A
   curve from a model small enough to train in twenty minutes on the CPU you were
   given is strictly better evidence than no curve, and the overlay doubles as the
   ablation figure.
2. **An inference-counter sweep.** Sweep each exposed counter — denoising steps,
   refinement iterations, samples, seeds — on a fixed subset with everything else
   held constant, and plot the metric *and* the wall clock against the counter. Mark
   the setting the main results used and say whether it sits before, at or past the
   knee. Flat or non-monotone is itself a finding: it says the limit is the learned
   map, not the sampler. Usually minutes per point.
3. **A single-step corruption curve**, wherever the model exposes one denoise or
   refinement call: corrupt the reference at a known level, apply one step, plot
   recovered accuracy against corruption level. It separates a bad objective from a
   bad trajectory.
4. **Accuracy against the number of samples drawn**, best-of-N beside a selection
   rule that does not peek at the answer. Every generative model has this one.

At least one of the four ships as a figure. A sentence explaining the absent curve,
placed where the curve would have gone, is the outcome this ladder exists to prevent.

## Checklist

- [ ] The scaled-down training arm was priced first against a measured device and
      time budget, and the price is in the report.
- [ ] Every named component has a row, including the ones with no inference switch.
- [ ] Each arm carries its "what it is no longer" sentence, written before it ran.
- [ ] Input ablations are labelled as such and do not occupy a component's row.
- [ ] Ablated arms ran on exactly the targets the full arm ran; deltas are paired.
- [ ] A validity or geometry statistic sits beside the metric on every arm.
- [ ] At least one counter curve ships as a figure, with cost on the same plot.
- [ ] Empty rows carry a price and a reason, never a blank.
