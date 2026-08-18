---
name: the-row-count-comes-from-the-split-not-the-brief
description: Use at implementation and experimentation, and again before any stage that writes the predictions file, whenever the task statement states a submission shape. Covers why the stated shape is a claim rather than a measurement, the one line that settles it, and the invariant to attach to every write.
applies_when: predictions will be scored
stages: 03_study_design, 04_implementation, 05_experimentation
---

# The brief states the shape. The split decides it. They disagree

An evaluator that reads your predictions with `read_csv(header=0)` and compares
the row count against its own labels refuses a mismatch outright. There is no
partial credit for 99% of the rows, and the refusal looks identical to having
produced nothing.

So the row count is not a detail to get right at the end. It is an invariant to
attach to the file the first time you write it.

## Both numbers are in front of you and one of them is wrong

The task statement tells you the shape. It is derived from the benchmark's own
metadata, and on at least one shipped task both are wrong: the description says
the submission should be of shape `(1531, 1)`, the metadata says `shape: [1531]`,
and the data the task hands you is a **1,267**-row split — which is what its
evaluator counts. An agent that believes the description scores zero on a task it
solved.

The prepared split is not a hint you are not entitled to. It is one line inside
the directory you were given:

```python
from datasets import load_from_disk
n = len(load_from_disk('./data/test'))
```

**That number wins over every statement of it, including the task's own.** When
they disagree, note the disagreement and use the split.

## Make it an invariant, not a step

A check you run once is a check you ran before the last three edits. Put it in a
function the writer calls, so an invalid file cannot be left on disk:

```python
def write_submission(values, path='submission.csv', header='prediction'):
    n = len(load_from_disk('./data/test'))
    values = list(values)
    assert len(values) == n, f'{len(values)} predictions, split has {n}'
    ...  # write only after the assertion
```

Failing the write is the point. A run that raises here has a valid file from ten
minutes ago; a run that writes anyway has nothing.

## The four ways the count drifts

Each of these has produced a refused submission, and none of them looks like a bug
at the moment it happens:

- **A filter that was meant for training.** Dropping malformed or out-of-range
  rows is correct on the training split and fatal on the test split.
- **A groupby or a merge that loses a key.** Any row whose key is absent from the
  right-hand table disappears silently. Merge with an explicit `how='left'` and
  assert the length afterwards.
- **A batched inference loop that drops the last partial batch.** `drop_last=True`
  is a training default and it silently truncates predictions.
- **A dedupe.** The test split is allowed to contain duplicate inputs and it
  expects one prediction for each occurrence, in order.

Order matters as much as count and is not checked by the row assertion. If any
step of your pipeline sorts, shuffles or groups, carry the original index through
it and restore that order before writing.

## Before the run ends

Read the file back the way the evaluator does — not the way you wrote it — and
check the count, the header, and that nothing is null or infinite:

```python
import pandas as pd
df = pd.read_csv('submission.csv', header=0)
preds = df.values.squeeze()
assert preds.shape[0] == len(load_from_disk('./data/test'))
assert pd.notna(df.values).all()
```

Round-tripping through the reader catches the class of failure that inspecting
your in-memory array cannot: a quoting problem, a stray index column, a header
you wrote twice.
