---
name: the-unit-of-analysis
description: Use at analysis and figure planning when the brief names the units its data is grouped into — patients, cells, classes, labs, behaviours — and you are about to report one pooled number over all of them. Covers why the pooled number hides the result, which strata a study of this kind is expected to report, and when an aggregate is the right answer after all.
applies_when: \b(patients?|subjects?|cohorts?|per[- ](cell|patient|unit|class|group|type|neuron|category)|cell types?|each (class|category|cohort|site|lab|condition)|stratif\w*|sub-?group)\b
stages: 03_study_design, 06_analysis, 07_writing
---

# Report at the unit the study is about, not only pooled

A single pooled number is the easiest result to compute and often the least
informative one. If the data distinguishes patients, regions, epochs, conditions,
lead times, molecules or seeds, then the analysis is expected at that level —
and a pooled mean is read as the stratified analysis not having been done.

The failure is specific and common: the study has seven subjects, the report
shows one distribution over all of them, and the question the study existed to
answer — do subjects differ, and how — is unanswerable from the figure.

## What to do

- Find the unit of analysis in the data: the column that says which subject,
  site, condition or fold a row belongs to. It is almost always there.
- Report the per-unit result as the primary view: one panel per unit, or a
  distribution with the units as points, or a table with a row each.
- Then add the pooled number, as the summary of that, not as a replacement.
- Where a unit behaves differently from the rest, say so and give your account.
  That is usually the most interesting sentence in the report.

## When pooling is right

When the claim is genuinely about the population, and you have shown the
per-unit spread somewhere so the reader can judge whether pooling was fair. A
pooled number whose spread is never shown asks to be trusted rather than read.

## The self-check

Look at your main figure. Can a reader tell how many units contributed and
whether they agreed? If not, you have shown a summary and called it a result.
