---
name: astronomy-error-budget-is-the-audit-trail
description: Use at analysis and writing when a result rests on a fit or a calibration chain and you are about to quote it with a single uncertainty. Covers itemising the error budget term by term, keeping the fit's own bookkeeping visible, and why the audit trail is the result a referee checks first.
---

# Astronomy: the error budget and fit bookkeeping are the audit trail

Decide the uncertainty machinery at design time, because it dictates what you must store. Propagate from the full measurement distribution, Monte Carlo over posterior samples or a full covariance matrix, never from a point estimate plus an error bar, and name the propagation method and which correlations it carries and which it drops.

Where a fit is involved, state its bookkeeping: how many constraint equations, broken down by category; how many free parameters; the resulting degrees of freedom; chi-square per degree of freedom; and whether the covariance used was diagonal or full. Read the reduced chi-square as a statement about whether the error budget matches the residuals. Then draw the residual diagnostic: model minus each individual measurement, one point per constraint, with its error bar and a zero line. Astronomers read that panel first, and an rms quoted in prose does not replace it.

Characterise the input catalogue quantitatively before modelling: sample count, central value and dispersion, correlations between inputs, units, and the assumed auxiliary quantities nobody measured. Report mean with standard deviation and median with percentile interval; subfields differ on which is conventional.

State the headline as value plus or minus uncertainty with units, an explicit confidence level, the relative precision, the object or range it is conditioned on, and the discrepancy from the community value in sigma. If you conclude the inputs cannot support the published value, still emit that value, its diagnostic figure and the structural counts in this form, and report the discrepancy beside them.

## Why this is here

Astronomy's mechanism 3 (task reframing) cost all three criteria of one task, 25-28 each, because the target-form deliverables (headline value at the stated precision, the equation/parameter/dof accounting, the residual diagnostic) were never emitted while the agent wrote a forensic audit; the final clause forces them out anyway. Mechanism 4 (convention mismatch: median with credible interval where mean plus sd is the field's habit) cost about 15 points on an otherwise strong criterion, fixed by reporting both. Mechanism 1's skipped cheap first step, characterising the input layer in standard form, is the opening clause.
