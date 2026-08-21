---
name: price-the-queue-and-preempt-your-own-arms
description: Use at study design when the run queue is priced and ordered, at implementation when the runner is launched, and again at every stage boundary while any condition the source names is still at N=0. Covers pricing per (condition x dataset slice) from measured seconds, a floor N per row, committed-hours arithmetic against the clock, and preempting your own invented arms when the queue is over-subscribed.
benchmarks: researchclawbench
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Price every cell, then preempt your own arms to pay for the source's

This extends two skills that already state the goal: `run-the-conditions-the-source-ran`
("run every row before any variant of your own; if the budget cannot carry both,
cut your variant") and `information-fill-the-whole-results-grid` ("a labelled
reduced-N cell beats an empty one"). Runs that had both installed still left
published conditions at N=0 while their own extra arms ran to completion. What
was missing is not the principle. It is the arithmetic that decides which row
runs, and one check that fires when the arithmetic went wrong.

## What goes wrong

The drop decision is made once, early, against a denominator you never reach and
on a slice the graded comparison does not live on:

1. At design time you time the expensive condition per item on the biggest,
   slowest slice and multiply by the full released benchmark.
2. The product is large, so the condition is cut, and the cut is written into a
   design artifact as settled fact.
3. The clock then delivers a fraction of that sample, and the queue you planned
   is several times longer than the hours you have left.
4. Nobody redoes the multiplication. The condition that was unaffordable at the
   design N was an hour's work at the realised N, and it stays at zero while
   arms you invented — extra seeds, extra variants of your own controls, extra
   pinned values of a swept parameter — run at the full realised N.

Two errors are mechanical and both are checkable:

- **Priced per condition instead of per (condition x slice).** Per-item cost
  varies by an order of magnitude across the datasets in one study, and the
  cheap slice is often exactly where the source's own comparison is reported.
  A condition that is unaffordable on the heavy slice can be an hour on the
  light one; pricing it once, on the heavy one, deletes it everywhere.
- **The remedy assumed to be "append it later".** If the queue is
  over-subscribed — planned hours exceed hours remaining — the tail never
  executes and appending changes nothing. Only reordering and deletion move
  work into the run.

## The rule

A condition the source names may have its N shrunk, its slice narrowed, its
seeds cut to one, its stratification coarsened. It may not sit at N=0 while a
condition you invented has N>0. When the clock is short, the invented row is
what you truncate or delete, and that slot is how the source's row gets paid
for.

## The ledger: write it before the queue exists, publish it in the report

| cell (condition x slice) | named by | s/item measured | floor N | hours | realised N |

- `named by` is `source`, `task brief` or `me`. Sort every `source` and `task
  brief` row above every `me` row and fill from the top.
- `s/item` is measured on two real items **of that cell** — the expensive
  condition on that slice. Not extrapolated from a cheaper arm, not from a
  prefill, not from the other dataset.
- `floor N` is the smallest sample at which the row is worth printing. Choose it
  from what the row has to show, not from a power calculation. When the source's
  own numbers put two variants close together, no N you can afford will separate
  them: print both point estimates side by side anyway, because the comparison
  is the deliverable and the ordering is checkable when the interval is not.
- Sum the hours column and compare it against the hours you actually have, minus
  a reserve for analysis and writing. If the sum is larger, you are
  over-subscribed: delete rows from the bottom now, while the deletion is free.

## Committed-hours arithmetic, at every stage boundary

```
committed = sum(hours of queued entries not yet finished)
remaining = deadline - now - reserve for analysis and writing
free      = remaining - committed
```

`free`, not `remaining`, is what pays for a new row. When `free` is negative the
queue is fiction below some line — find the line, and treat every entry under it
as unscheduled rather than as scheduled-and-waiting.

For each source-named cell still at N=0: if its floor-N cost fits in `free`,
queue it. If it does not, name the invented row it preempts, truncate or delete
that row, and put the source row in the freed slot. Record the swap with both
prices. Re-run these three lines at every stage boundary; design-time N is a
guess, realised N is a fact, and it moves the answer in both directions.

## Launch before you finish auditing the design

The queue starts consuming the clock when the port passes its smoke test, not
when the design document stops being revised. Hours spent auditing a plan,
hardening guards or tuning your own internal scorers are hours the queue is idle
— and they are the hours the missing row needed. If the run ends with measured
compute far below wall clock, that gap is where the empty cells went.

## Checklist

- [ ] One ledger row per (condition x slice) the source or the brief names,
      written before any row of mine exists, sorted source-first.
- [ ] Per-item cost measured on real items of that cell, on that slice.
- [ ] Floor N chosen per row and justified by what the row shows.
- [ ] Planned hours summed against available hours at design time; if
      over-subscribed, rows deleted from the bottom before the run starts.
- [ ] Runner launched as soon as the port passes, not after the design review.
- [ ] `free = remaining - committed` recomputed at every stage boundary, with
      the realised N read off the checkpoint.
- [ ] Before writing: no source-named cell at N=0 while any invented row has
      N>0. If one is, either run it at floor N or delete the invented row and
      say in the report that you did.
- [ ] The ledger ships in the report with realised N per row, and the measured
      price that excluded any row still empty.

## Why this is here

Runs lose their heaviest criteria to conditions that were affordable on the
slice that mattered and were never budgeted. The rationale for the cut is
usually correct arithmetic against the wrong denominator and the wrong slice,
and the report that names the cut honestly scores like the report that never
mentions it: a named absence is an absence.
