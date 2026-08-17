---
name: disclose-by-construction-not-by-absence
description: Use at analysis when figures are rendered and at writing when they are captioned, and whenever an internal review asks you to disclose something you could not do. Covers why a disclaimer drawn inside a figure's axes destroys the result it annotates, the single location a caveat is stated in and what counts as a second copy, and how to describe the substitute you built instead of the gap you had.
stages: 06_analysis, 07_writing
---

# Disclose by construction, not by absence

## The failure this prevents

Two runs shipped the same panel with the same layer missing, because neither had
the inputs for it. One wrote the omission into the figure's axes, into the
figure's caption, into its design ledger and into its limitations section. The
other wrote nothing anywhere — the word does not occur in its report. The reader
graded the first as not having reproduced the missing element, and the second as
matching the source qualitatively, on two pictures missing the same thing. The
disclosure was the entire difference on that requirement, and it was one of the
headline requirements of the task.

The conclusion is not "say less". A silent gap is a defect and a reader is
entitled to find it. The conclusion is that a gap you filled is a construction
note, a gap you did not fill is one sentence, and every copy after the first is
subtracted from the result it is attached to.

## Say what you built, not what you lacked

Where you produced a substitute for something you could not source, describe the
object that exists:

- "Positions are constructed from the per-category counts, not measured; they
  carry no within-category information." Checkable, and it describes something
  that is in the figure.
- "The measured positions are unavailable, so that layer is omitted." Describes
  a hole, and a hole can only be graded as a hole.

Before writing either sentence, ask whether the missing thing can be produced
instead. `reconstruct-the-figure-layer-you-cannot-source` is that question in
full, and it is the version of this advice that raises the result rather than
trading transparency for score.

## Never draw an absence inside the axes

On-figure text is not the problem — it is usually what wins a figure
requirement. The value on every mark, the category names, `n`, the denominator,
the reference line, the source's published constant beside yours: all of that
belongs inside the axes, and in the run above the highest-scoring figure of all
was one that carried several lines of its own on-panel annotation. What does not
belong inside the axes is text about what the figure does **not** show.

A figure is read as the result. Text drawn into the axes is part of the result,
so a disclaimer rendered there replaces the finding with its absence at the one
moment the reader is looking at the picture instead of the prose. It also
survives every crop, thumbnail, excerpt and re-use the image appears in, long
after the caveat has stopped being interesting.

## One statement, at the point of absence

`evidence-not-assertion`, `the-canonical-figure` and `cover-what-the-task-named`
already fix the location: something you did not produce is stated plainly, in
one sentence, in the section where the result would have gone. Keep that
sentence — this skill is about the second and third copies.

| location | first statement | any repeat |
| --- | --- | --- |
| the section where the result would have gone | required | — |
| inside a figure's axes | never | never |
| figure caption | only as a construction clause, when the figure itself is the substitute | no |
| abstract | no | no |
| limitations | a pointer, not a restatement | no |

A caveat with four homes reads as the run's main finding. A reader has no way to
tell a thoroughly disclosed minor gap from a major one, and prices it as major.

## Do not let a review loop harden a caveat into an artifact

Self-critique and internal review will ask for disclosure, and the discharge
they deserve is the sentence you already wrote. Rendering that sentence into the
figure, promoting it into a heading, or adding it to the abstract are not three
discharges of one obligation; they are three more charges against the
deliverable. Close such an obligation by naming the single location that holds
the statement, and record that location in the review ledger so the next pass
does not re-open it.

When a review asks for a disclosure, run the cheaper test first: can the missing
thing be produced under a stated construction? If yes, the caveat becomes a
construction note and stops being a caveat.

## Checklist, before the report is finished

- Walk every string your plotting code draws inside the axes. Anything that
  describes what the panel does not show, what was unavailable, or why something
  is approximate: delete it from the render.
- For each gap you did not fill, grep the draft for its key phrase. One hit, in
  the section where the result would have gone, plus at most one pointer. Three
  or more hits means the caveat is eating the result it is attached to.
- Every construction note says what was built and from what, in one clause.
- Every caption describes what is in the figure. No caption opens with what is
  not.
