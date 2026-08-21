---
name: the-verdict-belongs-to-the-corrected-run
description: Use at the hypothesis freeze, and again at analysis and writing, when a measurement already on disk turns out to have been taken with the wrong flag, the wrong input or the wrong configuration. Covers what a frozen commitment may and may not cover, why re-running a mis-invoked command is a bug fix rather than a post-hoc analysis, and how to record the correction so the reader takes the corrected number and not the broken one.
benchmarks: researchclawbench
stages: 02_hypothesis_generation, 06_analysis, 07_writing
applies_when: ultra-?fast and sensitive
---

# Freeze the decision rule. Never freeze the command line.

Committing to predictions, thresholds, populations and estimators before you see
a result is what stops you choosing the analysis after you know the answer. It
is worth doing and it is cheap. It gives you no protection at all against having
run the wrong command, and — this is the part that costs — it confers no
authority on a number produced by one.

So separate the two artifacts and treat them differently.

**The commitment** holds what would count as support and what would count as
refutation: the prediction, the threshold, the population, the estimator, the
tie-break. Freeze it, hash it, do not touch it.

**The configuration** holds the invocations: binaries, flags, thread counts,
input paths, output formats. It is going to be wrong at least once, because a
methods paragraph is easy to under-read and defaults are easy to inherit. Keep
it in a file that is *expected* to change, with one line per change saying what
moved and why. Freezing it does not make a measurement more credible; it
converts a bug into a commitment and then argues for keeping it.

## When you find the mis-invocation

Re-run. The corrected number is the verdict. Nothing about the rule moved, so
nothing post-hoc has happened: post-hoc is choosing the criterion after seeing
the outcome, and you did not go near the criterion. Write the plain sentence —
*"the first search omitted the flag the source's methods specifies; corrected
here; the decision rule is unchanged"* — and carry on.

What must not survive into the document is the old number in a position of
authority. Check four places by name: the abstract, the section heading, the
figure title, and the summary or verdict table. A verdict row reading
*"inconclusive — zero hits"* sitting a page away from a paragraph reading *"with
the documented flag, five hits, exactly the ones the source names"* does not
present two views for the reader to weigh. It tells them the run's own summary
of itself is the first one.

The broken run is not deleted and it is not hidden. It goes in a correction
table at the back: what was wrong, how it was found, what changed, and how far
the number moved. That table is the honest artifact, and it costs a reader
nothing because they meet the right number first.

## The scope test, applied when you freeze

For every line you are about to freeze, ask: *could this line be wrong in a way
that re-reading the tool's documentation would catch?* If yes, it is
configuration, not commitment, and freezing it buys nothing. Prediction,
threshold, population, estimator: commitment. Flags, paths, formats, thread
counts, versions: configuration.

The same test settles the awkward case where the correction arrives late. A
re-run costing minutes is always affordable relative to publishing the wrong
direction, and a shortfall against a published value that you have already
attributed to your own configuration is not a finding about the method — either
re-run with the configuration or do not state the shortfall as a result. See
`time-the-operation-not-the-invocation` for the timing version of that rule and
`close-the-gap-to-the-published-number` for what a surviving gap is owed.

## Checklist

- [ ] Commitment and configuration are two files; only the first is frozen.
- [ ] Every configuration change carries a one-line reason and a date.
- [ ] No verdict, abstract sentence, heading or figure title carries a number from a run since shown to be mis-invoked.
- [ ] Each correction appears once, in a correction table, with the size of the move.
- [ ] The words "post-hoc", "not pre-registered" and "provisional" appear only where the *rule* changed, never where only the command did.

## Why this is here

Measured on a structural-alignment reproduction. The run froze its command lines
in `data/tool_invocations.json` before any result existed, then discovered
mid-run that its database searches had omitted a flag the source's methods
paragraph specifies for exactly that database. It re-ran, and the corrected
search reproduced the source's showcase precisely — the right rank, the right
five hits. It then labelled that re-run post-hoc, left the verdict table row
reading *"inconclusive — rank 18/21, 0 hits"*, and put in limitations that the
corrected result "cannot retroactively become the pre-registered outcome". The
report's own summary of its best reproduction is the version it had already
shown was wrong.
