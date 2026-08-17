---
name: chemistry-reproduce-the-scoring-path-before-you-replace-it
description: Use at implementation and experimentation when you are reproducing a published benchmark number and the source's scoring path is one you can read — which rows are scored, in what order, how many the loader drops, which epoch is reported, how tasks are pooled, over how many seeds. Covers implementing that path exactly before improving it, the one-row-per-step ladder from the published rule down to your own honest estimate, and why one un-replicated step makes the reproduction gap you report uninterpretable.
applies_when: molecular property prediction
stages: 04_implementation, 05_experimentation, 06_analysis
---

# Implement the scoring rule you intend to condemn

A leaderboard number is not the model's output. It is the output of a *path*: a
split, a subset of its rows, an order, a batch loader that may discard a partial
batch, a checkpoint or an epoch chosen by some rule, an aggregation across tasks or
targets, a statistic across seeds. Every one of those steps is worth points of
metric, and any one of them left out of your re-implementation goes into your
reproduction gap without a label on it.

So enumerate the path before you compute anything. Read it off the source's
training script and methods section and write it down as ordered steps in
`notes/scoring_path.md`: which split, which rows of it, in what order, how many are
dropped, at which epoch, aggregated how, over how many runs. Where the paper and
the code disagree, record both readings as separate steps — that disagreement is a
finding you will want later. Transcribing the caption's protocol is one line of
`rebuild-the-sources-headline-table-row-for-row`'s literature-stage step; this is
what to do with it afterwards.

## Implement every step, including the ones you can see are wrong

The first column of your reproduction table is your model scored through the
source's exact path, standing next to the published value. That column is the only
thing in the report that lets a reader decide whether your re-implementation is the
same model as theirs. Everything else you do — a better estimator, a fairer
aggregation, a validation-selected checkpoint — is measured *from* that column.

The temptation is to skip a step because it is obviously a defect: nobody should
report the maximum over epochs of a test metric, nobody should score a shuffled
loader that drops its last batch, nobody should pool tasks with different base
rates. Skipping it does not produce an honest number; it produces a third number,
neither the source's nor yours, and the gap you then report contains your training,
your featurisation and the step you left out, with nothing separating them. The
defective steps are precisely the ones carrying the deltas, which is why they have
to be implemented before they can be removed.

## Publish the ladder, one row per step

| step removed | BACE | BBBP | ClinTox |
|---|---|---|---|
| source's rule, as published | | | |
| − partial batches dropped from a shuffled scoring loader | | | |
| − maximum over epochs instead of a selected checkpoint | | | |
| − pooled instead of per-task aggregation | | | |
| your honest estimate | | | |

Each row is a delta you measured; the ladder as a whole is the decomposition of the
difference between the published convention and yours. "Their protocol inflates the
number" is an assertion. A ladder is a measurement, and every rung is checkable
against your own run logs. Costing nothing extra: the rungs are re-scorings of
training histories you already have on disk, so build the path as a function over a
saved per-epoch history rather than as a branch inside the training loop, and every
rung is one pass over JSON.

Size each rung against the source's own margin over the comparators it is tabulated
with. A step worth more than that margin is the finding; a step worth a tenth of it
is a footnote. And run the null controls through the same path — an untrained model
and a constant predictor that never looks at the input, scored exactly the way the
source scores a trained one. They cost one forward pass each and they bound what the
path returns for a model that learned nothing.

## Keep both columns to the end

Report the source's convention and yours side by side for every dataset and every
arm, not one in the results and the other in an appendix. And keep the ladder in the
reproduction section: it is a statement about a scoring rule, not about the method,
and a report that opens on it has led with a verdict on somebody's harness — see
`claims-before-harness-forensics` for the ordering, and
`verify-against-the-publication-not-the-authors-code` for why the published value,
not your replay, is the reference in the first column.

## Why this is here

Measured on Chemistry_000 of ResearchClawBench, scored with gpt-5.1 over three
draws: 36.8 for the run under study against 45.0 for bare Claude Code on the same
brief, with the largest-weight criterion — the benchmark comparison table, weight
0.45 — at 27.3 against 30.0.

The run under study did enumerate the source's convention, and led its
reproduction table with "the paper's estimator": maximum test score over epochs,
pooled across tasks. It landed at 0.8345 against a published 0.890 and 0.6773
against 0.787, called the result a partial reproduction, and recorded in its own
limitations that the release's `drop_last` behaviour was not replicated. The
comparator run implemented that step, reported 0.886 ± 0.008 against the same
published 0.890 under the released rule, and then decomposed its own inflation
term by term — the dropped partial batches worth 0.024 on BACE and 0.038 on BBBP,
the maximum over epochs a further 0.035 and 0.056, pooling worth 0.203 on the
two-task set. Same benchmark, same brief: one run reported a reproduction gap it
could not attribute, the other reported the published number and a ladder down
from it.
