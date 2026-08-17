---
name: information-paste-the-output-not-the-pass-rate
description: Use at analysis and writing whenever a result takes the form "the system produced X" — a model transcript, a transcribed formula, a caption, an extracted field, a generated snippet. Covers pasting the literal output into the report body, which outputs and how many, why a string rendered into a figure is not in the report, and the grep that checks it.
stages: 06_analysis, 07_writing
applies_when: visual question answering
---

# The output is the evidence; a rate against your own predicate is not

When the claim is that a system emitted something particular, the something is
the evidence and nothing stands in for it. Not a pass rate against predicates you
wrote. Not a normalised edit distance. Not the sentence "the greedy decode
normalises to the published target at edit distance 0.0", which is a claim about
a string a reader has still never seen.

This is the cheapest result in the report — the text is already on disk, it costs
five lines — and it is the one most reliably left out, because a run that has
built a scoring harness naturally reports the harness's output instead of the
model's.

## What to paste

For each demonstration, three fenced blocks in the section that discusses it:

* **the greedy or modal output**, in full, labelled with decoding settings and
  seed;
* **the best output of your grid**, if it differs, labelled with how it was
  selected;
* **one representative failure**, so the reader can see what going wrong looks
  like.

Untruncated. If the modal output stops mid-sentence, your token budget is part of
the measurement rather than part of the model: re-decode with the cap lifted,
quote the complete text, and report both lengths. A qualitative capability judged
on an output your own budget cut off is not judged on the model.

Quote the source's own printed output in the same place. Two blocks under one
heading is the entire comparison, and it is what a reader means by "did it
reproduce".

## Prose, not only the figure

A string rendered into a PNG is not in the document. It is invisible to a text
search, invisible to anyone reading the markdown without opening the panels, and
invisible to any downstream reader of the report file alone. Panels are for the
input, the layout and the rates; **the literal output goes in the body text**. If
a transcribed expression, an extracted field or a generated snippet appears only
inside `report/images/`, the report does not contain it.

## The rate goes beside, never instead

"p1 = 0.75 for recovering both embedded strings" tells a reader about your
lexicon. The two strings, quoted out of a decode, tell them about the system.
Publish both, transcript first, and say which predicate produced the rate.

## Before you finish

List every literal token the demonstration turns on — each string the system was
asked to read out of the input, each symbol of the expression it was asked to
transcribe, each field name it was asked to emit. Grep the report for each one. A
token with zero hits, or whose only hit is a bibliography entry, is a result you
measured and did not deliver.

## Why this is here

Measured on a unified understanding-and-generation reproduction with two graded
demonstrations. The formula criterion names a specific LaTeX string; `A_n` occurs
**zero** times in that run's `report.md` — the transcription exists only inside
`images/ocr_formula.png` — and the criterion scored **41.7** against **51.0** for
a plain agent whose report prints the string once in prose. The meme criterion
names two embedded strings; "Single Visual Encoder" occurs **zero** times in the
report and "Decoupling Visual Encoding" once, in the reference list, as part of
the paper's title. That criterion scored **26.7** against **38.3**. The run's own
`outputs/rows/h5_janus-1.3b.jsonl` holds fifteen decodes, the first of which
contains both strings and reads the muscular dog as "more control and
flexibility" against a "more centralized and less flexible" single encoder. No
decode is quoted anywhere in the report, and that one was cut off mid-sentence at
`max_new_tokens=160` — 7 of its 13 grid rows were, the run's own
`outputs/h5_hand_adjudication.json` recording that in the paper's printed answer
the claim under test is the final sentence.
