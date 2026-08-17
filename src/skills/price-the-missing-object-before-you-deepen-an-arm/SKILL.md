---
name: price-the-missing-object-before-you-deepen-an-arm
description: Use at experimentation, analysis and writing, when a run that has a deliverable plan and an automatic coverage or completeness check. Covers auditing coverage against the object a reader opens rather than the path a checker sees, pricing every missing exhibit in wall-clock against the arm you are still deepening, and re-owning the obligations of a stage that was skipped or amended mid-run.
stages: 05_experimentation, 06_analysis, 07_writing
---

# Price the missing object before you deepen an arm nobody asked for

A long run rarely fails to produce a missing exhibit because it ran out of
budget. It fails because the exhibit was never on a list that anything checked,
and because nothing put a wall-clock price beside it while there was still
budget to spend.

Two mechanisms make that invisible. The first is a coverage check satisfied by
paths: every named deliverable maps to a file, every file exists, green. The
second is a plan slot filled by whichever arm happened to emit an artifact of
roughly the right file type. Together they will certify a run whose central
deliverable does not exist.

## 1. Audit on objects, not on paths

For every deliverable the brief names and every slot the plan opened, write the
*object* down before you write a filename:

- its kind - a rendered sample, a verbatim output, a curve with named axes, a
  table with named rows;
- the input condition it has to be under - the source's own input, the shipped
  file, the named benchmark;
- what it sits beside - the source's published value, panel or printed answer.

Then bind a file to it and open the file. The test for the row is: *if a reader
opens only this file, can they tell whether the system did the named thing?*
"The path exists" is not that test, and a JSON of shapes, counts or configuration
does not stand in for a capability the brief named among its outputs.

Any slot whose own description says a number cannot replace it - a sample, a
transcript, a picture of a field - is a slot no filename discharges. Re-open
those rows every time the arm that feeds them changes.

## 2. Put a price on every gap

- Measure the per-unit cost of each production step **once, early**, and write it
  down: seconds per generated sample, per decode, per fit, per render. You need
  that number to make the trade later, and by then the run is busy.
- At every stage boundary after implementation, re-diff planned objects against
  what is on disk. Give each gap the wall-clock price of closing it. Sort
  ascending.
- Spend the tail of the budget from the top of that list. A handful of missing
  exhibits at minutes each will routinely be cheaper than one more hour of the
  arm currently running, and they are the ones the brief asked for.
- Make the trade explicit in one sentence with both prices in it: an extension
  nobody asked for, going deeper, against a named deliverable that does not
  exist. See `the-reproduction-is-a-hypothesis` for the budget ordering and
  `cover-what-the-task-named` for the list this diff runs against.

A deliverable that costs minutes and is still missing at submission was never
priced against anything. The defect is the missing price, not the shortage.

## 3. Re-own the obligations of a stage that did not run

Stages get skipped, exhaust a retry budget, or get amended in passing. Their
obligations do not leave with them.

- When a stage ends in a stub, a skip or an auto-continue, read that stage's own
  brief before the next stage starts and list what it was supposed to emit. Carry
  every item forward under the next stage's name, or record it as dropped with a
  reason.
- A plan amendment made while preparing something else is the same case. A slot
  re-pointed after design is re-checked against the deliverable it was created to
  carry, not against the artifact that now happens to fill it.
- The last stage that can still spend compute owns the gap list. If the writing
  stage is drawing figures an earlier stage was supposed to draw, it has
  inherited that stage's audit as well as its plots.

## Before you finish

1. Planned objects against disk: every row present, or dropped with a reason and
   a price beside it.
2. For each capability the brief names, name the single file a reader opens to
   see it. If the answer is a directory, a manifest or a coverage report, that
   capability has no exhibit.
3. Every gap you chose not to close carries its price and the thing you bought
   instead.
4. Every automatic coverage or completeness check that is green: open one file it
   passed and confirm the object is what the row promised. A checker that reads
   paths cannot tell you this.
