---
name: energy-dispatch-quantities-on-the-native-time-index
description: Use at study design when allocating figure slots, and again at analysis and writing, on any run that produces one value per quantity per step over a horizon. Covers the (quantity x axis) coverage matrix a one-axis deliverables ledger cannot see, the empty-cell test that has to pass before a figure is drawn, and how a per-step panel is built and ordered against method panels.
stages: 03_study_design, 06_analysis, 07_writing
---

# Draw every headline quantity on the model's own step index before you aggregate it

## When this applies

Trigger: you are allocating figure slots, and the run will produce one value per
quantity per step over a horizon of T steps. It fires again at analysis and at
writing, whenever a headline quantity has reached the draft only as a period
total, a single bar or a table row.

Three shipped skills state parts of this rule in one line each.
`energy-counterfactual-pair-and-hierarchy-closure` says to plot the full horizon at
the data's own timestep; `energy-canonical-configuration-before-the-enhanced-variant`
asks for a stacked decomposition when claiming a total splits;
`cover-what-the-task-named` enumerates the deliverables at design time. This file is
the procedure that makes those fire while the plan is still editable: the second
axis, the empty-cell test, and how the panel is built. Read it before the figure
slots are frozen; afterwards it is a rewrite, not an edit.

## What goes wrong

A figure plan indexed by hypothesis produces panels about the *method*: parameter
sweeps against analytic bounds, sensitivity surfaces, solver-agreement checks,
formulation ladders, cost decompositions, a headline-numbers composite. Not one of
them has a time axis, because no hypothesis is about a time axis. The primary
physical quantity then appears once as a period total, and the T-step series the run
actually produced sits in a CSV and is never rendered.

This survives the deliverables audit, because coverage ledgers are written with one
axis. Rows of the shape

    "<quantity A>, <quantity B>, <quantity C>"   -> figure:i   # period-total bars
    "at <resolution> resolution"                 -> figure:j   # that axis, without C

both resolve, the audit reports zero unresolved deliverables, and the cell that was
promised -- quantity C at that resolution -- has no panel anywhere. A ledger that
checks "this deliverable points at some figure" cannot detect that a quantity was
never drawn on the axis the task named it at.

The aggregate also deletes the only thing the axis carries: *when*. "X% over the
horizon" and "X concentrates in the steps where the driver peaks" are different
claims, and only the second shows a mechanism acting dynamically rather than on
average.

## What to produce

**1. Rows: quantities.** Take the task's Output sentence literally and split it on
its commas and parentheses. A phrase of the form "A (a1, a2, a3) and B" is four
rows, not one. Add any quantity that appears in your abstract or headline table.

**2. Columns: axes.** At minimum `native step index` and `aggregate over the
horizon`; add `per spatial unit` if the data is spatial and `per element` if it is
networked.

**3. The empty-cell test, before anything is drawn.** For every
(quantity x native step index) cell, name the artifact file, the columns and the
panel that will fill it. A cell whose entry is "a table", "the headline number",
"prose", or "a sub-axis of the panel about something else" is empty. The empty
cells are the work list.

**4. Persist the tidy series** -- one row per step, one column per quantity, per arm
-- so filling a cell later is a plotting call and not a re-run.

### How the panel has to be built

- **Stack the decomposition your headline ratio divides.** If the report quotes
  `part / whole`, the panel is an area chart of the parts stacked to the whole
  envelope at every step, so the ratio is a visible area split and a reader can read
  your percentage off the picture without arithmetic.
- **One dominant quantity per panel.** A component an order of magnitude larger than
  the quantity under study -- typically the term that absorbs infeasibility, or a
  total that contains it -- goes in its own panel or on a broken axis. A band
  squashed into the bottom tenth of a plot has not been published.
- **Full horizon, unsmoothed, unresampled.** Add a zoomed inset on the extremal
  window if T is large; keep the whole series as the main axes.
- **The aggregate is the caption; the series is the figure.** Never the reverse.
- **Same colour for the same quantity in every panel**, with the components named in
  the caption in the order they are stacked.

### Ordering rule

Series panels come before every sweep, surface, agreement check, replication
diagnostic, formulation ladder and aggregate bar. A method panel earns a slot only
after every (quantity x native step index) cell is filled. If the figure budget
binds, cut a sensitivity panel, not a series panel.

## Checklist

- [ ] The matrix exists in writing, quantities x axes, before any figure is drawn.
- [ ] Every quantity in the task's Output sentence has a panel on the native step
      index, or one line saying why the run cannot produce that series.
- [ ] Every percentage in the abstract has a panel whose stacked areas are its
      numerator and its denominator.
- [ ] No headline quantity appears only as a bar, only in a table, or only as a
      secondary sub-axis of a panel about something else.
- [ ] Each panel names the file and the columns it was drawn from.
- [ ] Series panels precede method panels in the body.
- [ ] Each series caption says *when* something happens, not only how much.
