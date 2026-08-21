---
name: energy-publish-the-ordering-when-the-level-fails
description: Use at analysis and again at writing when your absolute values miss their validation target, when a competitiveness or threshold count comes out zero everywhere, or when you are about to answer a 'where / which / identify' deliverable with a variance decomposition or a share. Subordinate to `close-the-gap-to-the-published-number`: publish the ordering in addition to closing the level, never instead of it.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
---

# A failed level check does not withdraw the ranking

Reproductions of quantitative models routinely miss the published level: a
factor of two on a cost, a compressed range, a benchmark you had to invent
because the source set it from an assumption. The level is one result. The
ordering is another, and it usually survives the very error that broke the
level — a multiplicative bias in a shared input, a missing chain component, an
uncalibrated comparator all move every entity in the same direction.

**This is not a licence to stop closing the level.**
`close-the-gap-to-the-published-number` still governs the level: a material
disagreement is a defect owned by this run until an experiment says otherwise,
and the cheap discriminators there — units, population, budget, a
hyperparameter you invented, a one-point sanity case — get run first, while
compute is still open. Publish the ordering *in addition to* closing the gap,
never instead of it. What follows is what to do with the rest of the report
while the gap is open, and what to do if it will not close.

## The failure this prevents

A run reimplemented a cost model, missed the published values by a large factor,
wrote the refutation up honestly, and then reorganised its whole report around
the decomposition it could still defend: how much of the spread is one input
class versus another. Its one domain-wide figure carries a caption saying it
answers that question and never answers where the quantity is lowest. One of
the task's named deliverables was to identify which locations perform best under
the model. The run had evaluated every entity it held. It never printed a ranked,
named list; its best entity is quoted in the report as a row id; and its
competitiveness result is a count of zero, with no statement of what would make
it non-zero or who would cross first — even though it had already run the sweep
that answers that, and had written the per-entity ranked table to disk.

The comparator's levels were wrong too — its surface was compressed against the
published values on the same 1:1 check — and it published the ranked list of
named places anyway. Its ordering tracked the published one closely, and every
criterion about where the quantity is low scored multiples higher.

This is not a failure to remember a deliverable. The deliverable was remembered
and then withdrawn on a validity argument that applied to the level and was
extended to the ranking without ever being tested on it.

## What to do, at analysis

1. **Split your outputs into level quantities and order quantities.** Absolute
   value, absolute margin, absolute share are levels. Rank, top-k membership,
   rank correlation, the ordering of scenarios, the sign of a difference are
   orders. Write the two lists down before you write the results section.
2. **Test the order under the error that broke the level.** Take the input you
   suspect — the miscalibrated mapping, the omitted component, the parameter
   vintage — and sweep it over the range that could explain the discrepancy.
   Re-rank at each point. Report the rank correlation against your base ordering
   and whether the leading k change membership. If they do not, say it in one
   sentence: the level is out by this much, the ordering is stable to that.
   This is your existing sensitivity machinery pointed at rank instead of level.
3. **Publish the ranked list of named things.** Before you build it, look in
   your own outputs directory: a per-entity ranked file usually already exists,
   written for some internal check and cited nowhere —
   `publish-what-the-run-already-computed` is the sweep that finds it. Resolve
   every entity to a name a reader recognises, never a row or cell id; if you
   hold a boundary layer or a catalogue, use it to attach a name to every
   coordinate first. Value, margin against the incumbent, rank, and both ends of
   the list.
4. **A zero count is the least informative form of an answer.** If nothing in
   your domain beats the threshold, report the per-entity distance to it, the
   leaders' margins, and the value of each threshold input at which the leaders
   cross — naming which cross first, in order, per scenario. "None today, and
   once the benchmark input reaches this value the ones that cross are these, in
   this order" answers the question. A bare count of zero does not.
5. **Never let a decomposition stand in for a location.** A variance share
   answers "what drives the differences". A deliverable phrased as *where*,
   *which* or *identify* is answered only by named entities in an order. Report
   both, in the order the task named them, and do not let the more defensible
   result displace the requested one.
6. **An identification argument is a licence to publish, not to withhold.** If
   you proved some quantity is invariant to the defect in your inputs, that
   quantity is exactly the one that must appear as a headline result — and when
   rank is among them, the ranking is a headline result.

## Writing

State the level failure once, early, with its magnitude and direction, together
with what you eliminated and what remains — then keep going. A report that leads
with its own refutation and repeats the caveat beside every number teaches the
reader to discount the results that survived. Each conclusion resting only on
the ordering carries that qualifier in its own sentence, once.

## Before you finish

- Is there a table or figure whose rows are named entities in rank order, with
  values and margins? If not, the where/which deliverable is unanswered whatever
  else you produced.
- For every pass/fail count in the report: is the threshold's value stated, and
  is there a sentence giving the input value at which the count changes and who
  changes first?
- Grep your own captions, section headings and figure titles for "never",
  "cannot", "does not answer", "out of scope". Each is a question you declined
  in writing. Check each against the task's list of deliverables before you
  ship; a caption is read by anyone who reads the figure, and a caption that
  disclaims the deliverable is the last thing you want next to your one
  domain-wide panel.
