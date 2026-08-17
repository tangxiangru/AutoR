---
name: late-budget-goes-to-the-task-not-the-method
description: Use at the head of the analysis stage and again during the writing stage's review passes, whenever a figure slot, an attempt or a redraw is still available. Covers re-deriving the reporting slate from the result tables that now exist rather than from the design note, why a label column joined for another purpose is a reporting axis you already paid for, how to rank a spare exhibit against the task's descriptive clauses, and why a review pass that only finds bookkeeping spends an attempt for nothing.
stages: 06_analysis, 07_writing
---

# The last slot goes to the task, not to your method

A plan frozen at study design is rarely a hard ceiling. Runs add to it — an extra
panel appears at analysis, a review pass has attempts left, a figure gets
redrawn. So the question is not whether you may add. It is what the addition gets
spent on, and the default is wrong.

By analysis you have spent two stages arguing with your own method: a sensitivity
grid, a null, a diagnostic, a robustness check. Those have an advocate. The
task's descriptive clauses — *where*, *which*, *for whom*, *how much of each* —
have none. They carry no hypothesis, so a hypothesis-allocated plan gave them no
slot and no headline number, and the coverage table discharged them by pointing
at whichever panel was nearest. With one slot left, the run adds a second defence
of its instrument and ships with no exhibit for a clause in the task's first
sentence.

## Two lists, at the head of analysis

Fifteen minutes, derived from two things, neither of which is the plan.

**List A — the task's clauses, verbatim.** Split the task statement at its verbs
and conjunctions and keep every clause, including the ones that read as framing.
Mark the descriptive ones. They are graded like the analytical ones, and they are
exactly what a hypothesis-allocated plan drops.

**List B — the axes that now exist.** Read the columns of the result tables on
disk, not the design note. Every categorical axis and every level of it:
conditions, regions, classes, models, periods, subsets. Include levels that
arrived late by derivation or interpolation — a level design believed impossible
is the commonest silent hole, because nothing reopens the slot that was narrowed
around it.

**Include every label column you joined for another purpose.** If you attached a
country, a site, a cohort, a family or a class to every row in order to compute
one aggregate somewhere, that label is a reporting axis and you have already paid
for it. It goes unused because the join lives in one arm of the analysis and the
primary result table lives in another; nothing is broken except that nobody ran
the groupby. Every statistic on that table can now be reported per label for the
cost of one line.

## The standard for a descriptive clause

An overview that renders each unit at one pixel does not discharge a *where* or
*which* clause. Neither does a share appearing as a reference column inside a
table about something else, nor a name that occurs only in prose. What discharges
it is an exhibit a reader can read names and numbers off, a ranked table of the
leading entities with the values printed on it, and those leaders named in the
caption and in the abstract.

## Ranking the addition

When a slot, an attempt or a redraw is available, rank candidates:

1. a task clause with no exhibit at all;
2. a task clause whose only exhibit is a pooled aggregate;
3. an axis one level short of the levels that now exist;
4. a result already published, drawn better;
5. a defence of your method — a null, a sensitivity, a diagnostic.

A second exhibit arguing about your instrument ranks below the first exhibit
answering a clause. That ordering is the whole page.

## Adding without losing the plan's audit trail

The plan's value is that results were not chosen after being seen. Keep it by
recording an addition exactly the way you record a drop: new slot id, source
artifact, one-line reason, and the clause or axis level it covers. You are adding
coverage of something the task already declared, not promoting a result you liked
the look of, and writing the reason down is what makes that difference visible to
a reader.

## The review pass has the same failure

Late review passes generate findings about entry counts, a stale timestamp, an
index whose file count disagrees with the directory by one. Those are real, and
they are bookkeeping. A pass whose findings are all bookkeeping consumes an
attempt and changes nothing that is graded.

Require at least one finding per pass about the content of the deliverable, in
one of two forms: "clause X has no exhibit" or "axis Y is one level short". If
neither is true, say so explicitly — that is a finding too, and it is what
licenses spending the remaining attempts on prose.

## What this extends

This page is only about *which* addition wins. For what to put in it:
`earth-report-the-lattice-and-show-the-field` for per-stratum tables, zoomed
panels over the places a result names, ranked entities and numbers printed inside
the panel; `draw-the-source-figure-panel-for-panel` for deriving panels from the
source's rendered figures and filling slots before hypotheses claim them;
`publish-what-the-run-already-computed` for the same sweep run over files instead
of axes; `cover-what-the-task-named` for building list A at design time.

## Before you finish

Walk A and B. For every clause and every axis level, name the file and the panel.
Anything whose answer is "a table", "prose", "the neighbouring panel" or "the
caption mentions it" is a hole — and the cheapest one left in the run, because
the data is already on disk.
