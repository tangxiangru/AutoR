---
name: physics-discriminate-model-families-and-defend-the-fit
description: Use when the research task is in physics — condensed matter, many-body theory, simulation and physical modelling — at study design, analysis or writing. Physics: exclude a named model, and treat the fit protocol as part of the result
---

# Physics: exclude a named model, and treat the fit protocol as part of the result

Name the competing model families before you touch the data. A physics result is not "our number is good"; it is "quantity Q, measured against control X with everything else fixed and carrying an uncertainty, follows family A and excludes family B". Fit every candidate family to the same data on a common footing, report a per-family goodness-of-fit, and state which families are excluded and at what confidence. The supplied materials usually name the alternatives; where they do not, the conventional theory and a trivial null are still required arms.

When the reported number is a parameter of a functional form, an exponent, a slope, a critical value, treat the fit protocol as part of the result. That value depends on the abscissa, the fit window, the weighting, and which reference quantities (amplitude, critical point, offset) are held fixed rather than free. Enumerate those choices, report the parameter under the field's standard convention first, and attach a sensitivity table over the alternatives. Test the fixed-exponent model with a goodness-of-fit statistic in addition to free-fitting the exponent: the two answer different questions and can disagree by a factor of two when the small-signal end is noise-dominated.

Run the original protocol on its own terms and report that outcome as the headline for each target result. Data-provenance problems and alternative interpretations belong in a subordinate section, and "the effect is present with the wrong functional form" must be stated separately from "the effect is absent".

## Why this is here

Physics has 0% absent, so its headroom is the five items scoring 28-38, every one of them a case where the agent's number contradicted the paper through fit-protocol choice rather than through error. In one task the criterion's own fixed-form goodness-of-fit test passes on the shipped data (R-squared 0.9886) while the agent free-fitted a log-log exponent, got a different value, and declared the effect refuted; running both would have kept the item. The model-family clause targets the discipline's constant claim grammar, which three of four tasks state explicitly as two or more named alternatives.
