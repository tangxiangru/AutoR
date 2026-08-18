---
name: math-canonical-curve-on-the-cost-counter
description: Use at figure planning when a convergence or performance curve is about to be drawn against wall-clock, or folded into a composite panel. Covers the field's plain two-curve figure, plotting against the algorithm's own cost counter, and why it comes before any richer diagnostic.
stages: 03_study_design, 05_experimentation, 06_analysis
---

# Draw the field's plain two-curve figure against the algorithm's own cost counter, before any richer diagnostic

In algorithms and optimisation the standard result artifact is one plain figure: the field's headline scalar on the ordinate against the algorithm's own implementation-independent cost counter on the abscissa, with every competing method on the same axes as an additional curve or a labelled horizontal reference line. Draw that figure first, alone, in its own panel. Folding it into an eleven-series multi-panel diagnostic destroys it -- a reader has to be able to see one curve sitting below another.

Pick the abscissa another group can reproduce on different hardware: iteration index, oracle or function evaluations, node expansions, sample count, instance size, number of agents or items. Wall-clock time is a legitimate second figure and never a substitute for the first; on a shared or loaded machine it is also the axis a referee discounts. For residuals, duality gaps and objective gaps use a logarithmic ordinate across the full decade span, and draw the target tolerance as an annotated horizontal line.

State the headline scalar in the paper's own unit on a three-point scale: prior method, your method, and the oracle, human or ideal reference where the field defines one. If the available instances are smaller than the benchmark the claim concerns, run the reduced set anyway, report the achieved-versus-target ratio explicitly, and support it with a scaling curve across instance size. An arm deferred in a limitations bullet is scored as an arm never run.

## Why this is here

Math's headroom is entirely in the quantitative/figure criteria (71% of weight, agent mean 21/100), and the two lowest scores in the discipline (5 and 3) were both this exact failure: the canonical two-curve plot was produced but buried inside an eleven-method multi-panel composite (5/100 on a 0.30-weight item), and a progress curve was drawn against wall-clock instead of the algorithm's own iteration counter (3/100). It also converts the measured 'scoped out in Limitations' loss into a reduced-scale run with a stated achieved-versus-target ratio, which scored 25 rather than 0 the one time it was done.
