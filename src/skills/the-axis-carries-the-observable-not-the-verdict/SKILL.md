---
name: the-axis-carries-the-observable-not-the-verdict
description: Use when drafting the figure list at study design, when the plotting code is written, and again before writing — especially if figure slots are being assigned from preregistered hypotheses, decision rules or agreement checks. Covers what may occupy a panel's axes, where verdicts and intervals belong instead, and a one-minute test that sorts a figure set into observable and audit.
stages: 03_study_design, 06_analysis, 07_writing
---

# Cover the caption and read the axis labels

A panel earns its place by putting a quantity of the *system* on each axis. When
a figure slot is filled from the hypothesis it settles rather than from the
result it shows, the axes drift to the machinery of the verdict, and the panel
stops being readable as a result at all.

This is the axis-level test that sits under two skills you should already be
running. `the-canonical-figure` decides which figures a paper of this kind must
contain; `draw-the-source-figure-panel-for-panel` decides which result owns a
slot and tells you to print the source's named constants on the panel. Neither
catches the case handled here: a panel that is being drawn, is nominally about
the right result, and has your run's own verdict on one of its axes. It applies
to panels with no source counterpart as well as to reproductions.

## The test

Cover the title, the caption and the legend. Read the two axis labels.

**Observable axes** name things that would exist if nobody had run a study: a
length, an energy, a temperature, a rate, a count, a composition, a
concentration, a size ratio, a class label, a step index.

**Audit axes** name things that exist only because you ran one: absolute error,
|residual|, fraction reproduced, cases a rule predicted correctly, points inside
tolerance, a score, a decision band, an interval width, a labelling margin, or a
row index in whatever order your reference table happened to be in.

Both are legitimate panels. But a named output of the task must be carried by a
panel with observable axes. If the only panel that touches a quantity has that
quantity's *error* on the y-axis, the quantity has not been shown — it has been
graded.

## What goes wrong

A run with a strong preregistration binds each figure slot to a distinct
hypothesis and writes the slot's purpose as the question it settles. By the end,
every panel in the report plots a property of the run's own inference: a
fraction with a confidence interval against a preregistered decision band,
|residual| against index in the reference table's order, the number of cases each
rule got right, a histogram of the margin a categorical label was assigned on,
the signed deviation of measurement from prediction. Each is a sound and honest
panel about the run. Not one puts a studied quantity on an axis with a number a
reader can take away.

The tell is in the run's own figure manifest. A slot whose declared purpose is
what the values of some quantity are, across the families the theory defines,
records its evidence as a count of published values checked and a residual panel
covering all of them. The slot asks what the values *are*; the accounting answers
how many were *checked*.

## What to produce

**Stage 03, before any plotting code.** For each figure slot, write the literal x
and y axis labels with units into the report plan, and tag each axis `observable`
or `audit`. A slot that is the only home of a named output and carries an audit
axis is rejected and rewritten there and then, not at Stage 07 when the code
exists and the panel looks finished.

**One panel per named output whose axes are the quantity and the variable it
depends on.** Where you are comparing against a published or supplied value, the
comparison belongs on those same axes — as an overlaid marker or a labelled line
at the predicted level, annotated with its numeral — not converted into a
residual that spends an axis on error.

**Print your own landmark values on the canvas.** For every curve or family a
reader would quote one number from, annotate that number as text at the point.
Someone who reads only your figures should be able to state the value.

**Log axes hide landmarks.** A family of curves over a decade, unannotated,
answers "which is bigger" and nothing else. If the reader's question is what the
value is at a particular operating point, annotate that point or add a linear
inset around it.

**Verdicts, confidence intervals, tolerance bands and decision rules go in the
caption**, or into one clearly separate audit figure at the end. The caption is
the right home for N, the interval, and whether the criterion was met. It is not
the right home for the value.

## Before you finish

List every panel you are shipping in two columns, observable and audit, keyed by
its axis labels rather than by its title. Every named output of the task should
appear in the observable column. If the audit column is longer, the figure set is
about the run rather than about the system, and it will not be recognised as the
result it is.
