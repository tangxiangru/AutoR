---
name: material-design-targets-span-the-property-range
description: Use when a task asks you to generate, design or optimise candidates toward desired property values that the brief never enumerates. Covers deriving the target grid from the supplied property distribution, why the target outside your validator's fitted range must not be deleted, and how a source study's published designs may and may not be used as anchors.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Design at the ends of the property range, not only in the middle

A design brief usually says "achieve desired values of the property" and stops.
The target list is then yours to choose, and the cheap choice is one or two
values near the mode of the supplied distribution. Those get hit to three
decimals, a tiny design error is reported, and the study has demonstrated
something a lookup over the supplied rows already does. The claim an
inverse-design paper is actually making is the opposite one: the ends of the
range, and whether the generator reaches past the data it was fitted on.

The second failure is more specific and more expensive. The run computes the
property distribution, notices that one regime lies outside the range its own
validator was fitted on, and deletes that target because it could not honestly
call the result validated. Declining to *call* an extrapolation validated is
correct. Deleting the *run* is not: it removes the only evidence about whether
the generator extrapolates, which is the half of the claim that is not already
in the training set. What is left is a defensible report with no answer in it.

## Study design: write the target table before you generate

Derive the grid from the data, not from taste. Compute the property distribution
over the supplied labelled set — after whatever calibration or correction your
pipeline applies, since that is the scale the targets live on — and write:

| target | value | where it came from | inside the labelled range? | how it will be assessed |

Rows, at minimum:

- the **minimum** of the calibrated property over the supplied set;
- the **maximum**, and one target **beyond** it, placed a stated multiple of the
  labelled standard deviation above the maximum;
- a **central** target: the mean, median or mode;
- every **landmark** value named in something you are allowed to read — the task
  text, the data dictionary, the related work, the source study: a service
  temperature, a specification limit, the property of a candidate someone has
  already made.

Quote the computed min, max, mean and sd in the report. Three lines of code, and
they turn the grid from a preference into something reproducible.

**Reserve one figure slot per target row, in this stage.** Figure plans get
frozen, and figure producers get written to refuse any filename not in the plan;
a target row that acquires a population two stages later is then undrawable. If
your producer enforces the plan, write the reopen procedure into the plan file
at the same time.

## The landmarks and the anchors live in the source study, not in the folder

The papers shipped beside the data are usually background reading, not the study
the brief was drawn from. Fetch the source study itself. It holds the landmark
values, and it is usually the only place holding candidates whose property has
been established by a method independent of yours.

Those published candidates are an external test set for your validator and
nothing else. Write the boundary down before you open the file:

- **allowed** — score them with your validator and report your validator's
  signed error on them, per regime;
- **forbidden** — copying any of them into your candidate list, your delivered
  designs or your target values, and treating agreement with them as validation
  of a design of your own.

A run that cannot state that boundary tends to resolve it by refusing to open
the file at all, which deletes the only out-of-range anchor available and the
extrapolation claim with it.

## Experimentation: run every row at the same budget

Out-of-range rows use the same code path and the same number of scored
candidates as interior rows. State the per-target budget. Out-of-range is not a
special case at generation time; it becomes one at assessment, and only there.

## Assessment: apply the reporting rules, do not restate them

Per-target values in the property's physical unit, each against an independent
anchor, with the error outside the labelled range reported as its own number, is
`material-landmark-scalars-in-physical-units`; this skill does not repeat it.
Two things it adds. The anchor set must contain points at or beyond **both** ends
— the top and bottom deciles of the labelled set, plus the independently
established candidates above. And the out-of-range target is reported twice, as
the design-time score and as the anchor-corrected value with the anchor spread
as its interval, rather than dropped.

## Analysis: one figure carries the whole grid

Designed population per target, overlaid on the labelled distribution, on the
property axis, with every target drawn as a line and the labelled min and max
drawn as bounds. A reader must be able to see, without reading a number, whether
any designed population lies outside the bounds of the training data. If a
target produced nothing, that is written on the axis where its population would
have been — not by deleting the category, and not by leaving the category empty
with a note about which internal test disabled it.

## Checklist

- [ ] Target table exists, with min / max / beyond-max / central computed from
      the supplied data and quoted in the report.
- [ ] Every landmark value in the brief, the data dictionary or the source study
      is a row.
- [ ] At least one target lies outside the labelled range, and it was run.
- [ ] Equal generation budget per target, stated.
- [ ] A figure slot was reserved per target row before generation started.
- [ ] Independently established candidates scored as an external test set; the
      allowed/forbidden boundary stated in the report.
- [ ] Per target: achieved value, gap, interval on the gap, anchor-corrected
      value, and whether the candidate's components already occur in the
      supplied set.
- [ ] One figure: designed populations + target lines + labelled min/max, no
      empty category.

## The move that loses the point

Reporting a minuscule gap between the optimiser and its own proxy at one
interior target. That gap is a spacing statistic of the scoring budget — halve
the candidate pool and it doubles — not a design accuracy. Compute the order
statistic 1/(2·N·f) it should equal, put it beside the measured gap in one
sentence, and spend the rest of the effort on the ends of the range.
