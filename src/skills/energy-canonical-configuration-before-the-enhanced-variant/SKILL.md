---
name: energy-canonical-configuration-before-the-enhanced-variant
description: Use at study design when you are about to run an improved variant of a system before its default configuration, or fold several claims into one panel. Covers running the default recipe with its conventional diagnostics first, and giving each claim its own plain panel.
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Run the default recipe with its conventional diagnostics, and give each claim its own plain panel

Two things get engineering and energy reproductions marked incomplete.

The default configuration. Implement the field's canonical recipe exactly as specified - the given sample count, architecture, optimiser, budget, convergence tolerance, solver settings - and report its conventional diagnostics: the loss actually optimised with its start and end values, iteration or epoch count, how many model evaluations were attempted and how many converged, wall time per pipeline stage, and the speed-up claimed against the method it replaces. Only then run your improved variant, and present it as an ablation against that baseline. A study that goes straight to the better design leaves every diagnostic the field expects unreported, however superior it is. Use the field's published error definitions rather than substituting your preferred statistic.

**A named method may not enter a cut order**, and a design is not frozen until it has run. Pilot
the box with 24-48 real evaluations before committing to it, and record attempted, succeeded and
the failure mode. A 37.5% pilot yield is not a caveat to carry forward, it is the design telling
you it is the wrong box: one run recorded exactly that, ruled it "a guard and not a re-design",
froze the preregistration, and shipped 27.1% convergence to the reader.

Error per unit, not only pooled: a true-versus-estimated table with one row per estimated parameter, per site, per asset or per variable, carrying an absolute and a relative-error column, alongside the aggregate residual metric.

Figures. Give every headline claim its own single-purpose panel in the canonical diagnostic form: a two-series overlay when claiming agreement, a stacked decomposition when claiming a total splits, a utilisation-ratio time series when claiming a limit binds, a map at the native spatial unit when claiming heterogeneity. A dense multi-panel composite of novel diagnostics is an addition, never the only place a claim appears. And if you judge the supplied inputs unrepresentative, still run the pre-specified analysis on them and report it first, with the audit in a clearly separate later section.

## Why this is here

On the inverse-identification task the agent ran a far better study than the reference - large design of experiments, deep ensemble, Sobol screen - and never ran the textbook small-design plain-MLP configuration, so every criterion asking for the standard recipe's diagnostics (training MSE trajectory, epoch count, run yield, per-parameter true-vs-identified error) scored 0 or 25; it reported held-out R-squared where the field reports training MSE and per-parameter percent error. Separately, three of the four zero-scored Energy criteria were single plain panels that no 4-panel composite contained. The audit-ordering clause addresses the run that discarded the supplied files entirely and scored 8.4.
