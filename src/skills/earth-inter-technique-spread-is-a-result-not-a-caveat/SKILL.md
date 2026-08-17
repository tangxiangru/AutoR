---
name: earth-inter-technique-spread-is-a-result-not-a-caveat
description: Use at study design when the figure list is chosen, and again at analysis, when the supplied data is many estimates of one quantity from several measurement techniques, instruments or products and the deliverable is the combined or reconciled series they produce. Extends earth-report-the-lattice-and-show-the-field with the four things that decide whether the per-technique grid says anything: each technique's own coverage window, rate versus interannual variability, recomputing a population-mismatched statistic instead of demoting it, and where the offsets have to be printed.
stages: 03_study_design, 06_analysis, 07_writing
---

# Earth: the spread between techniques is a result, not a caveat

When the deliverable is a reconciled product - one series combined from several
measurement techniques, instruments or data products - the combined curve is half
of it. The other half is what the inputs said before you combined them: which
technique reports the most change, which two disagree and where, whether the
combination sits inside their spread or is pulled onto one of them. A reader of a
reconciliation looks for the disagreement that was reconciled, and a combined
curve shows none of it.

## The failure this prevents

Two runs on the same reconciliation task lost the same criterion in two different
ways, and both mistakes are cheap to avoid.

The first measured the disagreement properly at its survey stage - pairwise
differences between techniques per unit, each technique's offset from the
combination, the units where they diverge most - and wrote all of it to a results
file. Its later experiments re-ran the pipeline on the raw submissions, so the
survey-stage statistic described a slightly different population than the
preregistered arms. Instead of recomputing it on the arms' population, the run
moved the number into a Limitations bullet with a scope caveat welded to it,
saying the statistic came from a different population than the arms. The
reconciliation the task existed to deliver therefore appears in the report only
as a weakness of the study.

The second run drew the figure, and its numbers were close to the published ones,
and it still scored near zero on that criterion. The panel plotted differences
with no values printed in it, and the paragraph carrying the values sat halfway
down the report. A figure-typed criterion is read from the picture plus an opening
excerpt of the report text, not from the whole document, so a number in the middle
of the file is - for that criterion - not in the report at all.

## What to produce

The grid itself is `earth-report-the-lattice-and-show-the-field`: per-stratum
panels over the technique x sub-unit cross-product, each stratum carrying its own
uncertainty, a global row, and the governing numbers printed inside the panel.
Follow it. This skill is the four decisions that determine whether that grid says
anything.

1. **Each technique on its own coverage window, never the common window.**
   Instrument eras differ: one technique starts at a mission launch, one has a
   gap, one exists only as multi-year survey periods. Truncating them all to the
   intersection changes the quantity being compared and destroys the comparison
   exactly where coverage differs most - the sparse technique is the one whose
   window you are deleting. Estimate each technique's rate over the years that
   technique actually observed, print that window on its row, and add a coverage
   matrix of technique x unit x period marked used and not used.
2. **Long-term rate and interannual variability are two statistics.** Techniques
   routinely agree on one and not the other, and combination schemes usually take
   the two from different sources. Report the rate offset and the year-to-year
   agreement separately, per technique, and state which of the two each technique
   actually contributes to your combination. One pooled disagreement number
   answers neither question.
3. **A population mismatch is a recompute, not a demotion.** When a quantity you
   measured earlier does not sit on the same population as your experimental arms,
   the fix is to recompute it on the arms' population, at the cost of a script.
   Demoting it - a caveat welded to the number, a scope note, a move into
   Limitations - converts the study's own deliverable into a statement about the
   study's weaknesses. Any scope condition that survives travels in the same
   sentence as the number, in Results.
4. **Placement decides whether it counts.** Choose the technique with the most
   complete coverage as the reference, and print every other technique's offset
   from it - value, uncertainty, and the two or three named units where it is
   largest - inside the panel itself, not only in the caption or the surrounding
   text. Restate the cross-unit mean offsets in the abstract or the report's
   opening pages. A pooled offset hides that most of the disagreement usually
   lives in two places, and those two places are the finding.

## Before you finish

From the pictures alone, could a reader say which technique reports the most
change, which two techniques disagree most and where, and whether the combination
sits between them? Does every estimate carry an interval, so that any statement
about techniques agreeing inside their stated uncertainties is a claim about bars
and not about points? If the techniques exist in the report only as an inventory
of input files and a sentence saying they were combined, the reconciliation has
been asserted and not shown - and if the only place they appear as numbers is a
list of the study's own weaknesses, it has been disowned.
