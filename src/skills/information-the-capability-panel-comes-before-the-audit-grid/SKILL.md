---
name: information-the-capability-panel-comes-before-the-audit-grid
description: Use at analysis and writing when a figure has to show a generative system's own output — images it drew, structures it produced, artifacts it rendered. Covers why a scored contact sheet is not evidence that the system works, what the capability panel contains instead, how its members are chosen without cherry-picking, and the order the two figures go in.
stages: 06_analysis, 07_writing
applies_when: visual generation
---

# A scored contact sheet answers a different question from "can it do this"

Two questions get answered with pictures of your system's output, and one figure
cannot answer both.

*Can it do this?* is answered by a small number of samples shown large, clean,
with the prompt underneath and the source's own sample beside them. Nothing else
in a report establishes that the generation pathway you rebuilt produces the kind
of object the paper claims.

*How often is it right?* is answered by a contact sheet of many small tiles, each
stamped with a scorer's verdict and its reason.

Ship only the second and you have answered only the second — and worse, the
rendered evidence a reader takes away is a wall of red. A montage where half the
tiles read `detector: FAIL` under a caption quoting a rate below the published
one is a competent audit and a poor exhibit, and it is the only picture of your
system's output the reader ever sees.

## What goes in the capability panel

Three to six samples at a size where the object is legible. No verdict labels, no
red, no per-tile annotations. The prompt underneath each one, verbatim. The
source's own sample for the same prompt in the same figure, labelled, so the
comparison is made by looking rather than by reading a number. One line of
caption naming the settings — resolution, guidance, seed — and pointing at the
audit figure for the rate.

**Its members are chosen by the source, not by your score.** Fill it with the
demonstrations the source printed; that selection was made before you saw any of
your outputs, which is what keeps it from being cherry-picking. Where you have to
select from your own prompt set, say how in the caption — "first six in index
order", or "best of four samples per prompt, N stated" — and never "the ones that
passed".

## What goes in the audit grid

Everything the capability panel leaves out: the whole scored set at thumbnail
size, verdicts, failure reasons, the rate with its interval, the published rate
beside it. Lead its caption with the honest number. If the rate is well under the
published one, that belongs in the abstract too. The point of the split is not to
soften the failure — it is that a failure rate and a capability demonstration are
two findings, and collapsing them into one figure loses the one that is harder to
recover.

Then say in prose what the failures *are*. "Eight of nine position failures read
`found 0 < 1`: one named object is absent, so the relation was never testable" is
a result. A grid of red stamps is not.

## Boundary

`the-canonical-figure` is about the plot a field expects for a claim of a given
kind — the learning curve, the posterior corner, the residual panel. This is
about figures whose content is the system's own generated artifacts, where the
choice is between exhibiting and scoring, and where both are owed.

## Why this is here

Measured on a unified understanding-and-generation reproduction. The run's only
figure of generated images was an eighteen-tile GenEval montage; nine of the
eighteen carry a red `detector: FAIL` caption, and its header line records
"60 scored, overall 0.4167". Its image criterion scored **0.0**. A plain agent on
the same task shipped eight photographic samples across the top of its generation
figure with no verdict labels, kept its scoring to the panels below, and scored
**41.0** on the same criterion — neither run having produced the specific image
the criterion names.
