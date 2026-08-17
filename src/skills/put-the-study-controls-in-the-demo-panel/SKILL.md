---
name: put-the-study-controls-in-the-demo-panel
description: Use when the source ships showcase examples — a demo notebook, a teaser figure, images supplied with the task — at experimentation, to run every arm of the study on those inputs, and at analysis when the panel is drawn. Covers putting the study's control arms inside the demo panel, title discipline, and keeping overlays registered to the image they explain.
stages: 05_experimentation, 06_analysis
---

# Put the study's control arms inside the demo panel

When a task ships the source's own showcase inputs — a demo notebook, a teaser
figure, two or three images supplied in `data/` — the panel you draw from them
is the one figure a reader lays directly beside the original. Two shipped skills
already cover the redraw: `draw-the-source-figure-panel-for-panel` (ship the
source's layout, print its named constants on the panel) and
`information-exhibit-the-intermediate-objects` (re-run the demos on the source's
own inputs, quote the verbatim before-to-after output). Runs that did both still
lost the figure item. A panel that matches the original is read as matching the
original: comparable, not superior. This skill is what to put in it beyond the
redraw.

## The failure

The demo is re-run exactly as the notebook prints it — one arm per example, the
panels the notebook emits — and every control that makes the demo mean anything
is somewhere else. The same-size region placed elsewhere, the un-guided variant,
the no-intervention baseline: all of them ran, all of them are summarised in a
table thirty pages away, none of them touches the images the reader is
actually looking at. The panel therefore shows that the method changed one
output once, and shows nothing about what it was compared against.

The panel is two or three images. It is the cheapest compute in the entire
study, and it is the one place where you can afford to run every arm.

## Rule 1 — every arm in the study also runs on the demo inputs

For each shipped example, run the full arm set you already built: the method,
each ablation, each null or randomised control, and the untouched baseline. Put
them in the same panel as one labelled line each, verbatim output, with the
method's own arm marked and the correct answer marked. Overlay the controls'
regions or interventions on the image alongside the method's, with a legend, so
a reader can see that the controls were placed differently and produced
different outputs.

One output shows the method worked once. Four labelled outputs show what it was
compared against and that only the method's arm moves the result. This is the
source's figure plus the experiment the source did not run, in one image, for
minutes of compute — and it is the load-bearing rule here. The other two are
hygiene.

## Rule 2 — titles and adjacent text carry the demonstrated fact

Panel title: the question asked of that input, verbatim, or the object shown.
Panel content: the intermediate object. Adjacent text: before-output to
after-output with the correct answer marked, in the same type size as the rest
of the figure.

No hypothesis IDs, no verdict tokens, no wall clock, no library versions, no
bare internal arm codes in a title. That line is the first thing a reader reads
and pipeline bookkeeping wastes it. If an internal arm code must appear, spell
out what it is on the same line. The same discipline applies in the report body:
a reader should never have to decode which of your arm labels is the published
method.

## Rule 3 — keep the intermediate object registered to the input it explains

A map, overlay or heatmap goes beside its own image at that image's aspect ratio
and orientation, at the same rendered height, with its grid resolution stated.
Do not silently square a non-square map. Do not log-transform, percentile-clip
or recolour unless the untransformed version is unreadable, and when you do, say
so on the colourbar. A reader comparing your panel with the source's is
comparing appearance, and an undeclared transform makes a matching result look
like a different one.

Optional, if the runs are cheap: where the source demonstrates one configuration
on one example and a different configuration on another, running both
configurations on both examples turns a presentation choice into a measured
contrast. Do it only after rules 1 to 3 hold; it doubles the demo runs and a
faithful one-configuration-per-example layout is not by itself what loses the
item.

## Checklist

- [ ] One panel row per shipped example — all of them, none dropped.
- [ ] Every arm in the study run on every demo input, printed in the same panel,
      labelled, with the method's arm marked.
- [ ] Control interventions overlaid on the image beside the method's, with a
      legend.
- [ ] Verbatim before and after outputs per arm, correct answer marked, at body
      type size rather than in a caption footnote.
- [ ] Panel titles are the question or the object; no IDs, verdicts, timings or
      versions anywhere in a title.
- [ ] Overlays at the input's aspect ratio, grid resolution stated, any
      transform declared on the colourbar.
- [ ] Caption states in one sentence what the panel demonstrates, and every
      claim in the caption is visible in the panel.
- [ ] Laid side by side with the source's figure, mine shows everything theirs
      shows plus the arms they did not run.

## Why this is here

The demo panel is graded against the source's own figure, and a faithful redraw
tops out at "the same picture". The two ways to lose from there are drawing less
than the source did — one arm, an unregistered map, the demonstrated fact
shrunk into a caption footnote — and never adding the thing the source cannot
have, which is your own controls on the source's own inputs. Both are fixed for
minutes of compute, because the inputs are a handful of images and the arms
already exist.
