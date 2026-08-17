---
name: math-budget-the-grid-before-the-cell
description: Use at hypothesis generation and study design when the supplied data is a factorial grid of conditions - one directory per family or environment, several condition levels inside each - and the source's protocol prices past the compute you have. Covers enumerating cells from the directories rather than from the protocol, calibrating the per-instance limit instead of inheriting it, breadth before depth with a per-cell cap, what to do when every arm floors, and the zero-compute figure that replaces an arm which never ran.
stages: 02_hypothesis_generation, 03_study_design, 05_experimentation, 07_writing
---

# Budget the grid before the cell

## What goes wrong

The supplied data is a factorial grid: one directory per family or environment, several condition
levels inside each (problem size, difficulty tier, noise level, scale). The source's protocol
prices at one or two orders of magnitude past your compute, so you look for a defensible shrink.
The tempting rule is **statistical power**: find the cell with the largest effect, show a small n
resolves it, spend everything there, and mark the rest "not run" against the source's published
values.

That rule maximises the significance of one number and destroys the deliverable. What you were
asked to support is a *trend across conditions* - which family, at which level, by how much,
against which competitors. One cell cannot carry a trend at any p-value, and "not run" is correct
bookkeeping and zero result.

The tell is mechanical: a beautiful data-inventory figure - families down the rows, levels across
the columns, instance counts in the cells - and then a results section in which no figure has
either axis. **You drew the grid and left it empty.**

## Enumerate from the directories, before a hypothesis is frozen

Every directory x every level it ships, with the shipped instance count per cell. Print it. This
is `ls` plus a header read, not an estimate from the source's protocol, and it is the enumeration
your plan is scored against. The shipped levels are the starting ladder, not the whole ladder;
leave space for rungs the data does not ship.

## The limit is a measurement, not an inheritance

The fork is explicit: *full fidelity at one cell, or a reduced per-instance budget across every
cell.* Take the second. A missing cell cannot be recovered by any later analysis at any price; a
shorter limit is a disclosed condition.

Do not assume the ordering of arms is budget-invariant. For anytime methods - anything holding an
incumbent and improving it, or switching strategy partway - arms cross as the limit grows, and the
winner at a short limit need not be the winner at the source's. Calibrate:

1. **Price the host.** One arm, one instance, one timed probe per family. Not the source's
   hardware, not an estimate. Record the ratio to any runtime the source publishes; the plan turns
   on it.
2. **Two-limit probe** at one cell near the transition, where the incumbent is neither floored nor
   saturated: every arm at L and at 3-5 L, two instances each. If the ordering or the sign of the
   margin moves between them, L is below the regime the claim lives in, and numbers taken there
   are about your budget rather than about the methods.
3. **Solve for the largest L that fits the whole grid**,
   `L = solver_budget / (cells x arms x n_first_pass)`, then check it against (2). If no L
   satisfies both, cut n or arms per cell before you cut cells.
4. **Log the running best objective per instance, timestamped.** That re-thresholds to any
   *shorter* limit for free, and yields the limit sweep with no re-run. Upward is impossible,
   which is what fixes step 3's direction.

## Breadth before depth

- First pass touches every cell: all arms, n = 5-10, the uniform L.
- No cell gets a second pass until every cell has had a first.
- Cap any single cell at one third of the solver budget, ever - including the late "one more arm
  at the cell we already understand", which is how the cap usually breaks.

## When every arm floors at a cell

That cell is not a cell to defund. Its *condition level* sits outside the range where anything is
measurable, and moving its budget away ships a panel that is a row of zeros.

Add rungs: levels below the shipped ones until the incumbent comes off the floor (above them, for
saturation), with the shipped level marked on the axis as a dotted line. A curve falling through
the nominal level is a result; a flat zero at the nominal level is not. Caption which rungs are
yours. A floored cell still carries continuous measurements - see
`math-register-every-metric-a-run-emits` before concluding nothing happened there.

## When a planned arm never runs

Repointing the figure slot at some other existing image is not a repair: the axis stays unshown,
and a validator that checks only that a slot is declared will pass while the demand goes
unanswered.

Replace it with the cheapest figure on the same axis - the source's published values across the
whole grid, on the source's axes, one series per competitor it names, your measured cells
overlaid, unmeasured cells left as visible gaps. If you parsed or digitised a reference table at
literature stage you already hold that figure's data; ship it as a figure. Rendered instead as
prose with the competitor columns dropped, it is the most expensive omission available at writing
stage, and drawing it costs zero solver seconds.

## Checklist, before an hour of solver time

- [ ] Can I name the figure whose panels are the grid's rows and whose x-axis is its columns, one
      series per arm? Does the plan produce the numbers that fill it?
- [ ] Did I choose L by arithmetic over the whole grid and check it with a two-limit probe, or
      inherit the source's limit for one cell?
- [ ] Is the incumbent off the floor at the chosen L?
- [ ] Is any single cell scheduled for more than a third of the budget?
- [ ] Am I logging the running best objective per instance, so a shorter limit is free?
- [ ] Cut off at half the plan, do I have a partial row for every family or a complete row for
      one? Prefer the partial row everywhere.

## Anti-patterns

- *"A power calculation shows only cell X can decide anything."* Power is per metric and per
  claim. Eight cells at p ~ 0.2 support a claim that spans conditions; one cell at p < 0.001 does
  not.
- *"The source ran at limit L, so we must."* Their L matters when you put an absolute number
  beside theirs. It does not license spending the grid's budget on one cell.
- *"The other families carry published values with a not-run marker."* Reference values belong on
  the same axes as your measurements, as a second series - never as a substitute for one, and
  never with the competitor columns dropped.

Per-family and per-regime reporting rows, degenerate families included, are already covered by
`math-equal-effort-baselines-and-knob-sweeps`. This skill buys the numbers that fill those rows.
