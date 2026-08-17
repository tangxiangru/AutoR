---
name: run-the-conditions-the-source-ran
description: Use at study design, before any experiment of your own is costed, on reproduction and method-evaluation tasks. Covers enumerating the systems, scenarios, stress sweeps and case studies the source names, running each one by name, measuring the preconditions the method declares it needs, and what to do when one of them fails.
stages: 01_literature_survey, 03_study_design, 05_experimentation
---

# The source's own systems, scenarios and stress tests are your experiment list

A paper's results are attached to specific things: named systems, named
scenarios, a named molecule, a named problem, a named noise axis, and the
conditions the method says it needs. A checklist for reproducing that paper is
written from those names. A better-designed experiment on different conditions
answers a question nobody asked.

## The failure this prevents

A run reproducing a feature-selection method replaced the paper's robustness
experiment — degradation under falling signal-to-noise, reduced library size and
increased dropout, against two named baselines — with its own structured
confounder and batch-geometry design. Better science, in the abstract, and the
reviewer wrote: *"it does not perform or report any simulations varying SNR,
library size, or dropout, nor explicitly compare performance degradation curves
versus Laplacian Score or MCFS."* That requirement scored **5**. A plain agent
that simply ran the paper's sweep scored **65** on the same requirement.

The same shape recurs, and it is never laziness — it is always a substitution
made for a good local reason:

* A chemistry run judged that saliency maps are not interpretable enough to be
  worth computing, and argued the point instead of computing them on the paper's
  own molecule: 5 against 70.
* A climate run carried two of three named SSP scenarios and dropped the third;
  the requirement that names it scored 12 against 38.
* A geometry run built a general traceback facility and never ran it on the
  paper's worked example, IMO 2004 P1: 5 against 18.
* A tracking run measured at literature stage that the supplied data violates the
  method's flat-ground assumption — correlation 0.146, camera height constant
  within each track — and then never mentioned it again. The word "perspective"
  occurs 0 times in its report and 4 times in each comparator's.

## What to do

1. At literature stage write `notes/source_experiments.json`: one row per named
   system, sample, scenario, stress axis, ablation and worked case study, each
   carrying the baselines it is compared against and the numbers the source
   reports for it. Add a row for every condition the method **declares it
   needs** — a ground plane, i.i.d. residuals, sparsity, a calibrated confidence
   channel.
2. Run every row before any variant of your own, and use the source's names in
   the section heading. Your improved design is an extra row, never a
   replacement. If the budget cannot carry both, cut your variant.
3. Measure each declared precondition on the supplied data and report the number
   where the mechanism is introduced — not in Limitations. A precondition that
   fails is one of the strongest things a reproduction can find, and it is worth
   nothing if the reader meets it as an apology on the last page.
4. When a precondition fails, build the counterfactual: construct or simulate
   data where it holds, re-run the same comparison there, and report the pair.
   That turns "the assumption does not hold" into "the assumption does not hold,
   and here is what it costs" — which is the finding.
5. A row you cannot run still gets its subsection, with the source's number, what
   you did instead, and what the gap is. Silence on a named experiment reads as
   an experiment nobody thought of.

## Before you finish

Walk `source_experiments.json`. Every row should map to a heading in the report
that uses the source's own name for it. A row whose answer is "we did something
better" is the failure above, wearing its best clothes.
