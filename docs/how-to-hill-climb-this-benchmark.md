# How to hill-climb this benchmark

The point of the ablations is not rigour for its own sake. It is to make the score go up,
reliably, one change at a time. This document is about why that has not been happening and
what to do instead.

Companion to [What actually moves the score](what-actually-moves-the-score.md), which has
the measurements. This one has the method.

---

## 1. The problem, in one line

**The steps being taken are smaller than the ruler being used to measure them.**

| | |
|---|---|
| typical change being tested | 1–2 points |
| what a 40-task paired arm can detect | **3.29 points** |

Measured, not assumed: over 71 paired differences between arms that share a skill pack and
differ only in code or flags, the standard deviation of the paired difference is **7.44**.
At n=40 that gives 2.8·σ/√n = 3.29 points detectable at 80% power.

Everything below the ruler comes back as a coin flip wearing a story. That is the whole
explanation for the record's history of reversals:

* pins "worth +8.32 over regression to the mean" → the same pins are +1.68 against a
  different reference, and the effect is the size of its own placebo
* deleting the skill pack "worth −3.16" → +1.6 ± 1.0 once the second 161-pack arm is
  included, with a same-pack placebo of +1.72 beside it
* "the first arm ahead of bare Claude Code" → 95% CI −0.13 … +6.11

None of those was sloppiness in the arithmetic. Each was a real number, correctly computed,
that the design could not distinguish from zero. **A hill-climb that reads noise as signal
does not climb; it random-walks and writes changelogs.**

There are exactly three ways out, and they multiply rather than compete: sharpen the ruler,
take bigger steps, and test more hypotheses per unit of compute.

---

## 2. Sharpen the ruler — free, and worth more than it sounds

Three things cut the detectable effect without buying a single extra run.

**Pair on the task.** Already done everywhere: both arms run the same 40 tasks and the
comparison is the per-task difference. Task difficulty is the largest variance component
and pairing removes all of it.

**Run two controls, not one.** The comparator's own noise is half the paired variance.
Averaging two identical control arms cuts the comparator's contribution by √2. The `base_a`
/ `base_b` pair in the `eff1f5d` quartet exists for this, and it doubles as the first
honest measurement of run-to-run spread over all forty tasks.

**Decide on the stable tasks.** The variance is not spread evenly. Over the same-pack
pairs, mean |difference| per task runs from **0.37** (`Physics_001`) to **18.15**
(`Math_001`):

| decision set | σ of the paired difference | detectable |
|---|---:|---:|
| all 40 tasks | 7.44 | 3.29 |
| all 40, mean of two controls | 7.44 | 2.85 |
| 32 stable tasks | 4.60 | 2.28 |
| **32 stable, mean of two controls** | 4.60 | **1.97** |

Dropping the eight noisiest tasks buys as much resolution as doubling the compute.

**Two conditions on that last row, and they are not negotiable.**

*The subset is a decision instrument, never a reported score.* The benchmark number is all
forty tasks. A subset chosen for low variance is for deciding whether a change helped; the
moment it appears in a headline it is cherry-picking.

*The subset must come from same-configuration pairs, and the ones available today are too
thin.* The per-task variances above rest on one or two observations each, so picking the
eight worst partly picks noise — the winner's curse, applied to variance. `base_a` vs
`base_b` gives a clean per-task estimate on all forty from a genuinely identical
configuration. **Define the stable set from that arm and from nothing else.**

Note what does *not* help: more judge draws. Judge sampling is roughly a tenth of the
paired variance at three draws. The noise is the pipeline, not the grader.

---

## 3. Take bigger steps — and know the size before you spend the arm

At a detectable floor near 2 points, a change whose mechanism predicts one point is not
worth an arm. It is worth a mechanical check and then a decision to drop it.

**Predict the effect mechanically first.** Every change to routing, prompts or packs has a
blast radius that can be computed from the repository in seconds, with no runs at all:

* `select_run_skills` answers *"how many of the forty tasks does this change, and by how
  many skills?"* This is what showed the task-id pins add a median of one skill to 16 of 40
  tasks, and that the `bb32a8c` pins added four skill-installs across a whole arm — 0.4% of
  that arm's 943. Neither needed an experiment.
* `format_skills_for_prompt` answers *"how many characters does this move in which stage
  prompt?"* This is what showed the skills block is 0.19–0.72% of a stage prompt, killing
  the prompt-budget theory for free.
* The score files answer *"how much weight is even available here?"* This is what showed
  coverage is finished — image criteria scoring zero are already under 2% in every strong
  arm, against the control's 8.5% — so any change whose mechanism is *"the run will now
  also produce X"* is aimed at an exhausted channel.

**Three ideas died this way in an afternoon and cost nothing.** That is the cheapest part
of the loop and it should always run first.

**Then rank candidates by predicted effect, and refuse the small ones.** A change worth an
arm has to clear about 2 points on a stated mechanism. The two arms now running are the
worked examples: the figure floor predicts (15 − 12) × 0.79 ≈ **+2.4**, and the 45-skill
withhold removes 45 of ~68 offered skills on **all forty tasks** rather than four
skill-installs across one.

---

## 4. Test more hypotheses per run — stop doing one-at-a-time

This is the largest available win and it is a change of search algorithm, not of effort.

One change per arm pair is the wrong design at this noise level. A **two-level fractional
factorial** turns each arm into a data point about every change at once: run each candidate
change on in half the arms and off in the other half, chosen so the on/off patterns are
orthogonal, then read each main effect as the difference between its two halves.

Same 320 runs, eight arms, 32 stable tasks:

| design | changes tested | detectable per change |
|---|---:|---:|
| one change at a time | 4 | 3.22 |
| **fractional factorial** | **7** | **1.61** |

Twice the hypotheses at half the interval — a factor of four in search efficiency, for the
same machine time. The reason is simple: in a one-at-a-time design every run informs one
comparison, and in a factorial design every run informs all of them.

**The honest cost.** Seven factors in eight arms is saturated and resolution III: each main
effect is aliased with two-factor interactions. That is the accepted screening trade-off —
you are ranking candidates, not publishing effects. **Whatever wins the screen gets a
dedicated confirmation arm against a pinned base.** Screening finds the hill; confirmation
is how you check you are standing on it.

If interactions are suspected, sixteen arms buys resolution IV. That is still five changes
per arm-pair-equivalent, and still better than one.

---

## 5. The loop

1. **Pin a SHA.** Never run from `main`. `main` has drifted past every configuration ever
   scored — 168 skills and 420 pins today, against the 120 and 161 that were measured.
2. **Predict mechanically.** Blast radius from `select_run_skills`, prompt delta from
   `format_skills_for_prompt`, available weight from the score files. Drop anything under
   ~2 points before it costs a run.
3. **Screen several changes at once**, each expressible as one argument, from one tree.
   That is what `--skills-dir`, `--withhold-skills` and `--min-report-figures` are for
   (#326): an arm becomes a command line the artifact records, not a worktree someone
   edited.
4. **Verify the manipulation from the artifact, not the command.** `run_config.json` now
   carries `skill_pack` — source, installed count, withheld set, and a digest over the
   installed names. In the quartet now running, `figfloor` and `base_a` share the digest
   `5408d8e9`, which proves the pack is identical and only the floor moved; `noskills` is
   66 → 21 installed at the same floor. Check this before the scores arrive, because
   afterwards it is too late to learn the arm did not do what it was labelled.
5. **Decide on the stable subset; report on all forty.**
6. **Confirm the winner** in its own arm against a pinned base.
7. **Write down what was falsified.** Half the value of this record is the list of things
   that do not work — read counts do not predict score, coverage is exhausted, the prompt
   budget is not the constraint, the pins are inert. Each one that stays written down is an
   arm nobody spends again.

---

## 6. What this predicts about the next few rounds

The remaining weight is not where the last three arms' gains came from. Image criteria
scoring zero are under 2% everywhere; **34–43% of all weight now sits in the 21–40 band —
*attempted, and flawed or shallow*** — and that block is larger in every strong arm than in
the control, because that is where the coverage gains landed.

So the next round of candidates has to be about making an attempt *correct* rather than
making it *happen*, and each needs a mechanism that survives §3's mechanical check before
it earns a slot in a screen. That is a harder search than the one that got the score from
23 to 40, and it is the one that is left.

Related: [What actually moves the score](what-actually-moves-the-score.md) ·
[The skill-routing arm](rcb-skill-routing-arm.md) ·
[The benchmark landscape](researchclawbench-arms.md)
