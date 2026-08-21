---
name: the-process-deliverable-is-the-labelled-state-at-every-step
description: Use at study design, experimentation and analysis when an asked-for output is a process — growth, assembly, a transformation, a pathway — and the theory assigns a discrete label to the system. Covers recording that label at every step, running one condition per named starting configuration plus a zero-driver null, and publishing the transition census against the quantity that drives it.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 06_analysis
---

# When the output is a process, the deliverable is the labelled state at every step

Briefs ask for "the pathway the system follows", "the sequence of states a
growth run produces", "the transformation route", "the trajectory". If the theory
under test assigns a *discrete label* to the system — a class, a phase, a motif,
a morphology, a regime — then what is being asked for is that label as a function
of step, together with the events where it changes and the quantity that drove
each change. Not the label at the end.

`physics-two-estimators-propagation-and-a-forward-model` compresses this into one
clause: plot the process itself, with the state label on it, plus the event-type
statistics. That clause fails silently, because by the time anyone reads it at
analysis the per-step state has already been thrown away. This skill is the three
things that have to exist before analysis can act on it: the state variable
declared at design, the step record written while the loop runs, the conditions
list that makes a census mean anything. It is the categorical-state analogue of
`the-canonical-figure`'s rule that a trace has to be written down while it
exists.

## What goes wrong

A run designs the ensemble properly: right initial configuration, right
interaction model, one increment at a time, tens of independent trajectories,
checkpointed and cheap to extend. Per trajectory it records how many increments
were added, a geometric deviation, a categorical outcome flag, whether the run
completed, the final energy. Every field is a terminal scalar. The label of the
growing region at increment 1, at increment 20, at increment 50 was never written
down — although it was computed at every increment and discarded — so the
sentence "the state changed here, at this driver value" cannot be written and the
panel showing it cannot be drawn. The ensemble is then reported as a success
fraction with a confidence interval: a measurement of the simulator's
reliability, standing where the phenomenon should be.

A second shape, always in the same run: only one starting condition is ever
simulated, because the run's hypothesis only needed one. The conditions that
would make a census mean something — a second driver value, and the zero-driver
control — are enumerated in the theory section and never executed. Nothing about
this is a budget failure. The trajectories are cheap relative to what was already
spent, and the state was computed anyway.

## What to produce

**Stage 03 — declare the state machine before running anything.** In
`notes/process_protocol.json`:

- `state_variable`: the label the theory assigns, and its admissible values.
- `step_index`: what one step is — one added particle, one added layer, one
  cycle, one round.
- `driver`: the scalar the theory says decides whether the state changes.
- `thresholds`: the predicted driver value for each transition type, computed
  from your own closed form, one number per transition type, written down before
  any run.
- `conditions`: one row per starting configuration named anywhere in the brief,
  the source, or the supplied data, **plus a null condition where the driver is
  zero**. The null is what makes a census interpretable; without it a percentage
  has nothing to be a percentage against. A second driver value is what turns two
  censuses into a comparison.

**Stage 05 — emit the step record.** One file per condition,
`results/<condition>_steps.csv`, columns: `step`, `state_before`, `state_after`,
`changed`, `transition_type`, `driver`, `predicted_threshold`, `agrees`. This
costs nothing: it is state the loop already computes. If the loop does not
compute it, the classifier that assigns the final label is the same function
called every step. Write the file inside the loop, not from a summary at the end.

**Stage 06 — the census, the events, the panels.**

- Census per condition: count and fraction of each transition type, with N. Give
  the null condition its own row; it is the claim about what the system does when
  nothing is driving a change.
- Events, each named individually in prose: at which step, from which state to
  which state, at what driver value, against which predicted threshold, in how
  many of the trajectories, and whether the sign of the effect is the one the
  theory predicts.
- Across conditions: moving the driver should move the census in a stated
  direction. Write that as one difference, not as two paragraphs the reader has
  to subtract.
- Three panels, drawn from those files: (1) state against step, categorical
  y-axis with the label names printed on it, one line per condition; (2) driver
  against step, with each predicted threshold as a labelled horizontal line
  carrying its value; (3) transition-type census as grouped bars, one group per
  condition.

## What does not count

- A success/failure rate over trajectories. That is instrument reliability.
- Energy against increments added. That is a convergence diagnostic.
- A scorecard of how often a rule predicted the right *final* state. That
  measures the rule; the requirement is the process.
- A histogram of the margin by which a categorical outcome was assigned. That is
  the classifier's confidence, not the system's behaviour.
- The enumeration of admissible paths taken from the theory. That is the state
  machine, not a run of it.

## Before you finish

- Every condition in `process_protocol.json` has a steps CSV.
- The null condition ran.
- Each transition type in the census is attached to at least one sentence naming
  a concrete event with its step index.
- From one figure alone, a reader can name which state the system was in at any
  step of any condition.
