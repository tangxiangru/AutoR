---
name: the-results-panel-is-not-where-the-run-argues-with-itself
description: Use at study design when the figure plan is written, at analysis when that plan is executed, and at writing. Covers keeping the figure inventory amendable once the data has actually been parsed and fitted, giving the run's own provenance audit its own figure and section instead of the foreground of a results panel, and writing panel titles as physical statements rather than internal identifiers.
stages: 03_study_design, 06_analysis, 07_writing
---

# The results panel is not where the run argues with itself

Two things compete for the foreground of a results figure: the result, and the
run's own bookkeeping — the hypothesis it was registered against, the parsing
dispute it had to settle, the validity finding it answered. The bookkeeping is
real work and often the best work in the run. On the panel it displaces the
physics, and the panel is what the result is read from.

`draw-the-source-figure-panel-for-panel` covers who owns a slot when the plan is
first written. This skill covers what happens to that plan once the data
arrives, and what else is allowed onto a panel the plan already granted.

## Failure one: the plan was frozen before the data was understood

A run wrote its figure plan at the end of study design, one entry per slot, each
entry naming the series that slot would carry and the internal hypothesis id it
served. Two of six slots adjudicated questions the run had invented. No slot
said "reproduce the experiment the task names". The series lists in that file
omitted most of the supplied data.

Nothing downstream could repair it. The analysis stage opened by scoping itself
to "draw the declared figure slots at exactly the filenames the plan commits
to". The writing stage made eight attempts and changed no series list. Every
figure in the plan was drawn, on schedule, to specification, from a plan whose
inventory was wrong — and the loss is traceable to a single file with a
timestamp, written before a single array had been fitted.

A pre-registered *hypothesis* is a commitment you keep. A pre-registered *figure
inventory* is not the same object: it is a prediction about which pictures will
be worth showing, made at the moment you knew least about the data.

## Failure two: the audit moved into the foreground

The same run found a genuine ambiguity in how the supplied file mapped onto its
axes. It drew both readings on its highest-weight results panel — the primary
series, a second series for the alternative parse, an annotation marking where
they diverge, a legend of eight entries — and titled the panel with the
hypothesis id and the two competing fitted numbers. Roughly half the panel
adjudicates the run's own parsing question. Other panel titles are verdict
strings of the same kind, so even the panels carrying physics read as audit
artifacts.

A comparator with the same ambiguity, the same defects and the same scepticism
put all of it in one forensics figure and one numbered section, then left the
results panels to the measurement. Its panel titles are physical statements.

## What to do

1. **Write the plan with an amendment clause.** In the plan file, one line:
   *this inventory is provisional until the arrays are parsed and fitted;
   amendments are recorded in `notes/plan_amendments.md` with the date, the
   slot, and the measurement that forced them.* Zero amendments by the end of
   the run is a signal, not a virtue.
2. **Carry a standing question into every stage after design**: does what I just
   measured change what belongs on a panel? Answer it in one line in the stage's
   own notes. A stage that defines its job as executing the plan verbatim cannot
   ask it.
3. **Do not let a filename list act as a scope gate.** Committing to filenames
   is fine; committing to *only* those filenames turns an early guess into a
   ceiling. Adding a panel late is cheap. Shipping without one is not.
4. **The audit gets its own figure and its own section.** Parsing ambiguities,
   ragged inputs, mislabelled arrays, self-consistency checks and the answers to
   your own validity findings: one forensics figure, one numbered section, and a
   single sentence from the results section pointing at them. This is the
   cheapest structural change available and it protects every other panel.
5. **When two readings of the input are both defensible**, choose one on stated
   grounds, run the whole analysis on it, and put the other in the forensics
   figure plus one sensitivity line ("under the alternative mapping the exponent
   moves from a to b; every conclusion below survives"). Two foreground series
   for one measured quantity tells a reader you did not resolve it.
6. **Panel titles and captions are physical statements.** A title names the
   quantity, what it is compared against, and the direction of the answer; at
   minimum it names the quantity and the control variable. An identifier — a
   hypothesis tag, a finding number, an obligation id, a mapping letter — and a
   bare fitted number belong in the caption's last clause at most, and usually
   in the appendix. A reader who does not have your ledger cannot read a title
   written in it.
7. **Price the figure budget.** Count the panels that adjudicate questions you
   generated against the panels that carry an experiment the task names. If the
   first number is not the smaller one, the budget went to the wrong questions.
   The same count applies to the code: when the files that verify, audit,
   discharge and ledger outnumber the files that measure and draw by several to
   one, the deliverable is being built out of the leftovers.

## The check

Before you finalise: for each experiment or output the task names, write the
figure file and panel letter that carries it. Any row answered with "a table",
"a headline number", "the overview figure" or "prose" is a result you did not
draw.

Then read your own panel titles and axis labels end to end. Count how many name
a physical quantity and how many name an internal identifier. If a reader
without your notes cannot tell what a panel shows from its title, the panel is
addressed to you.
