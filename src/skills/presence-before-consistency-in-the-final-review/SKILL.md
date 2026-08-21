---
name: presence-before-consistency-in-the-final-review
description: Use at analysis and writing, when a self-review, an adversarial reviewer or a validator loop is generating the items you spend your remaining revision attempts on. Covers why an internal review cannot see a missing deliverable, how to sort review items into presence and consistency, and what a saturated internal quality score is actually measuring.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
---

---
name: presence-before-consistency-in-the-final-review
description: Use at analysis and writing, when a self-review, an adversarial reviewer or a validator loop is generating the items you spend your remaining revision attempts on. Covers why an internal review cannot see a missing deliverable, how to sort review items into presence and consistency, and what a saturated internal quality score is actually measuring.
stages: 06_analysis, 07_writing
---

# A review that reads your artifacts cannot tell you the deliverable is missing

The review loop at the end of a run grades the report against the run's own
outputs: number registers, mirrored artifacts, provenance fields, locator tests,
citation coverage, issue tallies. Every one of those checks is real, and every
one of them is *internal*. None can tell you that a quantity the task asked for
is a row in an appendix instead of a figure, or that a panel answers with the
wrong population. So a report can pass every check the run can run, at a quality
score pinned near the top, and still be missing the thing it is graded on.

`cover-what-the-task-named` builds the produced-or-explained list at design
time. This skill is about the endgame: which of the open items you spend a
finite number of revision attempts on, and what to check that no internal
checker is structurally able to see.

## The failure this prevents

A writing stage consumed every revision attempt it had and was auto-skipped
without ever being approved. The items it spent those attempts on: a register
that said it held one fewer entry than it did; a set of mirrored result files
described as identical when one of them had drifted by a timestamp; one
overclaimed reproducibility sentence. All three defects were real. None of them
was visible to any reader of the report.

In the same attempts the review affirmed that the report's structure was right
and must not be reshuffled, and specifically protected the placement, in the
opening pages, of the run's own novel result — a hypothesis the task had never
asked for. The quantities the task did ask for sat in subsections behind it. The
run's internal candidate scores across those attempts sat in a narrow band above
0.96, moving by thousandths while the loss was structural and unmeasured. It
lost the task, on every graded criterion, to a plain agent whose report was
under half the length.

The reasoning that produces this is sound at every step. Each item is a genuine
defect; fixing it is honest; the register really was wrong. The error is
allocation: attempts are the scarce resource, and every one spent on something a
reader cannot see is one not spent on something the reader is looking for.

## What to do

1. **Run a presence pass before the first revision attempt.** Build it from the
   task statement and the contents of `data/` — not from the run's artifacts,
   not from the plan, not from the hypothesis manifest. For each named output
   and each supplied file: the section, the figure and the sentence that carries
   it. Write it to `notes/presence.md`. Anything you cannot fill is the item at
   the top of the queue.
2. **Sort every open review item into PRESENCE or CONSISTENCY.** PRESENCE: a
   graded thing is absent, answered from the wrong population, or exists only in
   `outputs/`, an appendix or a table. CONSISTENCY: two artifacts disagree, a
   count is off, a locator is stale, a mirror has drifted, a claim overreaches.
   Clear every PRESENCE item before any CONSISTENCY item, whatever order the
   reviewer raised them in.
3. **A consistency defect a reader cannot see is worth a sentence, not an
   attempt.** Withdrawing or qualifying the claim in one line is almost always
   the right trade against rebuilding the artifact — and it is the honest
   version, because the disclosure is what a reader needed anyway.
4. **Treat a saturated internal score as a broken instrument.** If your own
   quality numbers sit in a narrow band near the ceiling across successive
   attempts while items are still open, they are measuring internal consistency,
   which you have already achieved. Stop reading them. Read the report instead
   as a stranger holding only the task statement and `data/`, and ask what that
   stranger cannot find.
5. **The opening belongs to what was asked for.** A result you found and nobody
   requested goes after the requested ones, however much better it is. Check
   what the abstract, the first screenful and the first figure actually contain
   against the presence list, and reorder rather than defending an ordering the
   review has already blessed.
6. **Never let the stage end by exhausting attempts.** Budget them: reserve the
   last attempt for the presence list and nothing else. A stage that runs out is
   a stage whose final state nobody chose, and the version that ships is
   whichever draft the loop happened to be holding.
7. **If you must ship with a known defect, ship with the disclosed consistency
   defect, never with the missing deliverable.** One costs a limitation
   paragraph; the other costs the criterion.

## Before you finish

Name the last three things you changed. If all three were internal — a count, a
hash, a field, a locator — you spent the budget in the wrong place, and the
presence list is still the document to read. Every line of it needs a section, a
figure and a sentence, or an explicit paragraph saying why it does not exist.
