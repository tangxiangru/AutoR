---
name: the-headline-entry-is-the-canonical-outcome
description: Use at study design when a decision rule is being frozen, and at analysis and writing when a capability the source demonstrated by example is about to be summarised by a rate you introduced. Covers what the summary row, the abstract, the section heading and the figure title are allowed to say, and calibrating a scoring predicate against the reference answer before it decides anything. Extends information-exhibit-the-intermediate-objects.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# The headline entry for a demonstrated capability is its canonical outcome

Turning a one-sample demonstration into a rate over predicates frozen in advance
is good work. It is also a *second* result, and it is only ever the second one.
The first is what your system produced under the source's own input, in the
source's own condition.

`information-exhibit-the-intermediate-objects` covers getting that object into
the report body verbatim. This skill covers the layer above it: the summary
table, the abstract, the section heading and the figure title - the four places
a reader goes to find out what happened. When those carry your rate instead of
the canonical outcome, the object sitting further down the document does not
save it. The summary entry is read as the capability's score, because that is
what a summary entry is for.

## The failure shape

The canonical run reproduced the source exactly, and that fact survives in the
report as a subordinate clause in a sentence about a figure, or as a panel
subtitle. Meanwhile:

- the summary table's row for that capability is a fraction over perturbations
  the source never claimed to survive, with an empty "published" cell, because
  the source never reported such a rate;
- the section's opening sentence is a verdict about robustness rather than a
  statement of what the system produced;
- the figure title names the branch the run's own hypothesis landed on.

Each of those is a slot where the run's instrument has displaced the source's
result.

## Rules

1. **Summary table, abstract, key-results list.** The entry for a capability the
   source demonstrated states the outcome under the source's condition, in the
   source's terms. A rate you introduced goes in an adjacent column or the next
   sentence, always with its n and the perturbation named in the same breath. A
   bare fraction in the headline position is read as the score for the
   capability.
2. **An empty "published" cell is a warning.** If a comparison table has a row
   for a capability whose published column is blank because the quantity is
   yours, check that the same capability also owns a row whose published column
   is not blank. If it does not, you have replaced the comparison the reader came
   for with a measurement of your own.
3. **Headings and figure titles name the capability and what it did**, not the
   branch your hypothesis reached. Nobody outside the run knows your hypothesis
   labels, and a summary of your extension is not a summary of the reproduction.
   Canonical outcome in the first clause, qualifier in the second.
4. **Order inside the section**: the canonical output, then the distribution,
   explicitly labelled as an extension the source did not run.

## Your predicate set is an instrument, and it has error

A rule written from the paper's *prose* is not a rule about the paper's *result*.
Before a predicate decides anything:

- **Run it over the reference answer.** The source's own printed output for that
  demonstration, and any reference text the task supplies. If your rule scores
  the target answer as a failure, the rule is testing for something the target
  does not contain, and every number it produces is a fact about the rule.
- Report that calibration in one line beside the rate: what the predicate returns
  on the source's own answer, not only on yours.
- If the rule cannot be changed because it was frozen, keep it and report what it
  scores on the reference, and make the sentence a reader takes away describe
  what your output actually said.
- A rule that fires on a property the source never claimed is not evidence of
  failure. Trace each keyword in it to the source's printed output before you
  write "inverted", "fails" or "does not reproduce".

Freezing a decision rule at design time is a commitment about the *decision*. It
was never a commitment to let the rule write the prose.

## Before you finish

Cover the body of the report and read only the abstract, the summary table, the
section headings and the figure titles. For each capability the source
demonstrated by example, ask what that reduced document says the system did. If
the answer is a fraction, a verdict on an internal label, or nothing at all,
rewrite that entry before you touch anything else.

Then, for every predicate whose output reached the report, record beside its rate
what it scores on the reference answer.
