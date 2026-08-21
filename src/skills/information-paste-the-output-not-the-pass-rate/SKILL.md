---
name: information-paste-the-output-not-the-pass-rate
description: Use at analysis and writing whenever a result takes the form "the system produced X" — a model transcript, a transcribed formula, a caption, an extracted field, a generated snippet. Covers pasting the literal output into the report body, which outputs and how many, why a string rendered into a figure is not in the report, and the grep that checks it.
benchmarks: researchclawbench
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

Untruncated. If the modal output stops mid-sentence, your token budget is part
of the measurement rather than part of the model: re-decode with the cap lifted,
quote the complete text, and report both lengths. If lifting the cap moves
nothing, say so in the same breath — a budget you ruled out is a result, and it
is worth a clause, not a paragraph.

Quote the source's own printed output in the same place. Two blocks under one
heading is the entire comparison, and it is what a reader means by "did it
reproduce".

## Prose, not only the figure

A string rendered into a PNG is not in the document. It is invisible to a text
search, invisible to anyone reading the markdown without opening the panels, and
invisible to every reader who is handed the report file on its own — which is
how a text-only reader, human or automatic, always reads it. Panels are for the
input, the layout and the rates; **the literal output goes in the body text**. If
a transcribed expression, an extracted field or a generated snippet appears only
inside `report/images/`, the report does not contain it.

## The rate goes beside, never instead

A pass rate "for recovering both embedded strings" tells a reader about your
lexicon. The two strings, quoted out of a decode, tell them about the system.
Publish both, transcript first, and say which predicate produced the rate.

## Boundary

`evidence-not-assertion` governs numbers: every quantity in the report traces to
a file this run wrote. This is the case where there is no quantity to trace — the
claim is qualitative, the artifact is a string, and a number attached to it is a
summary of the string rather than the thing being claimed.

`information-exhibit-the-intermediate-objects` says the stage outputs and the
verbatim transcript belong in the single report document. This is how: which
outputs, how many, what to do when the modal one was cut off, the rule that a
string rendered into a panel is not in the report, and the check below.

## Before you finish

List every literal token the demonstration turns on — each string the system was
asked to read out of the input, each symbol of the expression it was asked to
transcribe, each field name it was asked to emit. Grep the report for each one. A
token with zero hits, or whose only hit is a bibliography entry, is a result you
measured and did not deliver.

## Why this is here

Measured on a unified understanding-and-generation reproduction with two graded
demonstrations, against a plain agent on the same task.

The formula criterion names a specific LaTeX string. `A_n` occurs on **zero**
lines of that run's `report.md` — the transcription exists only inside
`images/ocr_formula.png`, and a text criterion is graded on the report with no
images attached, so what the grader read was the run's own assertion of "a
normalised exact match at edit distance 0.0". It scored **41.7** against **51.0**
for the plain agent, whose report prints the string once, in prose, on one line.

The meme criterion names two strings embedded in the shipped image. "Single
Visual Encoder" occurs on zero lines of that report and "Decoupling Visual
Encoding" on one, the bibliography entry for the source paper; the criterion
scored **26.7** against **38.3**. The run's own
`outputs/rows/h5_janus-1.3b.jsonl` holds fifteen decodes, the first of which
contains both strings and reads the muscular dog as "more control and
flexibility" against a "more centralized and less flexible" single encoder. Not
one decode is quoted anywhere in the report.

That decode does stop mid-sentence at `max_new_tokens=160`. The cap was not the
reason, and the run had already shown it:
`outputs/h5_uncapped_sensitivity.json` re-decodes the same image, prompt and
seeds at 512, records nothing still truncated at the lifted cap, and returns the
same rates. The text was complete enough to read, on disk, and measured twice. It
was never pasted.
