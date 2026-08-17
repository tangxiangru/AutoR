---
name: price-the-grid-in-wall-clock-and-fill-it-breadth-first
description: Use at the end of study design and through implementation and experimentation, when the experiment grid has more cells than you can obviously afford and the budget is a wall clock rather than a queue. Covers the hard gate on planning time, measuring one cell's cost to price the whole grid, choosing a first-pass fidelity from the quotient, the pass order, and deciding between buying cells and buying repeats.
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Stop planning and launch a cheap pass over every cell

A grid run depth-first at the source's fidelity ends the same way every time: the
first few cells are beautiful and the rest do not exist. The reasoning is sensible
from the inside -- the source trained for N epochs so N epochs is the honest
budget; the big dataset is expensive so start with the small ones; the second
architecture profiled expensive so schedule it last. Each step is correct and the
sequence is fatal.

## The gate, before anything else

Check the wall clock at the end of the literature and design work.

**If a third of the run has gone and nothing is training, simulating or sampling,
stop planning and launch pass 1 with the plan you have.** This is a gate, not a
preference. Planning time is subtracted from experiment time and there is no
other account it comes out of. A design refined for one more hour against a
campaign that then does not fit is a net loss twice over.

Two corollaries. A design or hypothesis stage on its third attempt is finished:
ship what it holds and start the compute, because the design document is not a
graded artifact and the cells are. And freeze decision rules over the campaign
pass 1 will actually cover, not the one you hope to afford -- a rule quantified
over a larger set than the one that runs becomes two rules with two answers, and
the report ends up printing the unreachable branch instead of the estimate.

## Price the grid; do not estimate it

Do this in a file (`outputs/budget.json`), not in your head.

1. **Deadline.** Wall-clock end minus time already spent. That number, not the
   source's protocol, is the constraint.
2. **Cells.** Every named model or variant x every dataset the results table needs
   x every metric family. Count them. This is the denominator.
3. **Cost, measured.** Run one cell at deliberately tiny fidelity and record
   seconds. Cost is close to linear in epochs and in rows, so one measurement plus
   two scaling factors prices the whole grid. Measure the arm you expect to be
   expensive too: per-cell cost varies by an order of magnitude across model
   families, and the expensive family is the one that silently gets dropped.
4. **Fidelity from the quotient.** Pick the largest fidelity `f1` such that
   `cells x t(f1)` fits in **40%** of the remaining time. Subsample the large
   datasets to make it fit and record the subsample fraction as a column.
5. **Reserve the rest**: ~35% for pass 2, ~25% for analysis, figures and writing.
   Analysis and writing always overrun.

If the arithmetic says the full-fidelity grid does not fit, that is the answer and
it arrived early enough to act on. Cut fidelity, subsample rows, cut repeats. Do
not cut cells; `information-fill-the-whole-results-grid` is the argument for why.

## Pass order

- **Cache once.** Featurise, preprocess and split every dataset before any model
  runs, and persist it. It is a small fixed cost that makes every later cell
  cheap, and it is what makes a late breadth pass possible at all.
- **Pass 1: every cell, `f1`, one repeat.** No exceptions, including the arm you
  expect to lose and the one that profiled expensive.
- **Pass 2: deepen** the cells the headline claim rests on, towards the source's
  fidelity, overwriting pass-1 rows and recording achieved budget per cell.
- **Pass 3: repeats**, on the cells that carry a comparison.

Start pass 1 running before the design prose is finished. The prose can be written
while the campaign burns; the compute does not come back.

## Before you buy a second repeat, work out what repeats can see

Repeats and cells compete for the same seconds, and a comparison you cannot
resolve costs exactly as much as one you can.

1. From the literature stage you already have the source's proposed-minus-baseline
   margin. Write it down.
2. Pair the arms first: same seed, split, initialisation and data order. Pairing
   is free and the relevant dispersion becomes the spread of per-cell
   *differences*, usually several times smaller.
3. Measure your own spread from two pilot runs at `f1`. Resolvable difference is
   about `2.8 x sd / sqrt(n)`; solve for the `n` that gets below the margin.
4. Multiply that `n` by the cell count. If it does not fit the reserve, buy cells
   instead of repeats and report the sign pattern across cells: a consistent sign
   on several independent datasets is evidence that one noisy cell is not.

One line in Methods: *the source's margin is X, our paired spread is Y, resolving
it needs n, we can afford m, therefore we bought cells / repeats.*

## The source's budget is a target, not a constraint

"N epochs because the paper used N" is how a complete grid becomes a third of one.
Pass 1 answers "does every cell have a number in it", not "does this match the
published value". Report the achieved budget per cell and its ratio to the
source's, then let pass 2 close the gap where the headline claim rests.

## Keep the deliverable renderable at every instant

After every cell finishes, append one row to `outputs/results/grid.csv`:
`(dataset, arm, fidelity, subsample, seed, metric, value, seconds)`. Regenerate
both the results table and its figure from that CSV by script. If the clock ends
in the middle of pass 2, the exhibit still contains every cell with the budget it
actually got.

## Checklist

- [ ] Clock checked at the end of design; if past a third with nothing running,
      pass 1 was launched instead of another planning attempt.
- [ ] `outputs/budget.json`: deadline, cell count, measured seconds per cell for a
      cheap and an expensive arm, chosen `f1`, reserve split.
- [ ] Preprocessing cache built for every dataset, including ones you expect not
      to reach.
- [ ] Pass 1 covers 100% of cells before any pass-2 run starts.
- [ ] Repeats-versus-cells arithmetic written down with the source's margin and
      your measured spread.
- [ ] `grid.csv` has a row per cell with fidelity, subsample and seed; the table
      and figure are regenerated from it, not typed.
- [ ] Every cell that got less than the source's budget says so in its own row.

Related: `information-fill-the-whole-results-grid` for why a labelled reduced-N
cell beats an empty one, `train-the-named-architecture` for cutting seeds before a
named model, `result-table` for dispersion reporting. What is here and not there
is the scheduling arithmetic: the gate, the measured cost, the fidelity quotient,
the pass order and the repeats-versus-cells trade.
