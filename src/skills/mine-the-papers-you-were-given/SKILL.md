---
name: mine-the-papers-you-were-given
description: Use when the task ships PDFs in related_work/, at literature stage and before the study plan is costed. Covers reading those papers for the named tools, benchmarks, events and metrics the work will be judged against — as a work list rather than as background — and what to record for each one.
---

# The papers in `related_work/` are a work list, not background reading

A supplied paper is not context. It names the tools the field uses on this problem, the
benchmark events results are reported against, the baselines a number is compared to. Those
names are what a reader checks your work for, and they are sitting in a file you already
have.

## The failure this prevents

It is not that runs skip the papers. Measured across a 40-task batch: every task ships them
(median 4 PDFs, median 250,000 characters of extractable text) and **every run referenced
100% of them**. They are opened. They are read for framing. Then the work list is written
from the task statement alone, and everything the papers name goes unused.

Chemistry_002 is the clean case. `CAPRI` appears **30 times** in its supplied papers and
`HADDOCK3` **22 times**. The two graded requirements that name them — a CAPRI round result,
and the tool's consensus scoring workflow — scored **5 and 0**. The report discusses CAPRI
*as a concept* and never reports a CAPRI result. Life_001's papers name `NetMHCpan` five
times; the requirement naming it scored 5.

The shape is always the same: the run knows the field's vocabulary, because it read the
papers, and produces its own analysis in its own terms beside a literature it has
paraphrased rather than used.

## What to do

1. While the papers are open at literature stage, write
   `literature/named_from_papers.json`: one row per **proper noun** the supplied papers
   attach to a result — a tool (`HADDOCK3`), a benchmark or event (`CAPRI round 57`), a
   dataset, a metric with a name, a scoring function, a public baseline. Carry the paper it
   came from and how many times it appears; something named twenty times is load-bearing
   and something named once may not be.
2. For each row decide, in writing, one of three things: **run it**, **compare against
   it**, or **say why not** — the tool is unavailable, the event has no public data, the
   dataset needs an account. Undecided is not one of the three.
3. Use the source's name in your section heading and in the prose. "We evaluate with
   HADDOCK3's consensus scoring" is checkable; "we use a modular scoring workflow" is the
   same work, unfindable.
4. Report the named quantity in the named units on the named benchmark. A run that
   computes the right thing and reports it against its own private split has not made the
   comparison the field makes.
5. A name you decided not to run still appears in the report, once, with the reason. That
   sentence costs a line and turns an absence into a decision.

## Before you finish

Grep the report for each row's name, with word boundaries. A row with zero hits is a piece
of the field's own vocabulary that you had in hand and did not use — and if you decided not
to use it, the reason is missing too.

Word boundaries matter more than they look: the measurement behind this skill was taken
four times and got the answer wrong three times, once because a substring search counted
`shape` as an occurrence of `SHAP` and produced a whole story about an analysis that is not
in those papers at all.
