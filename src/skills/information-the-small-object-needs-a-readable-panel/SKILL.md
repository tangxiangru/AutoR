---
name: information-the-small-object-needs-a-readable-panel
description: Use at experimentation and analysis when the claim is about something small in a large input — a cropped region, a localised attention peak, a few pixels of text, a rare token — and you are laying out the qualitative panel or saving its intermediate objects. Covers rendering the object under test at a size a reader can adjudicate, measuring that size before you save the figure, and persisting each visual object as an image rather than only as an array.
benchmarks: researchclawbench
applies_when: fine-grained perception|small objects
stages: 05_experimentation, 06_analysis, 07_writing
---

# If the object under test is small, most of the canvas belongs to it

A qualitative panel for a fine-detail method is not an illustration. It is the
measurement: the reader decides whether the region you selected is the right
region by looking at it. That decision needs pixels, and a multi-column figure
does not have them.

The arithmetic is unforgiving and nobody does it. A three-column figure on a
1500-pixel canvas gives each column about 300 pixels. A photograph 1024 pixels
wide is then drawn at 0.3×, and the thing the whole study is about — a date on a
number plate, a figure at the far end of a crowd, a ten-pixel object — is drawn at
a third of a size that was already small. Every element is present and correct
and the evidence is not visible. Meanwhile the source's own figure gave that same
photograph half of its canvas.

## Do this

1. **Measure the object before you choose the layout.** You already have its box.
   Compute its size in pixels and as a fraction of the image, and compute what it
   will be *on the canvas*: `object_px × (panel_px / image_px)`. Under about
   twenty rendered pixels it is not evidence, whatever the panel says. Print the
   number in the caption too — "the questioned object is 10 × 25 px, 0.007 % of the
   image" is the sentence that makes the panel mean something.
2. **Show at least one view at native resolution.** The crop as the model actually
   receives it, unscaled, is the cheapest and most persuasive panel you can draw.
   Never let the whole-image thumbnail be the only place the object appears.
3. **Spend the canvas rather than the columns.** One row per example, two or three
   panels per row, and a bigger canvas. A six-panel figure on a canvas the size of
   the source's one-image-per-half figure is a downgrade with more content in it.
4. **Put the annotation where the object is.** A box drawn on a thumbnail is a
   dot; add an inset that magnifies the boxed region beside it, with the
   magnification stated.
5. **Save every intermediate visual object as an image, not only as an array.** An
   attention map written to `outputs/*.npz` and rendered nowhere is a file nobody
   opens; the array is for recomputation and the PNG is the archive. Write both,
   named for what they show. This is in addition to the composite panel in the
   report, which is still the deliverable — see
   `information-exhibit-the-intermediate-objects` — not instead of it.

## Before you save the figure

Open the rendered PNG and look for the object. Not in the data, in the picture. If
you have to zoom in to find it, so does the reader, and the reader will not. Then
lay it beside the source's own figure and compare the two at the same displayed
width: if the source's photograph is bigger than yours, you have added panels by
taking pixels from the evidence.

`put-the-study-controls-in-the-demo-panel` covers what else belongs in that panel
— every arm, the controls, the verbatim before-and-after output — and
`draw-the-source-figure-panel-for-panel` covers matching the source's layout. This
skill is only about magnification: a correctly registered, correctly labelled,
control-carrying panel still fails if the thing being demonstrated is thirty
pixels across.

## Why this is here

On a task whose whole subject is perception of small objects, the source's own
figure gives each photograph 666 px of a 1340 px canvas. A run reproducing it drew
a wider canvas, 1507 px, split it three ways, and rendered each photograph at 319
px — under half the source's, for the same two images. Its two attention maps went
to `outputs/` as `.npz` arrays and nothing under `outputs/` was ever rendered. The
bare-agent control gave the photograph 577 px and also wrote each 336 × 336 crop
out as its own PNG beside the arrays. The image criterion scored 52.7 against that
control's 67.7, and both reports contained the same correct crops and the same two
corrected answers.
