---
name: math-train-distribution-is-a-reporting-axis
description: Use at study design before anything is trained or loaded, and again at analysis and writing, when the method contains a learned component - a released checkpoint you load or a model you train - and the supplied data splits into structurally distinct subsets. Covers the provenance record, labelling every evaluation cell IN/OUT/unknown with a count of distinct structures behind the label, splitting every results object by that label, and the Results paragraph that states the margin on each half.
stages: 03_study_design, 06_analysis, 07_writing
---

# The training distribution is a reporting axis

## What goes wrong

The method has a learned component. There are two ways to lose the same result.

1. **You load a released checkpoint and never establish what it was trained on.** Every
   evaluation subset then reads as equivalent. Whether the method holds up outside the data its
   parameters saw - usually the most interesting thing a learned component can be asked - goes
   unstated, and a reader defaults to assuming everything was in-distribution. Establishing the
   checkpoint's provenance in a methods note is not the same as using it: if the words "trained
   on" never reach the report, the axis does not exist for anyone but you.
2. **You train it yourself on everything you were given.** More expensive, because it destroys a
   split you cannot rebuild without retraining. It is fatal when a subset ships only one
   underlying structure: train on it and the model is evaluated on the instance it trained on,
   and that subset can never serve as a held-out condition again.

Either way the report contains no sentence of the form: *the parameters saw A; on B, which they
did not see, the measured margin against the incumbent is M, over n instances.*

## Study design: a provenance record for the learned component

Before any run:

- Where the parameters came from: release URL and file hash, or your own training script and
  seed.
- Exactly which subsets, which instance or index ranges, and which seed ranges the parameters
  saw. If you did not train it, go and find out: the release README, the source's experimental
  setup section, the training config in the repository, the checkpoint's own metadata. Record
  the file and the line you read it from.
- If it genuinely cannot be established, say so in one line and label every subset `unknown`. Do
  not label subsets in-distribution by silence.

## Study design: label the evaluation cells

Every cell gets `IN`, `OUT` or `unknown`. Then count distinct structures per subset before you
trust a label:

- A subset whose files all replicate one underlying structure, varying only the instance
  seed, is **one structure**, not a family. Its `OUT` label is real but its n of independent
  structures is 1, and the report has to say so.
- "Trained on A, tested on B" is only out-of-distribution if your B instances were not in the
  training draw. Check index and seed ranges, not just subset names.

Write the counts down. They are two lines of code over the shipped files and they change how
every later number reads.

If you are training: hold out every structurally distinct subset, name the held-out list in
writing *before* training starts, and draw training instances from index and seed ranges
disjoint from evaluation. State both ranges in the report. A small self-trained arm restricted to
the IN subsets is also the only thing that answers a criterion about the architecture itself -
see `train-the-named-architecture` - and it can sit beside the released checkpoint rather than
replacing it.

## Budget consequence

If the learned component is the contribution, the OUT cells are the load-bearing evidence for it,
not a robustness appendix. When the budget reaches only some of them, prefer one cell in each OUT
subset over many cells in one. A single point per OUT subset supports the split; ten points in
one OUT subset does not.

## Analysis: split every results object by the label

The per-cell table gets an IN/OUT column. The headline comparison against the incumbent is
computed and reported once for each half, never only pooled. If the margin differs between the
halves, that difference is a first-class result: its own number, its own sentence, and a panel or
facet of the primary figure. A method that holds its margin on OUT cells and one that collapses
there are different methods, and only the split tells you which one you have. Either outcome is a
result; the procedure does not presume which one you will get.

## Writing: one paragraph in Results

In the task's own vocabulary, and in Results rather than Limitations, state: where the parameters
came from; which evaluation subsets are outside that distribution and on what evidence; how many
distinct structures each of those subsets contains; and the measured margin on each half with its
n. Use the field's term for evaluation outside the training distribution rather than inventing
one. Limitations is where a reader looks for what you could not do; this is something you did.

## Checklist

- [ ] Can I name the file and the line that says what the parameters were trained on?
- [ ] Is every evaluation cell labelled IN / OUT / unknown, with the count of distinct structures
      behind each label?
- [ ] Did I measure at least one cell in every OUT subset?
- [ ] Does the primary results table carry the IN/OUT column, and are the two halves aggregated
      separately as well as together?
- [ ] If I trained: is the held-out list written down from before training, and are the training
      and evaluation index and seed ranges disjoint and stated?
- [ ] Does Results contain the paragraph above, or is the training distribution mentioned only in
      Methods - or nowhere?

## Anti-patterns

- Reporting only in-distribution cells and describing the result as if it covered the whole
  supplied dataset.
- Training on every supplied subset because more data is better. It is not, when one of those
  subsets is the only held-out condition you will ever get.
- Inferring the training distribution from the method's name, or from what seems natural. Read it
  out of the release.
- Establishing provenance thoroughly in a stage note and never carrying it into the report. The
  axis exists only where a reader can see it.
