---
name: the-supplied-arm-owns-figure-one
description: Use at study design when the figure slots are allocated, and again at analysis and writing, when the study has two arms — the files the task supplied and a better external version of the same quantities — and you are deciding what goes on which axes. Covers which population owns the opening figure, copying the source panel's rendering and not only its data, and keeping the two arms out of each other's sentences.
stages: 03_study_design, 06_analysis, 07_writing
---

---
name: the-supplied-arm-owns-figure-one
description: Use at study design when the figure slots are allocated, and again at analysis and writing, when the study has two arms — the files the task supplied and a better external version of the same quantities — and you are deciding what goes on which axes. Covers which population owns the opening figure, copying the source panel's rendering and not only its data, and keeping the two arms out of each other's sentences.
stages: 03_study_design, 06_analysis, 07_writing
---

# The supplied file gets a panel with nothing else on it

`run-the-requested-analysis` settles *whether* the supplied data still gets
analysed once you have found something better: it does, as an arm beside the
external one, never instead of it. This skill is the half that decides the score
after you have agreed to that — **where on the page the two arms go**. A run can
hold both arms, measure both, tabulate both, and still lose every figure-typed
criterion, because the arm the reader is checking never had a set of axes to
itself.

## The failure this prevents

A run located the authentic release behind the task's stand-in files during
literature survey, profiled every supplied file correctly inside the first hour,
and wrote the values to a results JSON. It then built every reproduction figure
on the external population, with each supplied column laid over the top as a
dashed line labelled by how far off it was. Each supplied value reached the
report exactly once, as the numerator of a deviation ratio, in a table under a
heading announcing that the supplied files were unfaithful. Where the report
restated the questions the supplied files pose, it answered them with the
external arm's number — and for one quantity the two arms differ by more than an
order of magnitude, so the answer on the page is the one a reader holding the
task's own files cannot reproduce.

On that criterion it scored about half what a plain agent scored. That agent ran
the same download, reached the same conclusion about fidelity, and put it last.
Its opening figure was one panel per supplied file, each panel that file alone,
each annotated in-figure with its own n, its own location statistic and its own
spread.

Two mechanisms finish the job, and both look like discipline from the inside.
The first is an integrity rule of the form *no supplied value is quoted without
its external counterpart*. The rule is right; its mechanical effect is that the
supplied value never once occupies a main clause. The second is figure
inflation, below.

## What to do

1. **The opening figure is the supplied arm.** One panel per supplied file, that
   file and nothing else on the axes, with n, the location statistic and the
   spread printed inside the panel. Overlays, external comparisons and fidelity
   checks are a later, separate figure.
2. **Copy the source panel's rendering, not only its data.** Before drawing,
   record from the rendered source figure: count histogram or density estimate,
   log or linear on each axis, the raw variable or its log on x, bin count,
   decade span, and any region the source shades or brackets. A panel that
   carries the right numbers in a different artifact class is read as an
   approximate match, and approximate is where the points go. The series list
   and the panel layout are covered by `draw-the-source-figure-panel-for-panel`;
   this rule is the rendering underneath them.
3. **The number in the caption is measured on the rows the panel shows.** If the
   headline statistic came from a different population than the curve, the panel
   does not support it, however close the two happen to be. State the statistic
   the panel's own rows give, then the external one beside it if you want both.
4. **Draw cross-quantity comparisons inside one population.** A reference value
   from one supplied file belongs on another supplied file's panel as a labelled
   line, measured on supplied rows on both sides. A ratio whose numerator and
   denominator come from different populations is not a comparison of anything.
   With two populations, publish the ratio twice — once per population, each
   internally consistent, each labelled — rather than once with the sides mixed.
5. **Never let the two arms share a sentence.** Two sentences, each naming its
   population in the same clause as the number: "over the supplied rows, X is
   ...; recomputed from <source> over M entries, X is ...". The moment one arm is
   the subject and the other is a caveat, the caveated one is the one that was
   asked for.
6. **Give each supplied value one unqualified sentence before any comparison.**
   If you are running an integrity rule that forbids a bare supplied number, pair
   it with this one; they are compatible and only the pair survives contact with
   a reader.
7. **Keep the figure count near half a dozen and consolidate.** Readers and
   automated reviewers alike open a bounded number of figures, and it is not
   always the ones you ranked first: a run that shipped eleven figures had five
   of them examined, and the two panels answering graded questions were in the
   six nobody opened. Merging the supplied-arm panels into one multi-panel
   opening figure makes the graded content a single artifact instead of several
   lottery tickets.

If a supplied file genuinely cannot express the quantity — the column is absent,
the variable is a different one — that sentence goes where its value would have
gone, naming the missing column, and the panel still shows what the file does
carry.

## Before you finish

For each file in `data/`, name two things: the figure whose axes contain that
file and nothing else, and the sentence that states its own summary statistic
with no comparison attached. If either is missing, or if every occurrence of the
file's name sits in a clause about it being wrong, rewrite before you ship.
