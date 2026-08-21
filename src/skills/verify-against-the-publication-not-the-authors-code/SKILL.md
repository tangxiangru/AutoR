---
name: verify-against-the-publication-not-the-authors-code
description: Use at literature survey the moment you find the source's released code, and at experimentation and analysis whenever you are about to report that a result reproduces. Covers where a reference value comes from and in what order of authority, transcribing the published-value file before you compute anything, the published-versus-ours comparison every deliverable carries in the body, and what a replay of the authors' script does and does not establish.
benchmarks: researchclawbench
stages: 01_literature_survey, 05_experimentation, 06_analysis
---

# The authors' released code is not the published result

## The failure this prevents

A run located the source's released analysis and plotting script, called it in
its own words "the operational definition" of the source's figures, replayed it
block by block against the shipped data, and reported near-total value-by-value
agreement with that replay as its reproduction evidence. It went further at
design time and declared that any disagreement with the script was its own bug.

Three things followed. On two figure requirements the reader wrote that the
counts were not verified against the original paper and graded the run at par,
while a plainer comparator that tabulated its numbers against the claims as the
source states them was graded above it on both. On a third, the released block
draws one layer where the published figure carries two, so replaying it
confirmed a figure the paper does not contain. And the one requirement where
that run did re-derive a published statistic from the source's own printed table
and showed both numbers was its best-scoring item of the task.

Agreement with a released script is self-consistency between two executions of
one code path. It cannot detect an error the script itself has, it says nothing
about the quantities the script does not compute, and it is not what "we
reproduced the paper" means to the person reading you.

## Where a reference value comes from, in order of authority

1. **Printed in the source.** A number in its text, a table, a caption or the
   abstract. Transcribe it verbatim with its unit, its denominator and where it
   appears.
2. **Read off the rendered figure.** Where the source draws a value and never
   prints it, read it off the rendering and record the precision — "read from
   the published panel, ±5%". A read-off value is a reference; an absent one is
   not.
3. **Stated as a claim in words.** "X dominates", "the trend reverses after the
   midpoint". Still a reference: convert it into the statistic that decides it,
   and write the statistic down before you run it.
4. **Produced by replaying the authors' code.** A fourth column, labelled as a
   replay. Never the reference.

## Build the reference file while you read, not while you write

At the literature stage, write `notes/published_values.json`: one row per
quantity the source states — the quantity, the value as printed, the unit and
denominator as printed, the location, and the claim it supports. Transcribing
before you compute is the point of the exercise. A reference list assembled
after your own numbers exist gets fitted to them: the conventions you chose
become the conventions you believe the source used, and disagreements dissolve
into definitional notes instead of being found.

Where the source's convention is genuinely ambiguous — what the denominator is,
whether multi-valued entries are split, which subset is counted — record both
readings as separate rows and later report your value against both. That is a
finding. Silently picking one and calling the match a reproduction is not.

## Every deliverable carries a comparison a reader can check

For each figure or table you are reproducing, one small block beside it:

| quantity | as published | ours | difference | what would explain it |

Where the source's claim is qualitative, the block is: claim as stated →
statistic → value → verdict. A paragraph asserting agreement is not checkable; a
row is. Keep the block in the body next to the deliverable it belongs to. The
same rows in an appendix are the same evidence with the reader removed.

Then corroborate each headline by a second route that does not share the first
one's code path: an independent aggregation written from the source's own
definition, a fitted model whose parameter implies the same quantity, a
resampling that reports how often the published ordering survives. Two routes
agreeing is verification. One route run twice is not.

## What a replay is genuinely good for

Keep it. As a baseline and a debugger, not as the reference.

- It localises a bug in your own filter chain in minutes, which is worth the
  hour it takes to set up.
- It documents the operational choices the paper leaves implicit — which you
  then state as choices you inherited, rather than adopt as definitions.
- Its output is a lower bound on the published artifact: it is what the authors
  last committed, and the published figure may carry layers, labels, corrections
  or hand edits that live nowhere in the repository.
- Report it in its own terms: "agrees with the authors' released script on N of
  M computed values". That sentence is about the script. Do not let it stand in
  the slot where a reader expects agreement with the paper.

## What this extends

`close-the-gap-to-the-published-number` takes over when the comparison lands
materially off; this skill is about where the published column comes from and
why a replay cannot fill it. `draw-the-source-figure-panel-for-panel` says to
print the source's named constants on the panel — this is the file those
constants are read from. `reconstruct-the-figure-layer-you-cannot-source`
applies the same rule at layer granularity: the published rendering, not the
script, defines what you owe.

## Checklist, before analysis closes

- Every quantity the source prints is in the reference file with its location,
  and every deliverable has at least one row.
- Every reproduced figure or table has its published-versus-ours comparison in
  the body, next to it.
- No sentence claims reproduction where the only comparison made is to a replay.
- Every claim the source states in words has a named statistic and a verdict.
- Anything you could not compare, and why, in one line — not silence.
