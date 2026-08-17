---
name: the-firing-instance-gets-the-full-record
description: Use at study design, and again at analysis and writing, when the supplied instance comes back at background — no match, near-zero score, one part matched out of many — and the run is turning into a careful demonstration that nothing happened. Covers the equal-depth artifact rule for the instance where the method does fire, the ordering against the graded item, the four-rung ladder in one paragraph, and measuring rather than inferring the mechanism behind the negative.
stages: 03_study_design, 06_analysis, 07_writing
---

# The instance where the method fires gets the full record

## What goes wrong

The supplied inputs come back at background — no match, a near-zero score, an
empty result file, one part matched out of many — and the run does the honest
thing. It builds a null distribution, places the supplied instance in it, and
writes a careful section explaining that the negative is the correct answer.

That is usually right, and it is not the failure. The failure is what happens to
the *other* instances. Almost every run in this situation does run a positive
case; it is cheap and obvious. The positive then reaches the report as one
clause in a methods paragraph and one row in an appendix summary table, while
the negative gets a results section, a figure and its own appendix. Every
property the task asked about — a correspondence over many parts, per-part
solutions that agree with each other, detection at the edge of a detectability
regime, a cost advantage on a real workload — is observable *only* where the
method fires, and the run's one firing instance was compressed to a single line.

The gap this closes is reporting depth, not whether controls exist. Diagnose it
by counting: how many characters of the report describe the negative, how many
describe the case where the method worked.

## What to produce

### 1. The equal-depth rule, as an artifact rule

Whatever artifact the supplied instance gets, every other instance you ran gets
the identical artifact: same table, same columns, same per-part rows, same
transforms, same auxiliary statistics, same cost line, in the results section.
An appendix row does not discharge it, and neither does a summary figure.

Make it mechanical. Before writing, list the artifacts you produced for the
supplied instance — the per-part record, the across-row statistics, the
head-to-head cost, the threshold statement — and against each one name the file
that holds the same artifact for each other instance. Empty cells are filled by
re-running one script with a different input, not by a sentence.

### 2. Ordering: the supplied instance first, the ladder is additive

`the-supplied-item-is-the-graded-unit` sets the ordering and this skill does not
override it. The supplied instance's own numbers are reported first, in full,
under its own identifier, *including* the ones that came out badly. The ladder
is additive. Never present a firing instance as though it were the supplied one,
never merge their numbers into one row, and label every table and figure panel
with which instance it shows. Promoting the case you got right in place of the
case you were handed is selecting the exhibit on the outcome.

### 3. The rungs, named at design time

Four, written down before results exist:

1. **Self / identity** — the supplied input against itself. Fixes the trivial
   upper bound and catches a broken parser the moment the number is not trivial.
2. **Known positive** — an instance whose relationship is documented
   *independently of your run*: an example the source released, a catalogued
   relative of the supplied item, or a top hit from a database search whose
   relationship you then verify against an outside record. Write down how you
   established it and cite it. A positive certified only by your own tool's
   score is circular.
3. **The supplied instance**, whatever it turns out to be.
4. **Background** — a sample of comparable random instances.

Two operational rules carry the weight here. Every rung goes through one script,
one set of flags, one output schema, one timer; a rung that needs a special case
is itself a finding. And rung 2 is named before any of it runs — if you cannot
name it, that is a study-design gap, closed with one search, not with a
limitation paragraph.

### 4. Score every rung against a named threshold

Where your field has a conventional decision cut-off for the headline quantity,
state each rung's value relative to it and cite where the cut-off comes from.
The upper bound from rung 1, the firing rung's value, the supplied instance's
value and the background's spread belong in one small table with the cut-off
drawn on it, so the reader can see which rungs clear it.

### 5. Say why the supplied instance is background, from a measurement

Name the measured property of the inputs that makes the method return
background — a composition or size mismatch, a missing partner, an out-of-scope
component, a preprocessing step that removed the relevant part — and print that
measurement. Inferring the mechanism from the low score is a guess wearing a
result's clothes, and it is the one claim in this section a reader will check.

## Checklist

- [ ] Four rungs named at design time; rung 2's relationship established outside your own run and cited.
- [ ] All rungs run through one script, same flags, same output schema, same timer.
- [ ] Artifact-by-instance matrix built before writing; no empty cells left unfilled.
- [ ] The firing instance's full per-part record is in the results section, not an appendix row.
- [ ] Its auxiliary statistics and its cost are reported, not only its headline score.
- [ ] The supplied instance is reported first and in full, under its own identifier.
- [ ] Every table and panel labelled with the instance it shows; no merged rows.
- [ ] All rungs placed against a cited decision threshold in one table.
- [ ] The mechanism behind the negative measured and printed, not inferred from the score.
