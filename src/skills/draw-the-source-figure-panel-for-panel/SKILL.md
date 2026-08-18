---
name: draw-the-source-figure-panel-for-panel
description: Use at study design when planning figures for a reproduction, replication or validation task, and again before the report is written. Covers deriving each panel's series list and axis ranges from the source's rendered figure, giving every source result a panel before your own hypotheses claim the slots, and printing the source's named constants as labelled values.
stages: 01_literature_survey, 03_study_design, 06_analysis
---

# Every result the source drew, you draw

A reproduction is read by putting the source's figure beside yours and asking
whether they show the same thing. That is what a reader does with a
reproduction, and it is the only form in which "we got the same answer" is
checkable. Your study design is not the index anyone reads you under: a result
you settled early, or discharged with a headline number, still needs its panel.

## The failure this prevents

A run reproduced a packing theory to 110 of 111 published closed-form values —
more of the paper reproduced than either comparator managed — and scored 18.7
where a plain agent that did less scored 53.4. Every figure slot in its plan was
bound to one of its own preregistered hypotheses, and the paper's *first* result
was discharged as the headline number "110 of 111". That result is a
lattice-path construction carrying two magic-number series. Both were on disk.
Neither was drawn. The word "magic" appears once in the entire report, in a
bibliography entry, and the requirement scored 20 against 55 and 48 for the two
runs that drew it.

The mechanism is not how many panels exist — that run had spare slots, and other
runs in the same batch shipped fourteen panels and still lost the comparison.
The mechanism is **which result owns a panel**. An agreement count and a CDF are
a better summary and a worse exhibit than the panel they replace.

A second shape: a scan panel carried two series where the published panel carries
three, because the run reproduced a caption it had extracted from an older
preprint rather than the rendered figure. The third series was 250 rows on disk
and was already plotted in the neighbouring panel.

## What to do

1. At literature stage write `notes/source_figures.json`: one row per panel of
   every figure the task points at — source figure and panel letter, x and y
   quantities, **the full list of series**, axis ranges, special markers (an
   inferred point drawn open, a shaded band, a hardness line) and the values
   printed on it. Read these off the rendered figure. Extracted captions come
   from whichever version you fetched and routinely disagree with the published
   panel about how many series it carries.
2. Fill figure slots from that list *before* any hypothesis claims one. If the
   plan schema demands a claim id, use `exploratory:reproduce-source-figure-<n>`.
   A reproduction panel is not exploratory in any sense that matters.
3. Ship the source's layout. If the source is one three-panel figure, ship one
   three-panel figure with the panels in that order, so the two can be laid side
   by side without the reader doing translation.
4. Print the source's named constants as labelled values *on the panel* —
   `published 0.04 / ours 0.0400` — with any agreement count beside them, never
   instead of them. A count says how often you agreed; the labelled value is the
   agreement.
5. A supplied or published curve you disqualified stays on the panel, annotated.
   Deleting it deletes the comparison; annotating it adds a finding and keeps
   both.
6. A result you cannot produce — a wet-lab measurement, an instrument you lack —
   still gets a panel: the source's value against your prediction, labelled as a
   proxy.
7. State each panel's key numbers in the prose that introduces it, in the results
   section, early. A figure whose supporting sentence arrives forty thousand
   characters into the report is read on the picture alone.

## Before you finish

Walk the panel list. For each row, name your file and panel and diff the series
lists against the source's. Any row whose answer is "a table", "a headline
number" or "prose" is a result you did not draw.
