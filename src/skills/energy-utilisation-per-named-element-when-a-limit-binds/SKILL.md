---
name: energy-utilisation-per-named-element-when-a-limit-binds
description: Use at experimentation, analysis and figure planning whenever a result is explained by something reaching a limit -- a transfer capacity, a storage power or energy limit, a ramp rate, a cap, a budget. Covers reading per-element flows out of the solved object under their input ids, the normalised utilisation series and ranked binding-frequency table, and the cross-tab that tests the attribution instead of asserting it.
stages: 05_experimentation, 06_analysis, 07_writing
---

# If a limit explains your result, publish utilisation per named element

## When this applies

Trigger: the draft contains a sentence of the form "X happens because C is binding"
-- a transfer capacity, a storage power or energy limit, a ramp rate, an emission
cap, a budget, any constraint with a right-hand side. The moment that sentence
exists you owe the reader the utilisation of C. It fires at experimentation too,
because the per-element quantities have to be read out of the solved object before
it goes out of scope.

`energy-canonical-configuration-before-the-enhanced-variant` states the panel rule
in one clause -- a utilisation-ratio time series when claiming a limit binds. This
file is the rest of it: what to persist and under which ids, the ranked table, and
the cross-tab that tests the attribution instead of asserting it. The arm that
removes the constraint altogether belongs to
`energy-counterfactual-pair-and-hierarchy-closure`; run it there, do not re-derive
it here.

## What goes wrong

**The claim is made in prose and shown nowhere.** "The corridor sits at its rating
in every step" appears in a caption, and no axis in the report carries the ratio.
Search your own draft for *loading*, *utilisation*, *saturated*, *binding*, *at its
limit*. If those words appear in prose and no figure has a dimensionless axis, this
is you.

**The raw quantity is plotted against its rating.** A flow drawn in raw units on an
axis scaled to several times its rating reads as a flat line low in the panel; the
reader has to divide by eye, and the thing that explains the result occupies a
fraction of the panel height. Plot the ratio, not the flow.

**A set of named elements is collapsed into one derived aggregate.** Noticing that
several parallel elements share one effective limit is a real analytical result.
Reporting only the aggregate deletes every element the input files and the source
literature name, and no reader can match your rows to theirs. The input file spells
out its element ids; an aggregate you invented is not among them.

## What to produce

### 1. A utilisation artifact: every rated element, every step

    u[e, t] = |flow[e, t]| / rating[e]      for each element e with a finite rating

Persist it as one row per (element, step), carrying the element id **exactly as the
input file spells it**, the rating in the input's units, the signed flow, and `u`.
Read the per-element series out of the solved object at solve time -- solvers hold
them and then discard them, and re-solving later to recover them costs an hour you
will not have.

### 2. A ranked utilisation table in the report body

One row per element, sorted by binding frequency, the top handful plus every element
the task brief or the source study names:

| element (input id) | rating | mean u | max u | steps with u >= 0.99 | share of horizon |

This is what turns "the network is congested" into a measurement, and it names the
bottleneck instead of describing it.

### 3. A figure with a dimensionless axis

- y in [0, 1.05], with a horizontal reference line at 1.0 labelled as the rating.
- x is the native step index, over the full horizon.
- One line per named element for the top few; where there are many elements, add an
  element x step heatmap on a shared 0-1 colour scale beside it.
- Title the panel with the element id and the ratio, not with the raw capacity.

### 4. The attribution test, reported either way

An attribution is falsifiable, so test it rather than asserting it. Cross-tabulate
the steps where the effect occurs against the steps where the constraint is at its
limit:

    effect > 0 and u >= 0.99     attribution holds
    effect > 0 and u <  0.99     something else is binding
    effect = 0 and u >= 0.99     binding but harmless

Publish the counts, the inconvenient ones included. If the off-diagonal is large,
rank every element by `u` restricted to those steps and name the one that is
actually binding there.

## Checklist

- [ ] Per-element, per-step flows were read out of the solved model and persisted,
      not discarded.
- [ ] `u = |flow| / rating` exists as a column for every rated element.
- [ ] The ranked utilisation table, with a binding-frequency column, is in the body.
- [ ] At least one figure has a dimensionless axis in [0, 1.05] with a line at 1.0.
- [ ] Every element in the table and the figure carries its input-file id; an
      aggregate you defined is reported in addition to its members, never instead of
      them.
- [ ] The attribution counts are published.
- [ ] Grep the finished report for "saturat", "binding", "at its limit", "congest":
      every hit has a utilisation number or figure within one paragraph.
