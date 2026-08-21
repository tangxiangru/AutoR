---
name: extract-the-pdf-text-layer-then-read-every-figure
description: Use at literature survey, and again as a study-design gate, when the source demonstrates a capability by example - generated samples, transcripts, worked cases, before/after pairs - and those inputs are printed inside the figure graphics. Covers extracting every obtainable PDF's text layer before calling an input unrecoverable, building the figure inventory as the coverage denominator, opening as images only what the text layer misses, and the demonstration ledger study design has to spend.
benchmarks: researchclawbench
stages: 01_literature_survey, 03_study_design
---

# Get the source as a PDF and read its text layer before you call an input unavailable

A paper's quantitative results live in its tables and its prose. Its qualitative
results usually do not: the prompt, the query, the input case and the system's
printed answer are typeset *inside the figure graphic*. Fetch the article as
HTML and you get the caption and the paragraph that cites the figure - enough to
write "the source gives qualitative examples of this capability", not enough to
run a single one of them.

What happens next is the expensive part. The arm gets designed anyway, and it is
sourced from whatever inputs were machine-readable: a benchmark's prompt list, a
public evaluation split, the one file the task happened to ship. The
substitution measures a real thing and reproduces nothing, and the exhibit a
reader would lay beside the source's own panel does not exist.

The correction is a few minutes of work, in the right order.

## Order of operations

1. **Inventory first, from the rendered source.** List every figure graphic in
   the article body - in HTML, every `<img src=...>` between the abstract and the
   references; in a PDF, every numbered float. The filenames are usually named
   after what they show. That count is the denominator of your coverage line.
2. **Text layer next.** Run a PDF text extractor page by page over every PDF of
   the source you can obtain: the copy the task ships, and the preprint or
   publisher copy of the same work. In-figure strings are frequently ordinary
   text objects positioned over the graphic, so an extractor returns them
   verbatim. Long strings that appear nowhere in the running prose are exactly
   the demonstration inputs and printed outputs you are after. This costs
   seconds, and it is the step that gets skipped because the HTML was already in
   hand.
3. **Pixels for the remainder.** Whatever the text layer does not carry - raster
   panels, screenshots, outlined type - render the page at >=110 dpi and open it
   as an image, or download the figure graphic and open that. Do this for every
   remaining figure, not only the ones you already have a use for.
4. **Fallbacks.** The project page, the model or dataset card, the release
   repository's `assets/` and README, and the appendix frequently carry the same
   showcase inputs as plain text.

Versions differ in which figures they carry. If the shipped copy and the public
copy disagree, take the union and record which copy each row came from.

## The partial read

The failure is rarely skipping the figures. It is opening the ones that match
the files the task shipped, and stopping. The shipped files tell you which
demonstrations you can re-run **with a supplied input**. They say nothing about
which demonstrations the source published, and the half of the brief that ships
no input file is the half that ends the survey with no source material at all.

Read the brief's list of named capabilities against the figure inventory before
you close the stage.

## What to produce

`literature/source_demonstrations.jsonl`, written before the first hypothesis is
drafted, one row per demonstration the source publishes:

```
{"figure": "<figure and panel, as the source labels them>",
 "capability": "<which capability named in the brief it demonstrates>",
 "input": "<the input string or file, transcribed verbatim>",
 "printed_output": "<what the source prints as the result, or the artifact type>",
 "baselines_printed": ["<competitor outputs shown in the same panel>"],
 "settings_printed": "<any run settings printed in the figure or caption>",
 "recovered_from": "text layer | figure image | project page",
 "runnable_here": true}
```

Close the stage with one coverage line: *F figures found, T whose printed strings
the text layer carried, I opened as images, D demonstrations transcribed, K
inputs recovered verbatim.* If T + I is short of F, name the figures you did not
read and why.

## Then spend it

The ledger is an input to study design, not a note. Every row is assigned to an
arm or declined in writing - see `draw-the-source-figure-panel-for-panel` step 2
for slot assignment and `cover-what-the-task-named` for the enumeration it has to
match. Two non-reasons for declining: that the demonstration carries no metric
(a demonstration is reproduced by re-running the input and showing the output,
not by scoring it), and that a benchmark covers the same capability (a benchmark
measures a population; the demonstration is a named case with a published
expected output, and it is the only comparison a reader can make by looking).

An input you could not recover is an open question that names the figure it sits
in. It is never silently replaced by a list you could download.

## Checklist

- [ ] Figure inventory built from the rendered source; count recorded.
- [ ] A text extractor was run over every obtainable PDF of the source before any
      input was called unrecoverable.
- [ ] Every figure the text layer did not cover was opened as an image.
- [ ] `source_demonstrations.jsonl` exists, with verbatim inputs, before Stage 02.
- [ ] Coverage line recorded: found / in text layer / opened / transcribed.
- [ ] Every capability the brief names has at least one ledger row, including the
      ones with no shipped input file.
- [ ] At study design, each row is assigned to an arm or declined with a reason.
