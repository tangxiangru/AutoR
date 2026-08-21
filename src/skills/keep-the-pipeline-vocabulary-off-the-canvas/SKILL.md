---
name: keep-the-pipeline-vocabulary-off-the-canvas
description: Use at analysis and writing when your run carries internal scaffolding — numbered hypotheses, arm codes, clause verdicts, preregistered decision rules, provenance tags on input files — and you are about to save figures. Covers what may not appear inside the frame, what must, where the scaffolding does belong, and a four-question test on the image alone.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
---

# Keep the pipeline's vocabulary off the canvas

## What goes wrong

A run with internal scaffolding — numbered hypotheses, arm codes, clause tables, preregistered
decision rules, provenance tags on its input files — renders that scaffolding into the images.

An invented but typical example, from a hydrology run comparing two channel-routing schemes: the
figure is titled `H4 arm B - routing choice dominates (REFUTED)`; the x-ticks read `arm A pre-patch`,
`arm A post-patch`, `arm B pre-patch`, `arm B post-patch`; a legend entry says `seed-matched null`;
and a grey box in the corner lists `clause (a) FAILS / clause (b) FAILS / clause (c) —`. Every
element is true, traceable and correctly computed. The words *catchment*, *discharge* and *m³/s*
appear nowhere on the image.

You can read it because you wrote the preregistration. Nobody else has it. A reader with the task
brief and the picture cannot tell which experiment this is, and records the experiment as one that
was not run — which, from the image, it was not. Images are routinely read detached from the report
body, with little or none of the prose that would decode them, and the filename is not shown.
(`draw-the-source-figure-panel-for-panel` §7 and `use-the-sources-own-names` cover where the prose
and the source's names have to go; this skill is only about what is inside the frame.)

Verdict words make it worse. `REFUTED` or `INCONCLUSIVE` as the largest text on the canvas says what
your decision rule did, not what the system does. It reads as process, and it primes a reader to
score the panel as a negative result about your run rather than as a measurement of anything.

## Off the canvas, always

- Hypothesis, claim and obligation ids.
- Arm, run and configuration codes, anywhere a reader looks first: title, axis label, tick label,
  legend entry.
- Verdict words for your own decision rules — refuted, supported, inconclusive, pass, fail.
- Clause tables and pass/fail boxes.
- Internal provenance tags for your inputs, of the "as-supplied vs. mirrored" kind. If the
  distinction matters, it is a series name in physical terms plus one sentence of caption.
- Digests, artifact paths, `if_supported` placeholders and anything else that is a message from one
  of your stages to another.

## On the canvas, always

- **The system's name.** Somewhere visible — title, axis label, an annotation, or a legend that
  names it. The title is the strongest position and the default. A panel whose axes are already
  physical can carry the system name as an annotation instead, but "no name anywhere" is the failure
  mode, and it is common.
- **A physical quantity with a unit on every axis.** If a tick has to carry a categorical label, the
  category is a physical treatment ("no correction term", "with the correction term"), never an arm
  code.
- **A title of the form `<system> — <quantity> vs <coordinate or condition>`**, in the vocabulary the
  field uses for all three.

## Where the scaffolding does belong

Keep it, all of it. It goes in the preregistration file, in the artifact JSON, and in one appendix
table mapping hypothesis → figure → verdict → artifact path. That table is worth having and costs
the figures nothing. This is a rule about the image, not about the discipline behind it. A caveat
that genuinely matters is a sentence of caption, and any verdict is the caption's last clause.

## The stranger test

Before saving each figure, cover the report and ask of the image alone:

1. What system is this? If the answer is only in the filename or the surrounding prose, the canvas
   is wrong.
2. What is plotted, in what units?
3. Which series is the thing under test, which is the reference, which is the baseline?
4. What would this panel look like if the result had come out the other way? If there is no visible
   difference, the panel is showing a verdict rather than a measurement.

If any answer needs your report text, fix the figure, not the text.

## Checklist

- [ ] Every figure names its system somewhere inside the frame.
- [ ] No hypothesis id, arm code, clause table, pass/fail box or verdict word appears in any title,
      axis label, tick label or legend entry.
- [ ] Every axis carries a physical quantity and a unit.
- [ ] Every categorical tick names a treatment in physical terms.
- [ ] The hypothesis → figure → verdict mapping exists, in the appendix, not on the canvas.
- [ ] The stranger test was run on every figure that ships.
