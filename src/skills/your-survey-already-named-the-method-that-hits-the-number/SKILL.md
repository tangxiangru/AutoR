---
name: your-survey-already-named-the-method-that-hits-the-number
description: Use at the end of the literature survey and at the start of study design and implementation, when a published number exists for the dataset and metric you were handed and your own measured number is well short of it. Covers extracting the method family rather than the citation, the ladder that says how far off you are, and the refusal to let the survey's finding stop at the write-up.
applies_when: predictions will be scored
stages: 01_literature_survey, 02_hypothesis_generation, 03_study_design, 04_implementation
---

# The survey found the answer. Check that the implementation heard it

A literature survey on a task like this produces two things. One is a set of
sources and claims the pipeline's gates will ask for. The other is a fact worth
more than all of them: **which family of method produces the numbers the field
reports on this exact dataset and metric.**

The second is the reason to do the survey at all, and it is the one that reliably
fails to arrive at the model.

## How the failure looks from inside

It does not look like ignorance. It looks like this, measured on a scored arm:

- On a molecular-property task, the survey recorded the published ladder for the
  target and metric: **0.021 to 0.029**. The run then built features by hand,
  fitted a gradient-boosted tree, and shipped **0.11** — five times off a number
  it had written down in its first stage.
- On a second task from the same dataset, the run resolved the DOIs for two graph
  network architectures, cited them correctly, and shipped a gradient-boosted
  tree.
- The control arm, which did no survey at all, wrote a graph network and beat both.

Nothing in those runs was dishonest and nothing was refused by a gate. The survey
did its job; the finding just never became an instruction.

## Make the survey produce an instruction

Before the survey stage closes, write down four things — not as prose, as a note
you will re-read at implementation:

1. **The ladder.** The three or four best published numbers for *this dataset and
   this metric*, each with the method family that produced it. Not "the paper is
   good"; the number.
2. **The family**, at the level of a thing you could build: a graph network over
   the molecular graph, a fine-tuned sentence encoder, a gradient-boosted tree on
   engineered features, a retrieval-plus-rerank stack, a seasonal-naive baseline
   with a learned residual.
3. **The floor.** What the simplest defensible method gets. Often in the same
   papers, in their own baseline table.
4. **The gap you are accepting** if you build something other than (2), stated as
   a ratio against (1).

Point 4 is the one that does the work, because it forces the comparison to be
made rather than avoided.

## The rule at implementation

**When your measured validation number is more than about twice the published
ladder away from it, the method is the defect, not the tuning.**

Tuning a family that is a factor of five off will not close a factor of five. The
options at that point are to change family or to write down, with a cost estimate
rather than an impression, why you cannot afford to — see
`a-model-you-can-audit-is-not-a-model-that-scores` for how to price that decision.

What is not an option is to keep tuning and let the survey's own ladder sit
unmentioned in the notes. If your run holds a number the field beats by 5x and
your remaining plan is a hyperparameter sweep, the plan is wrong.

## When the ladder is out of reach

It often is: the published number may come from a model pre-trained on more data
than you were given, or from days of compute. That is a real finding and it should
be stated with the ratio attached. State it in the terms the ladder is in — "the
published 0.021 comes from a graph network trained for N GPU-hours; the budget
here is four CPU-hours, and the best I can reach in that is X" — and then spend
what is left going after X rather than polishing something well below it.
