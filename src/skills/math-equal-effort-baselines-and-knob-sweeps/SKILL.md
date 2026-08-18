---
name: math-equal-effort-baselines-and-knob-sweeps
description: Use at study design when the source names competing algorithms and they are about to become a related-work paragraph instead of arms. Covers running every named baseline at equal tuning effort, and sweeping the parameter you claim credit for.
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Run every named baseline as a real arm at equal effort, and sweep the knob you claim credit for

An algorithmic claim is a comparison, so the baseline suite is a build item, not a related-work paragraph. Enumerate the named competitors from the references shipped with the problem, implement or install each as a real arm, and run them on identical instances at an identical budget, reported in the same table and the same figure. Give every arm the same tuning effort and the same optional machinery: if a baseline gets restarts, warm starts, preconditioning or a tuned step size, your method gets them too, and the reverse. An asymmetric enhancement is the commonest way an apparent speed-up turns out to be a configuration difference.

Attribute the gain. Ablate the novel component on and off, then sweep that component's own hyper-parameter across its range to locate the optimum and the point where gains saturate or reverse. A component reported only as present or absent leaves a reader unable to distinguish a mechanism from a lucky setting.

Report quality and cost as a pair for the same comparison -- objective value with iterations or time, solution quality with memory or node expansions, accuracy with throughput -- and give the break-even factor. Break results out per instance family and per problem regime the benchmark distinguishes, including families outside your method's design or training regime and families that are degenerate at the shipped settings. Each still gets its own reported row rather than being pooled away or dropped.

## Why this is here

Four separate measured demands sit in criteria the bare agent never emitted: the full named baseline suite as separate arms at identical budget (4 tasks), a component ablation that additionally sweeps the component's own hyper-parameter to find its optimum and saturation (3 tasks), the quality/cost pair for the same comparison (3 tasks, one lost because sum-of-costs was computed but never paired with the collision-reduction claim), and per-instance-family rows including degenerate families (3 tasks). It also fixes the observed asymmetric-component failure, where an enhancement was implemented for the competitor but not for the proposed method.
