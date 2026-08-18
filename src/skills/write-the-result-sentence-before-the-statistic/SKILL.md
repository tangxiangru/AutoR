---
name: write-the-result-sentence-before-the-statistic
description: Use at the design freeze when analysis and figure slots are being fixed, and again at analysis before a comparative quantity is left uncomputed. Covers checking that the statistic can express the claim at all - its arguments, its degrees of freedom, its unit - the two-dataset test that finds the ones that cannot, and how to amend a frozen slate when a slot's statistic fails.
stages: 03_study_design, 06_analysis
---

# Write the result sentence, then pick the statistic that can fill its blanks

## What goes wrong

The statistic is computed correctly, the figure is drawn correctly, and neither can express
the claim the task asked for. This is not an error anyone catches by checking the code. It
is caught only by holding the statistic against the sentence it is supposed to produce.
Three shapes, in order of how much they cost:

**Wrong arguments.** The claim compares two arms under one condition. The plotted quantity
compares your value to a third reference - typically the published value - so the grid is
signed deviations from someone else's number. That is a fidelity exhibit. It can be a
figure; it is not the result, and the result's own quantity, the ratio or difference
between the arms per condition, may never be formed anywhere in the run.

**Too few degrees of freedom.** A claim about the shape of a profile is reduced to an
argmax and its offset - a statistic that structurally cannot represent a second local
maximum, so a secondary feature cannot be found, reported or refuted. A claim about which
items were detected is reduced to an aggregate area, which cannot name a member.

**Wrong unit.** The sentence quotes a factor; the table holds two absolute measurements and
a percentage of a third thing, and the reader is left to divide.

What makes all three expensive is when they are frozen. A slate that fixes chart types at
design time, before any statistic exists, is a ceiling: later stages execute it faithfully,
each correctly reports that it computed no new pre-registered statistic, and the deliverable
is unreachable without reopening a decision no stage believes it may reopen.

## At the design freeze: sentence first, slot second

For each deliverable the task names (`cover-what-the-task-named` builds that list), write
the result sentence you owe, with blanks:

> Under ____, method ____ is ____ ____ than ____, and ____ .

Then, per blank, write four things: the statistic that fills it, its **arguments**, the
file and column each argument will come from, and the **unit** of its output. Only now name
the slot. A slot is named by the sentence it settles and the statistic that fills the
blank - never by the chart type. "A heatmap of the supplied measurement grid" is not a
slot; "the per-condition ratio of each comparator's value to the method's, one row per
comparator" is.

If the statistic does not exist yet, the slot still names the statistic. That is the whole
point: a slot whose statistic is unnamed at freeze gets filled at analysis by whatever is
already on disk.

**The argument test.** Underline the entities the sentence compares. The statistic must be
a function of exactly those. If the sentence compares two tools and your statistic's
arguments are (your value, published value), it answers a different sentence. Both may be
reported; only one is the deliverable, and it is the one whose arguments match.

## At analysis: the two-dataset discrimination test

For each statistic that carries a claim, construct two inputs that differ in exactly the
way the sentence distinguishes, and run the statistic on both. If the outputs are equal or
indistinguishable, the statistic cannot carry the claim. This takes minutes and it is the
only reliable detector:

- shape claim: one profile with a single dominant feature, one with the same dominant
  feature plus a smaller secondary one - does the statistic differ?
- set claim: two prediction sets with identical score distributions and different members -
  does the statistic differ?
- comparative claim: two conditions with identical deviations from the external reference
  but opposite ordering between the arms - does the statistic differ?

Where it fails, the fix is a statistic with more structure, not more prose: the profile
across all positions rather than its argmax, the membership table rather than the area, the
per-condition ratio rather than the per-cell deviation.

## Form the derived quantity as a column

Which axes a comparison is expected to carry in your field, and the accuracy column that
has to accompany a cost claim, is `life-benchmark-against-the-incumbent`. This skill is
upstream of it: whether the quantity you planned to plot can state any claim at all.

Every comparative claim's quantity is derived. Compute it and store it: direction in the
column name (`x_faster_than_<comparator>`, `x_lower_<axis>_than_<comparator>`), one row per
condition x comparator x axis. Then count: how many cells that grid should have, how many
are populated, and which combinations are absent - drawn and tabulated as absent, never as
zero and never imputed. A derived quantity that exists only as "the reader can divide these
two columns" is not in the report, and the ones nobody divides are the ones that go
uncomputed for the whole run.

## Amending a frozen slate is required, not scope creep

If a frozen slot's statistic fails the argument test or the discrimination test, adding the
sufficient statistic is an obligation. Record the amendment where the freeze lives: the
slot, the test it failed, the statistic added, the stage that added it. Preregistration
protects you from choosing a statistic after seeing which one wins; it does not license
shipping a plan that cannot state the result. Note also that anything already on disk and
unpublished is cheaper than a new run - sweep for it with
`publish-what-the-run-already-computed` before you spend compute.

## Checklist

- [ ] A blanked result sentence written for every named deliverable, before slots are
      frozen.
- [ ] Per blank: statistic, arguments, source file and column, output unit.
- [ ] Argument test passed - the statistic's arguments are the entities the sentence
      compares.
- [ ] Discrimination test run on every claim-carrying statistic, with the two constructed
      inputs kept as a test.
- [ ] Derived comparative quantity materialised as a named, directional column.
- [ ] Cell count stated: how many of condition x comparator x axis are populated; absences
      shown as absent.
- [ ] Every amendment to the frozen slate recorded with the test that forced it.
