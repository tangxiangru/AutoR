---
name: energy-spend-the-figure-budget-on-the-named-checks
description: Use at study design when allocating figure slots, and again at analysis and writing when panels are drawn and ordered into the report. Covers a figure budget that is rationed and read in order, giving every check the task's own materials name a single-purpose panel before your diagnostics claim slots, titling a panel with its quantity rather than the run's verdict, and drawing a check that comes out trivially satisfied.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# Spend the figure budget on the checks the materials name, in the order they will be read

## What goes wrong

Two ordinary decisions collide and delete a result you already computed.

The first: your plan allocates one figure slot per hypothesis, so the panel list
becomes an index of *your* questions. When the hypotheses are an audit of the
source - is the archive internally consistent, are its constants right, is the
shipped file a surrogate - every slot goes to an audit diagnostic and none goes
to the plain checks the task's own materials name.

The second: a report's figures are read as a bounded, ordered prefix. A reader
opens the first few in document order; an automated reader is shown a capped
number of images, taken in the order it finds them. Panels past that cut are not
weighted less, they are not seen. A report carrying a dozen panels has not
published a dozen exhibits.

Cross the two and you get the characteristic loss: the computation ran, the
number is in `outputs/`, one panel does show it, and the report reads as though
the check was never performed. From where the reader sits that conclusion is
correct.

Three aggravators, each of which turns a performed check into an invisible one:

- **Verdict titles.** The panel is titled with the run's conclusion about its own
  hypothesis - supported, refuted, inconclusive - instead of the quantity and
  its value. Someone scanning titles for the check cannot tell it is there.
- **Composites.** The checked pair is one cell of a multi-panel grid of novel
  diagnostics. The exhibit exists; nothing in the layout says which cell is the
  result.
- **Degeneracy as licence.** The check runs, comes out trivially satisfied - exact,
  at the floating-point floor, nothing flagged - and the run reasons that a trivial
  result is not a test and drops the exhibit and often the number with it.
  Triviality is an argument *about* the value. It does not discharge showing it.

## What to produce

A figure list whose leading entries are one single-purpose panel per check the
task's materials name, each titled with its quantity and its value, capped at a
total you can defend.

## Checklist

1. **Enumerate the checks the materials name, before you have hypotheses.** Read
   the task brief's output list and the description shipped with the archive, and
   copy out every operation they say the data supports or the paper performed -
   verification, consistency, correlation, cleaning, clustering, forecasting. One
   row each, in their words. This list is not derived from your questions and does
   not change when your questions do.
2. **Allocate those slots first.** Fill them before any hypothesis claims one. If
   the plan schema demands a claim id, use `exploratory:` plus the row name.
   `draw-the-source-figure-panel-for-panel` states this rule for panels the source
   *drew*; the rows here are the checks the source only *describes*, which is why
   they are the ones that lose their slot.
3. **Cap the total and treat every new panel as a trade.** Write the cap into the
   plan. Roughly one panel per named check, plus a small number of diagnostics, is
   defensible; past that each addition pushes something below the cut. When a new
   diagnostic is worth drawing, name the panel it replaces.
4. **Order the document by that list.** The named-check panels come first in the
   results, in the order of the deliverable list. Dataset overviews, pipeline
   schematics and sensitivity sweeps are not free: they consume the leading slots
   that decide what is seen.
5. **One claim per panel.** A check that shares a panel with three of your
   diagnostics does not have a panel. Reserve composites for material that is
   genuinely one object.
6. **Title with the quantity, the population and the value.** The pattern is
   `<quantity>, <unit>, <population>: <statistic> = <value>`. The verdict goes in
   the body text - never the title, never an axis annotation. A title that states
   your conclusion tells the reader what you think and hides what you measured;
   worse, a dismissive annotation on a correct exhibit is read as the exhibit not
   counting.
7. **Print on the panel what the caption would otherwise have to carry:** n, the
   unit, the statistic and its value, entity names as row labels rather than codes
   decoded somewhere else. Then repeat those numbers in the prose beside the
   figure link, so the result survives whether the reader reads the image or the
   text.
8. **A trivially satisfied check is drawn exactly like a contested one.** Report
   the measured value at the precision you measured it, with the relevant floor
   beside it - float64 epsilon, sensor resolution, the rounding of the stored
   column - and put the argument for why it had to come out that way in the next
   sentence, not in place of the number and not in the title.
9. **Legibility beats density on an image criterion.** Named rows, an axis in a
   unit a reader thinks in or an explicit relative axis in percent, the headline
   number printed on the panel. A log axis over signed residuals, a scatter of
   every cell, or a count of breaches against a tolerance you invented may each be
   the better diagnostic, and none of them shows a reader whether two things
   agree. What the agreement exhibit itself must contain is specified in
   `energy-counterfactual-pair-and-hierarchy-closure`; this skill governs whether
   it gets a slot, where in the order, and under what title.
10. **Audit findings are additive, and they come second.** If you conclude the
    supplied materials are degenerate, synthetic or defective, the named check
    still runs on the supplied materials and still gets its panel first; the
    critique follows in its own section, with its own panels only if the budget
    allows. Deleting the check because you distrust the input deletes the evidence
    for your own critique.

## Before you finish

List your figures in document order with the title of each, as a reader would see
them. Against every row of step 1, write the position of its panel. Any row whose
panel is missing, below your cap, shared with something else, or titled with a
verdict is a check you performed and did not deliver.
