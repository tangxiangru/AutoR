---
name: read-the-pilot-run-as-a-result
description: Use at implementation and experimentation, when a reduced-scale or smoke run of the full pipeline finishes and before the compute budget is committed to the full run. Covers adjudicating the pilot's gap against the target instead of its exit code, reading the exclusions recorded beside the gap as its likely cause, testing whether a substituted input carries the contrast the headline statistic differentiates, and which input to change while changing one is still affordable.
stages: 04_implementation, 05_experimentation
---

# A pilot run returns a number. Read it.

A reduced-scale run — a smoke slice, one seed, a handful of files instead of the
full set — gets checked for two things: exit code and artifact count.
"exit 0, N/N artifacts present" goes into the stage record, the full run is
launched, and the headline is looked at for the first time hours later, with the
budget gone.

The number was usually already there. In the runs where this loses, the pilot
artifact is not silent: it holds the headline value, the target recovered at the
literature stage, and the signed gap between them, in the same file. The defect
is not that the pilot went unmeasured. It is that no step in the run was obliged
to read the gap and decide something. A pilot that reports its own shortfall and
is filed as a build check is worse than one that reports nothing, because the run
now has evidence it did not act on.

## What a pilot bounds, and what it does not

It bounds the **sign** of the gap, its rough **order**, and **which classes your
pipeline can populate at all**. Those are stable under scale.

It does not bound the **size** of the gap. A tenth of the data can move an
extreme class by a factor of several once the full sample arrives, so a shortfall
that reads as catastrophic at pilot scale can settle to merely large. Do not
quote the pilot's magnitude as an estimate, and do not dismiss a pilot gap
because you expect scale to close it — decide which of the two you are relying
on, and write it down.

## Make the pilot a gate

Before you open the pilot output, write one line: the tolerance, in the
headline's units, inside which the full run is worth launching. If study design
froze one, use that.

> If the pilot gap exceeds the tolerance, the full run does not launch until one
> of two things is recorded in the pilot artifact itself: **an input change
> chosen**, or **the gap attributed by a measurement** naming the property that
> carries it. "Noted, proceeding" is neither.

Record the decision in the artifact rather than the stage summary. You will need
it at analysis whether the gap closed or not, and the artifact is what survives.

## Join the gap to the exclusions sitting beside it

The file that reports the shortfall very often reports, a few lines away, what
the pilot quietly dropped: a field called `excluded`, `skipped`, `incomplete`,
`n_missing`, `insufficient`, or a member whose file count is zero. The two facts
are adjacent on disk and nothing joins them unless you write the join.

For every entity excluded for an incompleteness reason, write one line: what
completing it would cost, and what it would change. An exclusion applied on the
arm the headline is computed from is not housekeeping — it chose the population
of your result, and whatever happened to download chose it for you.

## Contrast, not level — and per member

A reproduction almost always runs on a substituted driver: a different product,
resolution, release, model pool or proxy for the one the source used. Substitutes
are chosen by matching **levels** — units right, magnitudes plausible, pattern
like the published one. But the headline of a reproduction is usually a
**difference**: a change between periods, a ratio between conditions, an
exceedance over a baseline. A product can match on levels and carry almost none
of the contrast, and nothing about opening the file tells you so. Only running
the source's own statistic on it does.

Measure the input-side contrast directly — the between-condition ratio or
difference of the raw driver, over exactly the rows that enter the statistic —
and put it beside the same contrast in the source's released field, or in a
number the literature reports. **Run it per member, realisation or model, not
once over the pool.** A pooled contrast hides an arm carried by a single member,
and a pool of one has that member's contrast, not the ensemble's.

Two more checks, minutes each:

- **Reachability.** For each class the published result populates, ask whether
  your pipeline can reach it at all: quantisation step against threshold, floor
  against smallest non-zero value, denominator range against numerator range. A
  class empty in the pilot is usually unreachable, not undersampled.
- **A positive control.** Feed the pipeline an input that must fire — the
  source's released field over whatever subset overlaps yours, or a synthetic
  case built to cross the threshold. If it does not fire, the defect is in your
  code and the substitution is exonerated. Do this before blaming the data.

## Changing the input, in order of preference

1. **Another member, model, realisation or release from the same archive** —
   especially when the arm that matters was built from one and the archive holds
   more. Cheapest fix available and the one most often skipped, because a pool
   counted across all conditions looks adequate while the condition carrying the
   headline has one member in it. Count the pool *within* that condition.
2. The variable or product the source's own released code reads, if fetchable.
3. A normalisation or calibration that restores the contrast, declared as an
   assumption and swept in the sensitivity analysis.
4. The supplied data plus a published scaling relation, as a stated
   approximation.
5. The source's released field over its overlapping subset as a calibration arm,
   which at least bounds the deficit and localises it.

## Checklist

- [ ] Tolerance written down before the pilot output is opened.
- [ ] Pilot gap adjudicated — input change chosen, or gap attributed by
      measurement — and recorded in the artifact.
- [ ] Every exclusion in the pilot artifact costed in one line.
- [ ] Input-side contrast measured per member and compared with the source's.
- [ ] Class histogram printed beside the published one; empty classes tested for
      reachability.
- [ ] Positive control fires.
- [ ] The pilot comparison appears in the report as evidence the check was made.

`close-the-gap-to-the-published-number` is this same rule one stage later, when
the gap is full-scale and the budget is short. Arriving there with the pilot
unadjudicated is arriving at the expensive version of this page.
