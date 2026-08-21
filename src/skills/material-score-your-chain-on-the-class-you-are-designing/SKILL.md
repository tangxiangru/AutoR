---
name: material-score-your-chain-on-the-class-you-are-designing
description: Use at experimentation, analysis and writing when a calibration or reference table you fitted on is a mixed population and the objects you are designing are one class inside it. Covers finding those rows by name, reporting the chain's error on that subset per row rather than folding it into the pooled statistic, and why that subset is usually the only experimental validation available in the workspace.
benchmarks: researchclawbench
applies_when: \b(?:vitrimer\w*|glass transition temperature)\b
stages: 05_experimentation, 06_analysis, 07_writing
---

# Score your chain on the class you are designing, by name

A calibration or reference table is usually a mixed population: a few hundred materials of many kinds, assembled because they all carry the property. The objects your study designs are one class inside that mixture, and often only a handful of rows belong to it. Those rows are worth more than the other several hundred put together, and pooling them away is the default because the pooled statistic is what the source quotes.

So look for them. Read the label, name or family column of every supplied table and select the rows that are instances of the class in your brief. In this task, three of the 295 rows in `data/tg_calibration.csv` are named `Vitrimer-DGEBA-AA`, `Vitrimer-DGEAC-SA` and `Vitrimer-DGEBA-SA`, with experimental Tg of 317, 304 and 323 K — the only experimentally measured members of the target class anywhere in the workspace. Where no name column exists, select structurally: the motif, the functional group, the phase, the composition range that defines the class, and say what rule you used and how many rows it caught.

## What to report

Per row, not pooled: the object, your chain's prediction, the measurement, the signed error, and whatever similarity or coverage statistic tells the reader whether that row was inside your model's support. Then the subset statistic beside the pooled one, both labelled with their n. Three rows is a small number and it is not a reason to suppress them — give the three, and let the reader see the spread rather than a mean over a population that mostly is not the material.

This subset does three jobs at once that nothing else in the workspace can do. It is the tightest available test of the whole chain end to end, because it is the only place the chain's output can be compared against an instrument. It bounds the class-specific bias your pooled error hides. And when the brief ends in an experimental validation you cannot perform, it is an experimental validation you can perform: real measurements, on real members of the class, predicted by your pipeline, with the deviation in kelvin.

Check the values as well as the errors. If one of those rows sits at the property value the study designs toward, say so explicitly — a chain that lands a measured member of the class at its design target is the sentence the whole reproduction is for.

## Where it goes

Its own panel and its own paragraph in the validation section, with the rows drawn as chemistry and the measured values marked as measurements. Three points inside a 295-point parity plot are invisible; the same three points on their own axis, named, with the pooled MAE drawn as a reference line, are a result. `material-deliver-a-candidate-a-chemist-could-make` covers the wider measurement axis and the candidate hand-over; this is the part of it that needs no external source at all, and it is the part that is easiest to walk past because the numbers are already in an artifact you wrote.

## Why this is here

Measured on Material_003. The run's own `calibration_loocv.json` holds all three vitrimer rows with per-row leave-one-out results: `Vitrimer-DGEBA-AA` calibrated to 334.75 K against a measured 317.0 K (17.75 K), `Vitrimer-DGEAC-SA` to 294.39 K against 304.0 K (9.61 K), and `Vitrimer-DGEBA-SA` to 321.20 K against **323.0 K — an error of 1.80 K at exactly the temperature the source's synthesised candidate was designed for**. The mean absolute error over that three-row subset is 9.72 K, against the 28.0696 K the run published over all 295 rows and repeated in its abstract, its lead panel and two figure captions. None of the three rows is named anywhere in the delivered report, and the section headed "Validating selected candidates experimentally: not performed" scored **0.0 in all three gpt-5.1 draws**, against 42.7 for a bare agent — 10.7 of that run's 18.5-point deficit, for a result the run had already computed.
