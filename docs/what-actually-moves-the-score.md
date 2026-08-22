# What actually moves the score

Fifteen ResearchClawBench arms have now been scored on one instrument. This is what
they say when read together, and it is not what any individual arm's write-up said.

Everything below is `tools/score_rcb_run.py --judge reference --draws 3` against bench
`bfffc480` — gpt-5.1, three draws — because judge choice moves a score by roughly sixteen
points and a number carrying another judge is incomparable rather than smaller.

**One score per task, from the newest workspace that has one.** That rule is stated
because it has to be: eleven tasks in `full40_main40` have two or three workspaces, and
an analysis that lets glob order pick between them is not reproducible. (Checked: no task
currently has two *scored* workspaces, so on today's files the rule is not load-bearing.
It will be again.)

---

## 1. The scoreboard, 2026-08-21 06:15 UTC

| arm | n | mean | vs control | 95% CI | W–L |
|:---|---:|---:|---:|:---|---:|
| `pins_on` | 18 | 41.66 | +9.11 | +4.28 … +13.95 | 15–3 |
| `xrev_off` | 33 | 39.81 | +9.10 | +5.31 … +12.89 | 25–8 |
| `xrev_on` | 15 | 37.47 | +8.84 | +3.21 … +14.47 | 12–3 |
| **`full40_abl40`** | 36 | **40.71** | **+8.81** | +5.65 … +11.97 | 28–8 |
| `topo_adaptive` | 21 | 39.48 | +8.73 | +4.46 … +13.00 | 19–2 |
| `full40_a9c2b48` | 37 | 39.36 | +7.84 | +4.55 … +11.13 | 29–8 |
| `full40_skills161` | 37 | 39.36 | +7.80 | +4.85 … +10.75 | 30–7 |
| `pins_off` | 20 | 40.63 | +7.76 | +3.77 … +11.74 | 18–2 |
| `full40_main40` | 39 | 38.53 | +7.33 | +3.98 … +10.69 | 30–9 |
| `topo_linear` | 34 | 37.50 | +6.61 | +3.02 … +10.20 | 25–9 |
| `full40_skills` | 40 | 37.01 | +5.54 | +2.31 … +8.76 | 31–9 |
| `full40_pins` | 40 | 34.47 | +2.99 | −0.13 … +6.11 | 26–14 |
| `control_bare_cc` | 40 | 31.48 | — | | |
| `full40_v220` | 40 | 28.77 | −2.70 | −6.32 … +0.92 | 14–26 |
| `arm_2ffaeb4` | 40 | 28.75 | −2.73 | −6.32 … +0.87 | 20–20 |
| `full40` | 40 | 23.07 | −8.40 | −12.01 … −4.79 | 12–28 |

**Do not read the top of this table as a ranking.** Everything above `full40_skills` at
n < 40 is missing tasks, and the missing ones are not random: they are the tasks the
control scores well above its own average on. The ordering among the top eight is inside
the noise those omissions create, and three of those arms were still running when this
was written.

The table is a snapshot of files other processes are writing. Two scorers and several
arms were live at 06:15. Re-pull it before quoting it.

---

## 2. The lineage is a 2×2, not four independent arms

`full40_abl40` was described in #315, and in this repository's own commentary, as
"`main40` with forty task-scoped skill directories deleted". That is true of the
mechanics and misleading about the design. `abl40`'s skill directory is **byte-identical
to `a9c2b48`'s**: the 41 deleted files are exactly the 40 added by #270 plus the 1 added
by #266, and nothing else.

So four arms are one 2×2 — two skill packs crossed with two code revisions:

| | 120-skill pack | 161-skill pack |
|---|---|---|
| **code @ a9c2b48** | `full40_a9c2b48` 39.36 | — |
| **code @ 48501e7** | `full40_abl40` 40.71 | `full40_main40` 38.53, `full40_skills161` 39.36 |

which makes four paired contrasts available, two of which are placebos:

| contrast | what differs | n | paired | 1 SE |
|:---|:---|---:|---:|---:|
| `abl40 − main40` | pack | 35 | **+2.39** | 0.97 |
| `abl40 − skills161` | pack | 33 | **+1.33** | 1.48 |
| `skills161 − main40` | **nothing but code** | 37 | +0.33 | 1.25 |
| `abl40 − a9c2b48` | **same pack** | 34 | +1.72 | 1.24 |

Read the bottom two rows first. `skills161` and `main40` run the *same* 161-skill pack
and the *same* pin table, so their difference estimates the twenty commits of code
between a9c2b48 and 48501e7: **+0.33 ± 1.25 — nothing.** And `abl40` against `a9c2b48`
shares a pack, so it should also be near zero: it is **+1.72 ± 1.24**.

**That placebo is the whole problem.** The effect being claimed for the pack is +1.33 to
+2.39. A contrast that ought to be zero comes in at +1.72. The pack effect and its own
placebo are the same size.

**So "deleting the skill pack is worth +3 points" does not survive.** #315 reported
`main40 − abl40 = −3.16 ± 1.48` on 33 tasks and that arithmetic reproduces; what it lacked
was the second 161-pack arm, which was sitting on disk. Pooling both 161-pack arms as
replicates puts the pack effect near **+1.8**, against same-pack placebos of +0.33 and
+1.72. The honest word is *unresolved*, and the direction — smaller pack slightly better —
is worth another arm, not a revert.

---

## 3. `full40_a9c2b48` was not run at the same settings as the arms it is compared to

Every arm launched on 2026-08-18 or later ends its command with
`--stage-timeout 1800 --max-auto-skips 3`. `a9c2b48`'s forty runs end at
`--web-search gemini` and nothing else.

That is a different configuration, not a different commit, and it sits underneath the
`abl40 − a9c2b48 = +1.72` row above. **No claim that a9c2b48's code is better or worse
than 48501e7's can rest on that number** until the pair is re-run at matched flags. This
is the rule the repository already states — *a benchmark comparison is a claim about two
configurations* — applied to itself.

---

## 4. There is no routing layer to speak of

`docs/rcb-skill-routing-arm.md` §7.3a says the pins are redundant "because the shape
filter now selects around 66 skills per task unaided". The count is right; the
attribution is wrong, and the correct version is more useful.

| tree | skills | carry `applies_when`/`applies_unless` | unconditional |
|:---|---:|---:|---:|
| bb32a8c | 45 | 4 | 41 (91%) |
| a9c2b48 / abl40 | 120 | 4 | **116 (97%)** |
| 48501e7 | 161 | 44 | 117 (73%) |
| main today | 173 | 56 | 117 (68%) |

Almost nothing is routed. Sixty-six skills reach a task because they are *unconditional
or match its field by name prefix*, not because a predicate matched its brief. The
module docstring in `src/run_skills.py` describes a competition of descriptions in which
the right skills win; that mechanism is switched off for 68–97% of the pack depending on
the tree.

This is why the task-id pins are inert: not because a clever filter already chose well,
but because **nearly everything is offered to nearly everyone**, so a pin has almost
nothing left to add.

---

## 5. The figure lever was tested and falsified

> **Update 2026-08-22:** the `figfloor` arm from the eff1f5d quartet tested this directly
> by forcing every run to produce 15 figures. Predicted +2.4; measured **+0.44 ± 1.03**.
> The correlation was entirely "better runs make more figures", not figures causing better
> scores. The remainder of this section is the original analysis that predicted the effect.

Regressing each run's score on the number of figures it published, with **task and arm
fixed effects** so task difficulty and arm quality are differenced out, over 541 scored
runs across 20 arms:

```
score ~ images_available      beta = +0.786 ± 0.161   t = +4.87
```

and **423 of 541 runs (78%) publish fewer than fifteen figures, median twelve** — while
`RCB/evaluation/score.py:163` hands the judge `generated_images[:15]`. Runs are leaving
window unused.

The discriminating test, because "better runs make more figures" would explain the
correlation just as well:

```
IMAGE criteria ~ images_available   beta = +0.716 ± 0.269   t = +2.66
TEXT  criteria ~ images_available   beta = +0.410 ± 0.267   t = +1.53
```

The image slope is 1.75× the text slope and only the image one clears its standard error
— consistent with a real mechanism, since image criteria carry 60.6% of the weight and
the judge literally cannot see a figure that was not produced. But **the text slope is
not zero**, so part of this is runs that are simply better. **That "part" turned out to be
the whole thing.**

**The direct test.** Arm `figfloor` raised `BENCHMARK_MIN_REPORT_FIGURES` from 3 to 15.
Every one of its 47 runs topped out at exactly 15 images (`images_available` in
`_score_gpt51.json`), versus median 13 in the paired control arms. The manipulation was
uniform and it bit perfectly: **+2.91 figures ± 0.39** paired against the mean of `base_a`
and `base_b`.

The score effect, over n=31 scored tasks (out of 40, as of 2026-08-22):

```
figfloor − mean(base_a, base_b)   +0.44 ± 1.03   sd 5.71   W-L 14-17
```

95% CI roughly −1.59 … +2.47. Point estimate 18% of the predicted +2.4. **As a lever,
forcing figures does nothing.**

**What still works: the correlation as a selector.** Choosing the run with more figures is
choosing a better run for reasons unrelated to the figures themselves. Over `base_a` and
`base_b` at n=14 pairs, picking the longer report gains **+1.15 ± 0.74** against a single
random draw, capturing 48% of an oracle ceiling of +2.42. Best-of-3 projects roughly
+1.5–1.9, which is still larger than any pipeline change proven here — but it costs 3× the
compute per task.

---

## 6. Coverage is finished; everything left is depth

Weight scoring exactly zero, split by criterion type, over the same score files:

| arm | n | image at 0 | text at 0 | weight in band 21–40 |
|:---|---:|---:|---:|---:|
| `control_bare_cc` | 40 | 8.5% | 7.9% | 31.4% |
| `full40` | 40 | 14.2% | 15.2% | 39.8% |
| `full40_pins` | 40 | 0.8% | 4.8% | 40.8% |
| `full40_skills` | 40 | 1.9% | 2.5% | 37.0% |
| `full40_main40` | 39 | 0.0% | 2.6% | 34.0% |
| `full40_a9c2b48` | 37 | 0.0% | 1.0% | 42.7% |
| `full40_skills161` | 37 | 1.6% | 1.0% | 37.6% |
| `full40_abl40` | 36 | 0.7% | 1.7% | 40.8% |

**Every strong arm has driven empty image criteria from the control's 8.5% to under 2%,
and three of them to nothing at all.** Text is nearly as saturated. The entire gain
described in §9 came from that migration, and it cannot happen twice: there are no blank
cells left to fill.

What replaced them is the 21–40 band — *"attempted, and flawed or shallow"* — which is now
**34–43% of all weight in every strong arm, larger than it was in the control.** That is
the only block big enough to matter and it is the hardest kind of work: not producing a
missing artifact, but producing a right one.

This reframes every proposal. A change that helps a run *attempt* something is aimed at a
channel that is already exhausted. A change has to make an attempt *correct* — which is
why the figure lever in §5 is worth testing (more figures give the judge more to credit on
an already-answered criterion) and why another skill telling the run to remember something
probably is not.

---

## 7. The standing cost nobody is paying attention to

Pooled over five large-pack arms and 196 scored runs: **44 of the 61 always-installed
skills have a read rate at or below 5%.** They hold roughly 17.6k of 23k always-on
description bytes and account for 9% of all reads. Eight are offered in every single run
and have never been opened.

Meanwhile the read budget barely responds to pack size — 6.9 distinct skills read at 24
offered, 8.3–10.0 at 68–71 offered. The read *rate* falls from 29% to 12%.

Deleting the 44 lowest-read always-on skills is the change with the most predictable
blast radius available: every task, a known number of bytes out of every agent turn, and
a measured 9% of reads at risk. Like the figure floor it needs its own arm, and it must
not share one with the figure floor.

---

## 8. Three defects in the record, found while assembling this

**Fourteen finished reports were never scored.** `full40_abl40`, `full40_main40`,
`full40_skills161` and `full40_skills` have no live Slurm job and last wrote 46–78 h ago,
yet their `_meta.json` still says `running` — the stale-status defect #313 fixed, in
trees that predate it. Fourteen substantive reports sat unscored because of it. Scoring
them moved `main40` from +6.00 (n=35) to **+7.33 (n=39)**, which is most of the gap #315
attributed to the skill pack.

**A relaunch destroyed three scored workspaces.** `score-unscored/driver.log` records
`full40_a9c2b48 completed=40 scored=40` at 05:03:08 and `completed=37 scored=37` at
05:16:43. The three tasks — `Chemistry_000`, `Neuroscience_000`, `Physics_001` — now have
exactly one workspace each, created 05:15. #317's headline, *"the first complete AutoR
arm … +7.33 over all forty"*, is no longer reproducible from disk; the arm is at 37 and
the three are re-running. The scores are not archived anywhere: `~/rcb_results/autor_a9c_*_state.json`
holds only the runner's status, already repointed at the new workspace. Nothing in the
pipeline treats *"this workspace holds a score"* as a reason not to replace it.

**`abl40` cannot be re-run by anyone.** `Manager.skills_dir` is
`self.project_root / "src" / "skills"` with no flag, config key or environment override,
so there is no supported way to run AutoR against a subset of the pack. The best-scoring
arm on the board exists only as a dirty worktree with deleted files and no SHA. Its
`configs/task_skill_pins.json` is also JSON-corrupted — every string exploded into a
per-character array, and the `_rationale` provenance block replaced by a list of its own
keys. Runtime-harmless, and it destroys the only record of what each pin was aimed at.

---

## 9. What not to do

**Do not revert #270 as a measured +3.** §2. The best-powered estimate is +1.8 with a
same-pack placebo of +1.72 beside it.

**Do not chase coverage.** §6: empty image criteria are already under 2% in every strong
arm, against the control's 8.5%. Any proposal whose mechanism is "the run will now also
produce X" is aimed at a channel with nothing left in it.

**Do not trim the pack on prompt-budget grounds.** The rendered skills block is
0.19%–0.72% of a stage prompt, and going 120 → 161 adds under a kilobyte. The standing
cost is the always-on Skill-tool descriptions (§6), which is a different object.

**Do not optimise skill read counts.** Reads do not predict score: within `main40`,
r = −0.135 (n=34); the arm with 41 *fewer* skills opened *more* of them. Three PRs of
routing work (#237, #242, #251) were justified by a proxy that has never been shown to
track the outcome.

**Do not select the next round of task-scoped skills on a between-arm gap.** #270 chose
its twelve tasks by where AutoR trailed the control, and those twelve are the tasks the
control is strongest on by 12.3 points and where every subsequent contrast is least
stable. This is the same trap as `docs/rcb-skill-routing-arm.md` §7.2a, one level up.

**Do not run the next arm from `main`.** It is at 173 skills and 420 pins over 47 task
ids — past every configuration that has ever been scored, in the direction the weak
evidence says is unhelpful. Pin a SHA.

---

## 10. What the scoreboard actually says

Against the bare agent, paired and decomposed by criterion type:

| arm | n | total | image | text |
|:---|---:|---:|---:|---:|
| `full40_pins` | 40 | +2.99 | +2.84 | +0.15 |
| `full40_skills` | 40 | +5.54 | +3.95 | +1.58 |
| `full40_main40` | 39 | +7.33 | +5.37 | +1.96 |
| `full40_skills161` | 37 | +7.80 | +5.01 | +2.79 |
| `full40_a9c2b48` | 37 | +7.84 | +4.97 | +2.88 |
| `full40_abl40` | 36 | +8.81 | +5.44 | +3.37 |

AutoR's advantage over bare Claude Code has always been image criteria — they are 60.6%
of the weight and they carry the larger half of every arm's gain. **But the movement
between arms is mostly the text half**: from `pins` to `abl40` the image lead grew +2.60
while the text lead grew +3.22. The arms did not get better at figures; they stopped
leaving text criteria empty.

That is the honest answer to "why is the best arm best": not the skill pack, whose effect
is the size of its own placebo, and not the pins, which barely fire. The arms improved by
covering text criteria they had been leaving empty, and by publishing more of the figures
the judge was already willing to look at.

Related: [The skill-routing arm](rcb-skill-routing-arm.md) ·
[The benchmark landscape](researchclawbench-arms.md)
