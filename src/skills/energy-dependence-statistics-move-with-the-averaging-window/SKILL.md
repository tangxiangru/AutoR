---
name: energy-dependence-statistics-move-with-the-averaging-window
description: Use at analysis and writing when a coupling between two supplied series - load against weather, generation against irradiance, emissions against activity - is about to be reported as a single correlation, sensitivity or R-squared value. Covers the resolution ladder the statistic has to be reported as, how to compare it against a reference value whose window is unstated, and getting the ladder into the graded figure.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
---

# A dependence statistic is a function of the window you averaged over; report the ladder

## What goes wrong

You merge the energy table with the weather table, call `corr()` at the data's
native timestep, and report the matrix. One number per pair, computed once, at
one resolution, over whatever span you happen to have loaded. Then the number
stays inside a heatmap cell and never reaches a sentence.

A correlation, a sensitivity coefficient, an R-squared: each is defined jointly
by the pair and by the aggregation window it was computed over. Change the window
and the value changes, sometimes by more than the difference you are arguing
about. It does not move in a reliable direction - averaging suppresses whichever
component of the variance is fast, which strengthens some couplings and destroys
others, and can flip a sign when the fast and slow components disagree. So the
direction is a measurement, not an assumption.

Any reference value you will be compared against was computed at *some*
resolution over *some* span, and sources routinely state neither. When your
single number lands away from it, neither you nor a reader can tell whether your
pipeline is wrong or your window is different, and both of you assume the former.
The same failure has a second half: you obtain a longer record than the one you
were supplied and quote the coupling over the long record only.

## What to produce

A resolution ladder for the pairs the study is about, carried in the graded
figure, with a sentence per headline pair.

## Checklist

1. **Fix the merge first.** Join energy to weather on a reconstructed timestamp,
   never on row order; state the absence predicate and mask it before computing
   anything; report how many rows survived the join. A sign that surprises you is
   a merge bug until proved otherwise.
2. **Build the ladder.** Same estimator, same pairs, recomputed at the native
   timestep and at no fewer than two coarser aggregations of the series (for an
   hourly archive: daily means and monthly means). Add a rung for any physically
   motivated subset - daylight hours for a generation variable, occupied hours for
   a plug load - and say why it exists. Print n on every rung; the coarsest rung
   is often a handful of points and its coefficient is nearly free to move.
3. **Report the direction you measure, not the one you expect.** One or two
   sentences: which pairs strengthen under coarser averaging, which weaken, which
   change sign, and by how much. A pair that is weak instantaneously and strong
   seasonally, or the reverse, is a physical result about the mechanism and is
   worth a clause either way.
4. **The headline rung is the archive's native resolution,** because that is the
   resolution the data is published at; the coarser rungs are the sensitivity
   around it. This is `energy-counterfactual-pair-and-hierarchy-closure`'s native
   resolution rule - what this skill adds is that the other rungs get computed and
   shown rather than assumed away.
5. **Span is a second axis, not a replacement.** One column for the span the
   supplied file covers, one for any longer record you obtained; see
   `the-supplied-item-is-the-graded-unit` for why the supplied column survives.
6. **When a reference value r\* exists, name the rung it is consistent with**
   instead of reporting a bare gap. "We obtain A at the native step, B daily, C
   monthly; r\* corresponds to the C rung" is a reproduction. If no rung reaches
   r\*, say that explicitly, give the closest rung and the size of the gap, and
   list the candidate causes you can still discriminate: population (which
   entities, which node of the hierarchy), span, subsetting, unit or sign
   convention, or a genuine pipeline defect. An unexplained discrepancy is the one
   outcome to avoid; either explanation is a result.
7. **Put the ladder in the image, not only in a table.** These criteria are graded
   on a picture. Draw one compact matrix - the study's energy variables as rows,
   every supplied weather attribute as columns, in the source's order and under
   the source's names, the coefficient printed in each cell to two decimals,
   diverging colour map centred on zero - and make the rungs visible in that same
   image, as one row block per rung or as small multiples with the rung in each
   sub-title. A rung that lives only in `outputs/` or in a table cannot be seen
   where the work is judged, and a graded pair that is one cell of a dense
   composite is not much better off.
8. **Every pair the task or the source singles out gets a sentence in the text,**
   with both variable names and the number in it, in the results section. If a
   pair is in your matrix but not in your prose, a reader scanning for it will not
   find it - and neither will anyone checking your work against the source. Do not
   let the caption spend its space on the pairs your own hypotheses were written
   about while the pairs the source is about survive only as colours.
9. **Nulls are already required elsewhere.** One quantified effect for every
   supplied variable, including the ones that turn out not to matter, is
   `energy-counterfactual-pair-and-hierarchy-closure`'s rule. Apply it to the
   weather attributes here; do not re-derive it.

## Before you finish

Count the weather attributes in `data/` and count the ones named in your results
text. Then check that every headline coupling appears three times: as a cell in
the matrix figure, as a rung in the ladder inside that same figure, and as a
sentence with its number. A ladder that exists only in `outputs/` did not happen.
