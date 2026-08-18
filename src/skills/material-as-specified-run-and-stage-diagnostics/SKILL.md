---
name: material-as-specified-run-and-stage-diagnostics
description: Use at study design and implementation when a protocol is specified and you have found a reason to deviate, or when a pipeline stage is about to run without its conventional diagnostic. Covers running the protocol as specified as the foreground result, and leaving every stage's default panel behind you.
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Run the protocol as specified as the foreground result, and leave every stage's default diagnostic panel

Materials pipelines are graded stage by stage, so run the protocol exactly as specified before you improve it: the given parameter values, cell sizes, sample counts, budgets and convergence thresholds. That run is the foreground result, reported in the protocol's own units. Nearly every supplied specification has a defect you will find; the audit belongs in a clearly separated second analysis with the delta attributed, and must not take the title, the abstract's first sentence, or panel (a). A lead figure captioned with what is wrong with the spec is read as a declined reproduction even when the correct number sits in a table two sections later.

Emit each stage's default diagnostic panel even when a deeper analysis supersedes it: input characterisation (N per split, class balance, target range, replicate noise), training and validation objective versus epoch, held-out metric versus step, parity plot against the reference with the identity line, best-so-far versus evaluation count, generated-versus-reference scatter in the physical parameter space. These panels are cheap, conventional, and their absence is unrecoverable.

**A named method may not enter a cut order.** When the budget will not carry everything, cut the
extension, the extra seeds, the second substrate — and run the paper's own method at one seed and
fewer epochs instead. A reproduction at a fifth of the scale scores; a reproduction replaced by a
cheaper engine does not. One run listed the paper's graph encoder as item (5) of its cut order,
took the cut, shipped gradient boosting as the headline, and watched that criterion go 28 -> 5
against a plain agent's 38.

When the specification names a method family -- a particular surrogate, optimiser, simulator or architecture -- run that one and report it, then place your alternative beside it rather than instead of it. When the final validation needs an instrument you lack (synthesis, a measurement, a high-fidelity simulation), do not drop the stage: report the best available proxy, label it a proxy, quantify its uncertainty, and give it its own panel.

## Why this is here

Targets the four Material mechanisms that produce 0-35 scores with no absence: task substitution (all four bare runs detected a defective spec and made the audit the headline, so the demanded number existed nowhere), framing inversion (the correct result relegated behind a 'the spec is broken' lead panel scored 25), the never-plotted standard diagnostic (a weight-0.5 criterion scored 5 and 0 because loss- and accuracy-versus-epoch traces were judged too boring to draw), and the silently dropped wet-lab/expensive-simulation stage.
