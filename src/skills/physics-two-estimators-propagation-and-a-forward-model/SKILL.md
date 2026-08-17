---
name: physics-two-estimators-propagation-and-a-forward-model
description: Use at study design and analysis when a physical quantity is about to be reported from one estimator, or an uncertainty quoted without propagation. Covers measuring it a second independent way, propagating the error through the chain, and generating the observable forward from the fitted model to check it.
---

# Physics: measure it twice, propagate it, and generate it

Matching a published measurement is the floor in physics; you exceed it in four specific ways, so design for them up front.

Measure the same quantity through two or more independent estimators or measurement channels and quantify their agreement with a paired plot, residuals and a chi-square using per-point uncertainties, rather than asserting it. Where one channel reaches beyond the other, validate the proxy on the overlap region before relying on it outside.

Attach an uncertainty to every number and a propagated band to every model curve drawn against data, obtained by Monte Carlo or analytic propagation from the inputs' own uncertainties. For ensemble points, state how many members contributed and confirm none were dropped.

Generate data rather than only re-fitting the observation: at least one result should come from a stated forward model, an energy minimisation, a kinetic simulation of the process, an error-budget model, compared against the measurement. When the claim concerns a process, plot the process itself, observable against time, step or index with the state label on it, plus the event-type statistics; final-state energies do not evidence a mechanism.

Re-derive derived quantities from the rawest artifact available, treating shipped peak positions, landmark tables and summary files as claims to verify. Check absolute scale and units against known physical bounds and an independently computed characteristic scale. Sweep each control variable separately with the others held fixed, both directions where the data form a grid. Give every claim one self-describing figure and put its number in the summary.

## Why this is here

Eight of Physics's fourteen items sit in the 45-60 parity band, and moving that cluster is worth about +10 discipline points; the measured route above parity is more independent estimators, tighter propagated uncertainties, wider sweeps and validation of the estimator's own assumptions, none of which the bare agent did systematically. The process-figure clause targets the one near-absent item in the discipline (score 5, weight 0.30): the agent ran the simulation and reproduced the effect but plotted final-state energies instead of the process, and never computed the event-type statistics.
