---
name: tuning-curves-report-the-argmax-and-its-error
description: Use at experimentation, analysis and writing whenever you sweep a stimulus, dose or environment parameter across a population of units and reduce each unit's responses to a selectivity, modulation or preference index. Covers extracting the preferred level alongside the index, its per-unit error against an expected value with a chance line drawn, naming groups and clusters by what they prefer, and the artifact-key audit that catches a result computed into a sibling key no panel draws.
benchmarks: researchclawbench
stages: 05_experimentation, 06_analysis, 07_writing
---

# A tuning measurement produces two results. Report both.

You sweep a parameter -- direction, orientation, wavelength, frequency, dose,
concentration, temperature -- and record a response per unit per level. That
sweep yields two independent results per unit:

1. **How strongly the unit is tuned.** A selectivity or modulation index: a
   contrast between the best and worst level, normalised somehow.
2. **Which level the unit prefers.** The argmax, the fitted peak, or -- for a
   periodic parameter -- the angle of the vector sum over levels.

The second is almost always the one an independent measurement exists for.
Anatomy, physiology, spectroscopy and the source literature publish *preferred
values* -- the level at which a unit responds best: this channel peaks at
480 nm, this catalyst is best at 340 K. They rarely publish your index, whose
definition and normalisation are yours and whose threshold you imported from
someone else.

## What goes wrong

The analysis computes the index, imports a threshold, counts how many units
clear it, and reports the count. The preferred level -- already present in the
same array, at zero extra compute -- is never extracted, or is extracted into a
results file, or a sibling key of a results file, that no figure ever draws.
What reaches the reader is "k of n units are selective": a number that moves
when the threshold moves, and that says nothing about whether the model got the
science right. A model can score a low count because its units are *weak* or
because they are *wrong*. Those are opposite findings, and only the argmax
separates them.

A second casualty follows. Downstream groupings -- clusters of models, seeds,
replicates or conditions -- then get labelled `cluster 0`, `cluster 1`,
`cluster 2`, because nothing in the analysis can say what distinguishes them.
An anonymous cluster makes no claim. A cluster named "prefers the correct
level", "prefers the opposite level", "has no preference" is a result, and the
ordering of those groups by fit quality or task error is a second one.

## What to produce

At **experimentation and analysis**, for every unit in the population, out of
the same sweep:

- the selectivity index, defined once in one module that every arm calls;
- the preferred level in the parameter's own units (degrees, nm, Hz, K, mM).
  For a periodic parameter use the circular resultant, not the discrete argmax,
  and report the resultant length beside it as the sharpness;
- the **error** of that preferred level against the known or expected value, per
  unit, wherever such a value exists -- and name where the expected value came
  from, per unit, not per table;
- the chance level of that error so a reader can size it: for a full-circle
  parameter a random preference is off by a quarter turn on average, for a
  bounded sweep by about a third of the range. Draw it as a line.

At **writing**, one figure carrying:

- per-unit |preferred-level error|, sorted, every unit labelled, the chance line
  drawn, and one point per replicate behind the summary so the spread is visible;
- the curves themselves for every named unit -- one small panel each, replicates
  in light grey, your central estimate in one colour, the published or expected
  curve overlaid, and the correlation to it in the panel title.

Then use the preferred level as a **label**. Any clustering, model selection or
grouping done afterwards names its groups by what their members prefer and how
far that is from the expected value, gives the group sizes, and puts the group's
fit or task error in the same panel.

## Threshold hygiene

- A count at a threshold may be reported, but never alone and never first. Show
  the continuous distribution it was cut from in the same panel with the
  threshold drawn, so a reader can see whether units sit far from it or pile up
  on it.
- If the threshold was imported, say so, and say whether you re-derived it. A
  count "at the published threshold" and a count "at a threshold derived here"
  are different results and should not be compared.
- Never let a threshold count be the sole evidence for a negative conclusion
  about your own reproduction. Check the argmax errors first: units that prefer
  the right level weakly are a different story from units that prefer the wrong
  one, and only the second is a failure to reproduce.

## Checklist

- [ ] Index, preferred level and resultant length computed for every unit, by one function.
- [ ] Preferred level in the parameter's own units, with the sweep resolution stated.
- [ ] Per-unit error against an expected value, with that value's source named per unit.
- [ ] Chance level computed, stated and drawn.
- [ ] Curve panels for every named unit with the expected curve overlaid.
- [ ] Every downstream cluster or group named by what it prefers, never by an integer.
- [ ] No threshold count appears without the distribution it was cut from.
- [ ] For each figure slot, enumerate **every key** of the artifact it names and tick off
      which ones the panel draws. A slot that opens an artifact and plots the index while a
      sibling key holds the preferred level has drawn half the result. The weaker second
      check: grep the figure scripts for the files holding your argmax tables -- if nothing
      opens them, those results do not exist.
