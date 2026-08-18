---
name: information-run-the-prompt-printed-inside-the-figure
description: Use at literature survey, study design and experimentation when reproducing a generative model whose paper demonstrates its capability with a figure of samples — text-to-image panels, dialogue transcripts, rendered outputs. Covers why the copy you fetched does not carry the showcase inputs, running them before any benchmark grid is costed, which one to run first, and where the artifact has to land to count as delivered.
stages: 01_literature_survey, 03_study_design, 05_experimentation
applies_when: text-to-image
---

# Run the source's own showcase inputs, and land the results where a reader meets them

A generative model's paper argues its case twice: once with a benchmark table
and once with a figure of samples. The two are not substitutes. The table says
how often the system succeeds over somebody else's standard prompt set. The
figure is a named case with a published expected output, and reproducing it is
the only comparison a reader can make by looking.

The demonstration goes missing in two places, and a run usually loses it at the
first without ever reaching the second.

## The copy you fetched decides whether you have the inputs

The figure's inputs — the prompt string, the question asked, the system message
— are set as small type *inside* the figure graphic. The caption does not repeat
them; it names the figure and the comparison, and often the settings each system
ran at. An arXiv HTML build or an abs-page dump rebuilds the body text and the
caption and embeds the figure as a raster, so a fetch by either route hands you
every word of the caption and none of the inputs. Nothing in the document you
are reading will tell you they exist.

`extract-the-pdf-text-layer-then-read-every-figure` has the recovery procedure
and the ledger it fills. One thing to add to it, because it is the step a run
that already owns the technique still skips: **the extractor gets pointed at the
PDFs that arrived as files, and not at the source you went and found yourself.**
Fetch the source as a PDF as well as HTML and run the same extractor over it. A
LaTeX-built paper keeps in-figure typography as real text, so the inputs come out
verbatim and whole, with their clauses about colour, composition and mood intact.
Where a figure was pasted in as a bitmap, render the page and read the strings
off it.

## Run them before you cost the grid

Every recovered input is an experiment you can already run, and it is cheap
against the thing competing with it: one sample at the source's own settings is
a single forward pass, a benchmark grid is hundreds of them. When the budget
tightens, the grid is the one to trim.

Rank the rows by which one the source features: the first panel, the one on the
project page, and above all **the sample that depicts the system's own name or
its central metaphor**. A model named after an image will be shown drawing that
image, and that panel is the one a reader looks for first. Its input is usually
the longest and most specific in the figure, because it is the one the authors
worked on.

Where the figure compares against other systems, run the comparators you can,
say which you could not, and keep the source's own sample in the panel as the
reference either way.

## Where the artifact has to land

Computing the pixels is not delivering them, and the destination is decided when
you write the run script rather than when you write the report.

* **The artifact that carries the argument goes into a figure under
  `report/images/` that the report body links.** That is the location that
  survives. The export keeps images the report references and prunes the rest
  out of `outputs/` and out of `report/`, so a raster dropped loose in either
  tree is not merely unread, it is deleted. A raster left in a scratch directory
  no export walks fails the other way round and ends up the same: nothing
  outside the run ever sees it.
* **Under `outputs/`, write the mapping and not the pixels** — one row per
  demonstration giving the figure and panel as the source labels them, the input
  verbatim, the settings you ran at, and the file the sample is published in.
  That row is what makes the panel checkable.
* **Raw frames from a bulk grid are working data, not exhibits.** Keep them out
  of both swept trees and compose the figure from them. The set of images
  published with a report is a fixed-size budget shared by every figure in it,
  so loose frames do not add coverage — they spend it.
* Put the source's own sample in the same figure, labelled, so the two are read
  together rather than a page apart.

## Boundary

`extract-the-pdf-text-layer-then-read-every-figure` recovers the inputs and
writes the demonstration ledger. This skill spends it: which row to run first,
when to run it relative to the benchmark grid, and where its output has to end
up. Add rows to that file rather than opening a second one.

`draw-the-source-figure-panel-for-panel` is about the source's *plots*, and its
`notes/source_figures.json` records axes, series, ranges and printed values so a
curve can be redrawn and laid beside the published one. This is about the
source's *samples*: there is no quantity to plot, the artifact itself is the
result, and what the row has to carry is the verbatim input and the settings
rather than a series list.

`information-exhibit-the-intermediate-objects` states the rule — your own prompt
set may demonstrate the capability but does not reproduce the demonstration, and
aggregate statistics never substitute for it. This is the mechanics of not
losing it: where the inputs are, when to run them, and where the output goes.

## Before you finish

Walk the demonstration ledger. Every row should name the figure in your report
that shows the result and the line of the body that links it. A row answered
with "the benchmark grid covers this capability" is exactly the substitution
this skill exists to stop.

## Why this is here

Measured on a task asking for a unified understanding-and-generation
transformer, against a plain agent on the same task. The source's Figure 4
prints four prompts as typography inside the figure, and one image criterion is
graded on one of those four demonstrations. The run scored **0.0** on it against
the plain agent's **41.0** — 12.3 of the 19.8 weighted points it lost overall.
(The prompts are not reproduced here on purpose: a run that follows the method
above recovers them in a minute, and one that is handed them has not been
measured.)

The caption was never the obstacle. It sits verbatim in the run's own `logs.txt`
twice, and the run generated at the 384×384 that same caption prints for the
source's own samples. What it never reached for were the prompts. It pulled the
source as arXiv HTML into `notes/janus_v1.html`; three distinctive phrases taken
from three of the four prompts occur zero times in that file, zero times in its
text rendering and zero times in either of the run's two log files, while each
occurs once in the text layer of the source's PDF, which the run never pulled.
It owned the technique and had already used it four times — a PDF text extractor
over all four related-work PDFs the task shipped as files, and over none of the
source it went and fetched itself. The two figure rasters it did download,
`mm_und_sample.png` and `mm_und_appendix.png`, are both from the understanding
half.

So all sixty images it generated came from a public benchmark prompt list and
none from the paper, at a measured median of 67 s each: the four showcase
prompts would have cost about four and a half minutes against that grid's
sixty-seven. It published ten figures to the plain agent's five, and the grader
shows a grader up to fifteen, so both sets arrived whole — twice as many drawn was
not the difference, and the one that was missing was the source's own.
