---
name: every-supplied-array-is-a-series-in-a-results-panel
description: Use at study design when the figure plan is written, and again before the report is finalised, whenever the task ships a data file holding several named arrays, columns or blocks. Covers building the deliverable inventory from inside the file rather than from the directory listing, grouping the supplied series by shared abscissa into panels, and the grep sweep that finds the arrays you measured and never drew.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# The inventory is inside the file, not in the directory listing

A task that ships one file in `data/` looks like one deliverable. It is not.
The file holds N named arrays, and the results you are judged on are claims
about those arrays. Any inventory built by listing `data/` discharges in one
line and misses every one of them.

Two shipped skills stop the directory-level version of this and neither reaches
inside a file. `the-supplied-item-is-the-graded-unit` covers reporting a named
object from `data/` under its own name. `draw-the-source-figure-panel-for-panel`
covers deriving each panel's series list from the source's rendered figure, and
its rule that a curve you disqualified stays on the panel annotated is the rule
this failure breaks most often. What follows is the same discipline applied to
the arrays, columns and blocks *within* one supplied file, plus the sweep that
finds the ones you never drew.

## The failure this prevents

A run was handed a single plain-text file holding a few dozen named arrays in
several blocks, each block a set of series sharing one abscissa. It shipped six
figures. Its three results figures carried about a quarter of the supplied
series between them; several arrays — model curves and a second abscissa —
appear in no figure script anywhere in the run.

None of it was an oversight. Every missing array had been measured first, and
the measurement was the stated reason for dropping it: this series carries no
information the neighbouring one does not, this theory array is a
reparameterisation of another, this family of shipped model curves was fitted
and disqualified in a section of its own. Each of those findings was correct.
Each of them is a caption clause. A comparator ran the same audits, reached the
same conclusions, plotted every supplied array anyway, and scored higher on both
graded items where the two reports differed.

An array you measured and did not draw costs you twice: the panel is missing
the comparison, and the finding that justified the omission has no reader,
because the reader cannot see the curve it is about.

## What to produce

**At study design, before any figure slot is claimed:**

1. Parse the supplied file(s) and write `notes/supplied_series.csv`: one row per
   named array, column or block. Columns — the name exactly as the file writes
   it, length, stated units, which grid or abscissa it belongs to, and its kind:
   `measurement`, `model/theory`, or `abscissa`.
2. Group the rows by shared abscissa. **Each group is one panel.** Every
   measurement in the group goes on as markers, every supplied model or theory
   array in the group goes on as a line, on one pair of axes, in the file's own
   numbers.
3. Record the group-to-slot binding in the plan. A group with no slot is a block
   of the supplied file that your deliverable does not mention.

**Four rules that decide the hard cases:**

4. **A supplied independent-variable array is an abscissa you owe a panel.** If
   the file ships two axes for one response — an amplitude and a power, a
   density and a filling factor — you owe a panel in each, plus the conversion
   between them written down and checked against the relation the source states.
   A fitted exponent quoted against the axis the source did not use differs from
   the published one by a factor and reads as a disagreement you never had.
5. **Anything you build is an added series, never a replacement.** A regenerated
   model family, a closed form you coded from the source's equations, a derived
   bound: these go on the panel *beside* the supplied array they correspond to.
   If your substitute is on the panel and the array it stands in for is not, you
   have plotted your own reasoning instead of the data you were given.
6. **A defect in a supplied array is an annotation, not a deletion.** Whatever
   the audit found — a duplicate, a mislabel, a rescaling, a ragged length, a
   fit that fails — write it into the caption or onto the panel in one clause
   and keep the curve. The annotated panel is worth more than the clean panel
   and more than the paragraph that replaces it.

7. A data-overview or small-multiples figure **discharges none of this.** It
   shows that the arrays exist. A results panel shows what they mean.

## The sweep, before the report is written

For every row of `supplied_series.csv`:

```
grep -l "<array name>" code/*.py
```

- Zero hits: a supplied series you never drew and never fitted.
- Hits only in the parser or the overview script: half-drawn — read, plotted as
  a thumbnail, absent from every result.

For each, either put it on the panel its group owns, or write one sentence in
that panel's caption saying why it is absent. "It is redundant with another
series" is a legitimate sentence; it is not a reason to omit the sentence.

Then, per panel, diff the series you actually plotted against the group's row
list and write the two counts in your notes: *k of n supplied series on this
panel*. Any panel below n needs the sentence. Do this once at design time
against the plan and once against the figures you actually produced; the two
answers are routinely different.

See also `publish-what-the-run-already-computed`, which is the same sweep over
the run's own *outputs* rather than its inputs. Run both.
