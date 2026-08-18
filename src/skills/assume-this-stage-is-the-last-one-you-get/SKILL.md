---
name: assume-this-stage-is-the-last-one-you-get
description: Use at the first three stages of a run under a hard wall clock, when the plan defers the modelling to a later stage. Covers the measured probability that the later stages never execute, why deferring to the stage designed for the work is the most expensive available choice, and what each early stage should leave behind if it turns out to be the last one to run.
applies_when: predictions will be scored
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design, 04_implementation
---

# Plan as if the experimentation stage will not happen, because usually it does not

The pipeline has a stage for running experiments and a stage for analysing them.
On a wall-clocked run they are frequently theoretical.

Measured over a nineteen-task scored arm, with a four-hour cap per task:

| final stage the run reached | runs |
|---|---|
| 01 literature survey | 6 |
| 02 hypothesis generation | 3 |
| 03 study design | 5 |
| 04 implementation | 4 |
| 06 analysis | 1 |

**Nineteen of nineteen hit the cap. None finished the walk.** Six never left the
first stage; four of those six spent between 13 and 22 attempts on it. So the
predictions file that got scored was, on most tasks, whatever an early stage
happened to produce on the way past.

That is the environment. Planning as though stage five will arrive is planning
for a stage that arrives about one time in twenty.

## What follows

**Do the modelling in the stage you are in.** Not because the stage boundaries are
wrong, but because a plan whose payoff is two stages away has a low probability of
being executed, and a marginally worse model built now has a probability of one.

Concretely, at each early stage:

- **01, literature survey.** Alongside the sources, run the data loader, print the
  shapes, and write the trivial baseline submission. The survey is better for it —
  you now know what the columns actually contain — and if the run ends here, it
  ends with a valid file.
- **02, hypotheses.** Every hypothesis you register should be one you could test
  with a script you could write this hour. A hypothesis whose test needs
  infrastructure you have not built is a hypothesis that will be adjudicated by
  the clock.
- **03, study design.** Design the experiment you will run *first*, not the full
  grid. Then run it. A designed-and-unrun grid scores the same as no grid.
- **04, implementation.** The thing you implement should end by writing a
  submission, every time. "Implemented, not yet run" is the most common way this
  arm ended.

## Leave the run resumable at every boundary

Because you do not know which stage is the last one, each should leave the next
one able to start in five minutes rather than thirty:

- the current submission, valid
- its validation score, in a file, next to it
- the single script that regenerates it end to end
- one line saying what the next thing to try is

That is a smaller handoff than the pipeline's own artifacts and it is the one that
determines whether the following stage does research or does reconstruction.

## The stage budget is not yours to spend evenly

If the cap is four hours and there are six stages, the arithmetic that gives each
stage forty minutes is wrong, because the last three stages have a low chance of
running at all. Weight the front: the first two stages should end with a model, and
the later ones should improve it if they arrive. A run that is refused at stage one
three times has spent its budget on the stage with the least leverage over the
score.
