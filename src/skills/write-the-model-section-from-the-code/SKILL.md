---
name: write-the-model-section-from-the-code
description: Use at implementation while the model file is still open, and again at writing when the architecture, its training objectives or its hyperparameters are being described. Covers why a library primitive hides the components you are being credited for, and how to write a model section a reader could re-implement from.
stages: 04_implementation, 07_writing
---

# Write the model section with the source file open

The expensive failure here is not building the wrong model. It is building the right one and
describing it in a clause. A methods paragraph that gives the family name plus three
hyperparameters — a category, a width, a depth, a regularisation rate — is a description of a
class of models, not of yours. Everything a reader would check lives in the source file and never
reaches the page: what the layer actually computes, what the readout reduces, the shape of the
head, and the auxiliary machinery of any training phase that is not the final one.

Work that was done and not described scores as work not done, and it is a worse loss than an
experiment you never ran: that one at least cost nothing to omit.

## Library primitives hide the parts you are being graded on

`TransformerEncoderLayer(...)`, `MultiheadAttention(...)`, `GATv2Conv(...)`, `nn.GRU(...)`, a
stock convolution block, a pooling helper — each of these is one line in your code and a page of
computation a reader cannot see. Scaling, normalisation, an internal gate, an internal skip
connection, the aggregation rule and the default activation all live inside an import.

Naming the class is not describing the model. Name the class, the library and the version, then
write out what it computes. For a study whose contribution is an implementation, that is the
highest-value paragraph in the methods section.

## What the Model subsection contains

One subsection under Methods, placed ahead of the validation, null and provenance prose. Walk
your model file top to bottom and emit a line for each thing you find. Read the components off
the code; the list below is where to look, not what to claim.

- **Input featurisation.** What each element of an input is, its dimension, and how a raw record
  becomes it. Dimensions as numbers.
- **The per-layer update, as an equation**, with every term in it: what is aggregated and over
  what, what transforms it, what normalises it, what scales or attenuates it, which nonlinearity,
  and whether the block adds its own input back to its output. For each of those, say whether the
  primitive supplies it or you wrote it: "the stock layer applies X internally, so one block
  computes Y".
- **Depth and width**, and whether weights are shared or tied across layers.
- **The readout.** How a set of per-element representations becomes one vector: which reduction,
  over what, and whether anything is concatenated before the head.
- **The head.** Layer sizes in order, activations, where regularisation sits and at what rate,
  output dimension, and what the output means.

Then one block per training phase — **every** phase, including any pre-training, auxiliary or
representation-learning phase that precedes the one you report:

- the objective, as a formula, and what is masked, corrupted, sampled, paired or reconstructed;
- any auxiliary decoder or projection head, its shape, and whether it is discarded afterwards;
- what is frozen and what is trained;
- optimiser, learning rate, schedule, batch size, number of epochs;
- class weighting, resampling or loss reweighting, with the numbers;
- the split, the model-selection criterion, the number of seeds and what is averaged over them.

A phase with no described objective reads as a phase that did not happen, however much compute it
consumed.

Where you deviated from the method you are reproducing, say so in the same sentence as the
component, with the reason. A named, justified deviation reads as care. An unmentioned one reads
as an error the moment a reader finds it.

## Transcription, not recall

Open the source file and go line by line. Writing this from memory is how the parenthetical
happens: memory returns the category and the hyperparameters, because those are what you typed.

Two reconciliations close it:

- **In the code and not in the section** — a component you built and will not be credited for.
  Add it.
- **In the section and not in the code** — wrong. Delete it, or fix the code.

Then read the subsection as someone with no repository access and ask whether they could
re-implement from it. If you think they could, count the parameters from your own prose and
compare against `sum(p.numel() for p in model.parameters())`. A mismatch means the description is
incomplete somewhere specific, and the arithmetic tells you where.

## A diagram slot is a promise

If you leave a placeholder where a method figure belongs, fill it or delete it. A shipped report
with an unfilled placeholder comment sitting where the architecture figure was planned reads as a
section that was abandoned. Before shipping, grep the report for placeholder markers, `TODO`,
`TBD` and figure references with no file behind them.

The figure itself is cheap: boxes and arrows along the data path — inputs, each block, the
readout, each head — with tensor shapes on the arrows. It answers the same question the equations
answer, faster, and it is a second chance at the same credit.

## Where this sits next to `train-the-named-architecture`

That skill covers building the model the brief names, and its spec section asks for layer count,
width, pooling, dropout, optimiser, learning rate, batch size and epoch count — the model's
*numbers*. A report can supply all of those and still lose the architecture criterion, because
none of them says what the model computes. What is here and not there: unpacking the library
primitive, the update as an equation, the shapes of the readout, head and any auxiliary decoder,
one block per training phase, and the fact that this is writing-stage work done with the source
file open. Read that one at implementation; read this one when the section gets written.

## Checklist

- [ ] The Model subsection was written with the source file open, top to bottom.
- [ ] Every library primitive is named with its library, and what it computes is spelled out.
- [ ] The layer update appears as an equation, with every internal operation of the primitive
      attributed to the primitive.
- [ ] Readout, head shape and regularisation placement are stated, not implied.
- [ ] Every training phase has its own block: objective, auxiliary heads, optimiser, split.
- [ ] Deviations from the reference method are named where the component is described.
- [ ] Parameter count from the prose matches the parameter count from the model.
- [ ] No unfilled placeholder, `TODO` or dangling figure reference survives in the shipped file.
