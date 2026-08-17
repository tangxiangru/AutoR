---
name: information-run-the-prompt-printed-inside-the-figure
description: Use at literature survey and study design when reproducing a generative model whose paper demonstrates its capability with a figure of samples — text-to-image panels, dialogue transcripts, rendered outputs. Covers recovering the showcase prompts, which the caption and the arXiv HTML do not carry, running them before any benchmark grid is costed, and where the generated artifacts have to land.
stages: 01_literature_survey, 03_study_design, 05_experimentation
applies_when: text-to-image
---

# The showcase prompts are typography inside the figure, and nothing else carries them

A generative model's paper argues its case twice: once with a benchmark table and
once with a figure of samples. The figure's inputs — the prompt string, the
question asked, the system message — are set as small type inside the figure,
above or beside each sample. The caption does not repeat them. It names the
figure and the comparison: *"Qualitative comparisons of visual generation with
<baseline> and <baseline>."*

That matters because of how a paper is usually fetched. The arXiv HTML rebuilds
the body text and the caption and embeds the figure as a raster, so an HTML pull
gives you every word of the caption and none of the prompts. So does a text dump
of the abs page. A study designed from that source does not know the
demonstrations exist as runnable inputs, and reaches for a public benchmark
instead — which measures the same capability on somebody else's prompts and
reproduces none of the source's pictures.

## Recovering them

1. **Pull the PDF, not only the HTML.** Extract its text layer page by page. A
   LaTeX-built paper keeps in-figure typography as real text, so the prompts come
   out of the extraction verbatim, next to the sample they belong to. Where a
   figure was pasted in as a bitmap, render the page at high resolution and read
   the strings off it yourself. Either path costs a minute.
2. Write `notes/source_showcase.json`: one row per demonstration, carrying the
   figure number, **the input verbatim** — whole, with its clauses about colour,
   composition and mood intact, not a paraphrase and not a truncation — the
   settings printed beside it (resolution, guidance scale, decoding), the
   comparator systems the figure lines up against, and a description of what the
   source's own sample shows.
3. Do this at literature stage, before the experiment list is costed. A prompt
   discovered at writing time is a prompt you cannot run.

## Running them

Run every row before you cost a benchmark grid, and keep them when the budget
tightens. One sample at the source's own settings is one forward pass; a grid is
hundreds. The two are not substitutes, and the grid is the one to trim:

* the grid answers *how often does it succeed over a standard prompt set*, which
  is a number;
* the showcase answers *did the demonstration reproduce*, which is the picture a
  reader puts beside the paper's.

Rank the rows by which one the source features — the first panel, the one on the
project page, and above all **the sample that depicts the system's own name or
central metaphor**. A model named after an image is going to be shown drawing
that image, and that panel is the one a reader looks for first. Its prompt is
usually the longest and most specific in the figure, because it is the one the
authors worked on.

Save each generated artifact as its own file under `outputs/`, at full
resolution, named after the prompt that produced it, with the prompt text in a
sidecar record beside it. A montage is a figure; the samples are intermediate
results, and results that exist only in a scratch directory under your working
tree were not delivered. Then put the sample in the report next to the source's
own, so the two can be read together.

Where the figure compares against other systems, say which comparators you ran
and which you could not, and keep the source's sample in the panel as the
reference either way.

## Before you finish

Walk `notes/source_showcase.json`. Every row should name a file under `outputs/`
and a panel in the report. A row whose answer is "the benchmark grid covers this
capability" is exactly the substitution this skill exists to stop.

## Why this is here

Measured on a task asking for a unified understanding-and-generation transformer.
The source's Figure 4 prints four prompts inside the figure; one is a detailed
portrait of the model's namesake, left half in cold blues and right half in warm
golds, and the graded image criterion is that portrait. The run fetched the
paper's arXiv HTML into `notes/janus_v1.html`; none of the four prompts, and
none of the responses printed in the neighbouring Figure 5, occurs in that file
or in its text rendering — "Roman god", "Sydney Opera" and "wise old owl" are all
zero there and present in the PDF text layer, which the run never pulled. It knew
the technique: it downloaded two *understanding* figure rasters into
`notes/janusfig/` and validated a scorer against the answers printed in them. The
string "Figure 4" occurs **zero** times in its entire agent log. It generated
sixty images — every one from a public benchmark prompt list, none from the paper
— and left all sixty in `.autor/*/workspace/generated/`, outside `outputs/` and
`report/images/`. The image criterion scored **0.0** against **41.0** for a plain
agent on the same task: 12.3 of the 19.8 points that run lost overall.
