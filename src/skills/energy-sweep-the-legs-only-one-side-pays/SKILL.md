---
name: energy-sweep-the-legs-only-one-side-pays
description: Use at study design when the perturbation list is drafted, and at analysis, whenever the deliverable compares a cost assembled from a chain — production plus transport plus conversion — against a cost assembled somewhere else. Covers which legs decide a margin, routing the chain per origin instead of scaling a straight line, and sweeping the far side's assumptions rather than only your own plant's.
applies_when: ammonia shipping and reconversion
stages: 03_study_design, 05_experimentation, 06_analysis
---

# In a delivered-cost comparison, sweep the legs only one side pays

When the deliverable compares a good produced here and moved there against the
same good produced there — landed against domestic, imported against incumbent,
exported against local build — the margin is decided by the terms that appear on
one side of the comparison and not the other. Shared terms move both sides
together and cancel. Your sensitivity budget will drift the opposite way on its
own, because the plant is where you spent the run: its capital costs, its
efficiency, its financing and its resource are the parameters you know best, and
most of them are shared or nearly so.

So invert the order of attention. Before the perturbation list is frozen, write
the chain out leg by leg and mark each one **paid by both**, **paid by us only**,
**paid by them only**. Then:

1. Every leg in the second and third groups gets a sweep, over the range the
   literature actually publishes for it, whether or not any of your hypotheses
   mention it. These are the legs that can move a verdict on their own.
2. A leg the source quotes as a single number is not necessarily a measured
   value. Check what it was computed at — an electricity price, a heat source, a
   utilisation, a plant scale — and whether your own study sets that input
   differently. Where it does, the defensible value is a range, and the whole
   study is reported at both ends of it, in the same table and the same figure,
   not in a sensitivity appendix.
3. Report each asymmetric leg three ways: its value, its share of the delivered
   total, and its spread across your domain. A leg whose spread across the whole
   map is smaller than your rounding is telling you either that the leg is
   genuinely flat or that your domain is too small to make it vary — and when the
   domain was handed to you as a sample, the second is much the likelier.

## Route the chain; do not scale a straight line

A great-circle distance times a detour factor is a placeholder. It is fine for a
first cost, and it is worthless for the question a study like this is read
against, which is *which origins are close to the market*. A placeholder answers
that with a constant, and then the origin advantage the task asked you to
identify does not exist anywhere in your numbers.

Assign every origin its own exit point by minimising inland cost plus onward
cost over a list of real terminals — the boundary layer you were given plus a
published port or hub list is enough. Take the onward distance from a routing
library, or from an explicit path that names the canal or the cape it goes
round, and say which. Then publish the distance distribution and the resulting
per-origin leg cost as a map, beside the map of the total. Inland haulage gets
the same treatment: the mode is a choice with a minimum viable throughput, so
check whether the alternative mode was ever admissible at your demand before
reporting that it lost.

## The threshold usually lives on the other side

The line you classify against — the incumbent's cost, the local build, the
benchmark price — is normally assembled from one or two exogenous numbers that
describe the far side and nothing about your domain. Those are the highest-value
sweeps in the study, and they are the ones a plant-centred perturbation list
never contains. Sweep them over their published ranges as a matter of course,
report the headline at both ends, and state which end the source's own published
values are consistent with. A verdict quoted at one point of a factor-of-two
range is a verdict about that point.

`energy-counterfactual-pair-and-hierarchy-closure` owns the closure and the
per-layer effect; `energy-publish-the-ordering-when-the-level-fails` owns what to
report when the count at the threshold is zero. This skill is only about which
terms deserve the sweep budget.

## Why this is here

Energy_002. In `outputs/s05_ablation_results.csv` the run declared eighteen
distinct perturbations, across fifteen ablation ids, and ran every one of them:
resource arm, cost-of-debt reading, resource mapping constant, sovereign spread,
political-risk price, turbine curve, electrolyser capex, cost of capital, site
set, two ammonia parameter rows, storage sizing, synthesis electricity, synthesis
capex basis, three opex fractions, a shipping detour factor and an omitted
battery. Exactly one touches
the export chain and none varies the reconversion charge at the far end, which
the report states once, as €0.617/kg, inside a figure caption. Its sea leg is a
great circle inflated by a detour factor, and across the thirty supplied
coordinates it spans 7,730 to 9,127 km and moves delivered cost by €0.045/kg — so
the "delivered" half of a delivered-cost study had no variation in it at all. The
plain agent assigned each cell a port over sixty-five export ports with a routing
library, reported sea freight of €0.07–0.36/kg, and says its results are reported
at both ends of a published €0.47–1.17/kg reconversion range — which is what let
it say of its own two competitive shares that they track the published pair.
Both sit a little under it: 1.6% and 9.2% against 2.1% and 11.0%, and its sweep
of the reconversion charge moves the second from 1.7% to 9.2% without reaching
11.0%. The graded item that turns on export competitiveness, weight 0.25, scored
38.7 against 56.7.
