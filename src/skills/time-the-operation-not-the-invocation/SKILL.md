---
name: time-the-operation-not-the-invocation
description: Use at implementation and experimentation whenever a runtime, throughput or speed-up ratio between two programs is being measured, and again at analysis before any ratio is quoted — especially one that lands below a published figure. Covers the fixed-cost decomposition, the flat-cost-versus-size signature of a mis-timed harness, the conditions table both arms must match, and the per-instance head-to-head.
benchmarks: researchclawbench
stages: 04_implementation, 05_experimentation, 06_analysis
---

# Time the operation, not the invocation

## What goes wrong

You need a speed comparison, so you wrap each tool's documented one-shot command
in a timer and divide. That command is a convenience wrapper: it builds a
temporary index or database from the inputs, writes and deletes scratch files,
forks helpers, tears the whole thing down. The published comparison timed the
algorithm with the index already built, inputs on local disk or in memory, at a
stated thread count. Your ratio is then largely a measurement of your own
harness, and it lands materially below the published one.

The signature is unmistakable once you look for it: **your tool's per-run cost
is nearly flat as the input grows, while the baseline's climbs steeply, and the
ratio inverts on the smallest inputs.** A run reporting that its fast method is
slower than the incumbent on small cases has usually measured a startup cost,
not an algorithm. Reporting that inversion as a property of the benchmark's size
mix is the same mistake, written more confidently.

Two cheaper versions of the same error: timing wall clock for one arm against
CPU time for the other, or under contention only one arm pays; and putting
scratch or inputs on a network filesystem for one arm.

## What to produce

### 1. A cost-versus-size table, before any ratio

For **both** arms, median per-run cost and IQR at five or more size points
spanning at least a tenfold range in the natural size variable (length, number
of parts, product of the two sizes). Then read it:

- If one arm's cost is flat across that range, its cost is dominated by a
  constant. Measure the constant directly — run the tool on the smallest legal
  input, or on a trivial pair — and call it `t0`.
- Report `t - t0` beside `t`, and say which of the two is comparable to the
  published number.
- If the ratio crosses 1 inside your size range, say which side of the crossing
  the published measurement was taken on.

This table is recomputable from a benchmark you have already run. It costs one
groupby, and it is the cheapest thing in the run that can invalidate a headline
number.

### 2. A conditions table, filled in for every arm

| | arm A | arm B |
|---|---|---|
| wall or CPU seconds | | |
| threads | | |
| index/database build inside or outside the timer | | |
| scratch and input filesystem (tmpfs / local disk / network) | | |
| concurrent jobs on the host during the measurement | | |

Any row that differs between arms is a confound. Equalise it and re-run; a short
re-measurement is cheaper than a caveat, and a caveat does not restore the
number. CPU seconds from the process's own resource usage (`os.wait4`,
`getrusage`) rather than wall clock removes most host-contention noise at no
cost, and it is the clock most published single-core numbers are on — check
which one the source used and match it.

### 3. The per-instance head-to-head

A pooled median over a benchmark is a statement about that benchmark's size mix,
which you did not choose. For the instance the task actually names, run both arms
on that instance alone, under the conditions table above, and report both costs
and their ratio as its own line in the results section. Do the same for every
control instance you report. One sentence per instance: "on this input, A took
X s and B took Y s, single core, index pre-built." A stratified median table
does not discharge this; the question was about the named input.

### 4. If a shortfall survives all of that

Then it is a result, and `close-the-gap-to-the-published-number` governs how it
is written: the eliminations by name, not a list of plausible causes. Two things
specific to timing go with it — the decomposition (`t0` and `t - t0`), and a
line-by-line diff of your invocation against the flags the source's methods
section names, each missing flag listed with the direction it would move the
number.

One sentence is never acceptable in that section: that the source's faster
configuration exists in your build and was simply not run. If the flag is
available, re-run with it. Documenting a configuration you could have used and
did not is not a limitation, it is an unfinished measurement.

## Checklist

- [ ] Cost-versus-size table for both arms exists before any ratio is quoted.
- [ ] `t0` measured directly for any arm whose cost is flat in input size.
- [ ] Both `t` and `t - t0` reported; the one comparable to the published figure identified.
- [ ] Conditions table filled for every arm; differing rows equalised, not annotated.
- [ ] Same clock and same thread count on both sides, both stated in the report.
- [ ] Scratch and inputs off the network filesystem for both arms.
- [ ] A single-instance head-to-head for the instance the task names, and for each control, in the results section.
- [ ] Every flag in the source's methods paragraph either used, or named with the direction it would move the number.
- [ ] No sentence in the report says a faster available configuration was not run.
