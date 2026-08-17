---
name: train-the-named-architecture
description: Use at study design, implementation and experimentation when the brief's deliverable is a model you have to build — it names an architecture family (graph network, autoencoder, diffusion module, surrogate net) or a training regime (pre-training, fine-tuning, self-supervised, inverse design). Covers why a cheaper model class scores near zero however well it performs, why a scaled-down run of the named architecture beats a released checkpoint on every architecture criterion, and what to ablate.
applies_when: \b(pre-?train\w*|fine-?tun\w*|deep[- ]learning|neural[- ]network|auto-?encoder|inverse[- ]design|diffusion[- ]based|self-supervised|foundation model|generative model|surrogate model|meta-?model)\b
stages: 03_study_design, 04_implementation, 05_experimentation
---

# When the brief names an architecture, the model is a deliverable, not a line in the cut order

The reasoning that loses this is good reasoning. Building the named architecture
from scratch is expensive; a cheaper model class will reach a better number on the
supplied data; a released checkpoint will reach the published number exactly. All
three are true, and all three lose, because a brief that names an architecture is
graded on the architecture: its components, its training dynamics, its ablations.
Those questions have no answer that a different model can give.

So: **if the budget will not carry everything, cut seeds, cut substrates, cut your
own extension. Never cut the model the brief names.**

## A scale model beats a correct number from something else

The trade that looks obvious — "a from-scratch version at this budget would be far
worse than the published one, so it cannot win" — is a prediction, and it is
usually wrong about what is being graded. A small, honest re-implementation that
keeps the named components and trains for a fraction of the source's budget
answers every architecture-shaped criterion. A number obtained from something else
answers none of them, however good the number is.

Budget one small training arm before you budget a second inference sweep.

## Do both, when a release exists

A released checkpoint and a small re-implementation answer different questions,
and a task that names an architecture usually asks both:

| the criterion says | what answers it |
|---|---|
| accuracy, success rate, benchmark score | the released code, run as published |
| architecture, components, convergence, ablation, training | your own trained re-implementation, at whatever scale you can afford |

This is the one place to override the usual advice to install and run the
authors' release rather than reimplement it. Run the release *and* build the
scale model; they are not alternatives here.

## Take the ablation list from the nouns in the brief's architecture sentence

If the brief says "a graph encoder with gated convolutions, a self-supervised
decoder and a classifier head", the ablations are: remove the gating, remove the
decoder, replace the head. Removing an *input* — a feature, a modality, a
conditioning signal — is a different experiment, and it does not answer a
component question. Match each ablation against a parameter-matched control so the
delta is about the component and not about capacity.

## Persist the training log from the first loop

Inside the training loop, before anything else changes, append
`(step, train_loss, val_loss, val_metric)` to a result file — for **every** arm,
including the subordinate ones you do not expect to report. A convergence curve is
one of the most frequently graded artifacts of a model-building task and one of
the easiest to lose: the numbers exist in memory for the length of the run and
then do not exist at all. There is nothing to recover at writing time.

Then, before the analysis stage: grep your own figure captions for an epoch axis.
If the brief named an architecture and no figure has one, go back to
experimentation rather than forward to writing.

## Write the spec at the level the brief does

A criterion about architecture is a paragraph about layers, and it is answered by
a paragraph about layers, **in the report body**: layer count, width, pooling,
dropout, optimiser, learning rate, batch size, epoch count. "A graph network
pre-trained with masked reconstruction" is a description of a category. A config
file in `code/` is not in the report.

## Degenerate input data does not excuse skipping the run

You will sometimes prove the supplied file is trivial — a closed-form function of
its own index, a leak, a surrogate. Audit it, in its own section. Then train the
named model on it anyway and report what happened, because the architecture
criteria are still there and they are still graded. Switching to a model class the
brief did not name, on the grounds that the data does not deserve the named one,
scores worse than training the named one on bad data.

## State the budget and keep the comparison

"This is a statement about a 3,400-step budget, not about the architecture in the
limit" costs nothing and protects everything. An honest scale disclaimer next to a
real comparison is worth far more than a missing arm.

See also `run-the-conditions-the-source-ran` for the experiment list this model
has to be run through, and `publish-what-the-run-already-computed` for the sweep
that catches a training log you kept and did not plot.
