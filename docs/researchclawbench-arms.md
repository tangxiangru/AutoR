# The arms we have run, and what each one measured

[`researchclawbench.md`](researchclawbench.md) is how to run the benchmark.
[`researchclawbench-landscape.md`](researchclawbench-landscape.md) is where other agents
land. This is the lab notebook: every full-benchmark arm AutoR has run, what changed
between them, what it scored, and — the part that turned out to matter most — what the
instrument was doing while we read those numbers.

It exists because a four-point deficit was published internally three times before anyone
noticed it was the scorer.

---

## The control

Every number here is a **paired** difference against the same control, task by task:

```
timeout 43200 claude --dangerously-skip-permissions --model opus \
  -p <PROMPT> --output-format stream-json --verbose
```

Bare Claude Code on Opus 5 — the same model AutoR drives, with no scaffold at all. That is
the comparison that decides whether the pipeline earns its complexity. 44 workspaces, 41
completed, first run 2026-08-12, **median 6 figures** per report.

A paired difference cancels task difficulty, which is the dominant source of variance
here; an unpaired mean of two arms on different task subsets says which questions were
easier. Nothing below is unpaired.

---

## The measurement fault, and why it is first

`~/rcb_tools/gpt51_judge.py` held `MAX_IMAGES = 5` after upstream RCB raised the cap to
fifteen (`bfffc48`, 2026-08-14). `image_paths[0]` is the paper's **target** figure, so the
judge was shown **four** workspace images per criterion, and image criteria carry 60.6% of
the benchmark's weight.

**A local scorer that clips lower than upstream is not a stricter measurement. It is a
different one.** What it showed each arm is arithmetic: four slots divided by however many
figures that arm drew, and AutoR's figure count has climbed steadily.

| arm | median figures | shown at cap 5 |
|:---|---:|---:|
| control | 6 | 67% |
| `full40` | 5 | 80% |
| `full40_v220`, `full40_head` | 10 | 40% |
| `arm_2ffaeb4` | 11 | 36% |
| `full40_pins` | 13.5 | 30% |
| `full40_skills` | 14 | 29% |

That column is 4/median, not 5/median — it said 5 here for two days, and 5 is one slot the
judge never had. `full40` was never at 100%: at the median 5 figures it still lost one.
The medians are over workspaces holding at least one figure. Walking each picked workspace
and counting which of its figures actually land in the four slots gives nearly the same
answer — mean per-workspace 63%, 81%, 43%/41%, 37%, 32%, 32% — with one caveat the ratio
hides: `_find_generated_images` sweeps `outputs/` before `report/`, and one control
workspace, `Information_001_20260813_014949`, has two images there that displace report
figures. Every other workspace across all seven arms has an empty `outputs/`.

What that cost in points does *not* follow the figure count, and the note here asserted
that it did. Re-scoring the identical workspaces at both caps — no re-runs, same judge,
same tasks — moved `full40_head` by **+3.7** and the control by −0.6. It also moved
`full40_v220` by **−2.2** and `arm_2ffaeb4` by −0.8: v220 has the same median 10 figures as
head and moved 5.8 points the other way. Re-scoring one arm twice at a fixed cap already
moves its mean by about 1.0 (`cap15_pins` against `cap15_pins_preview`, same workspaces),
so only head's shift is clearly larger than a re-draw. The cap was wrong and every earlier
number is void; *which* arm it penalised is not something this data settles.

Corrected on 2026-08-18; the `cap15` column below is the one to read. The fix is still off
by one in the same direction — `MAX_IMAGES = 15` truncates a list that already carries the
target — so the corrected judge sees fourteen workspace images where upstream sees fifteen.

**Every score this harness produced before that date was measured through a four-image
keyhole.** Arms remain comparable to each other; none is comparable to an upstream number.

---

## The arms

Paired against the control. `diff` is AutoR − control in benchmark points; the interval is
95% on the paired mean.

| arm | date | n | mean | **diff (cap 15)** | 95% CI | W–L | diff (cap 5) |
|:---|:---|---:|---:|---:|:---|:---|---:|
| `arm_2ffaeb4` | 08-15 | 38 | 28.65 | **+0.39** | −3.05 … +3.83 | 25–13 | +0.23 |
| `full40_v220` | 08-15 | 38 | 27.33 | **−0.88** | −4.93 … +3.17 | 20–18 | +0.40 |
| `full40_head` | 08-17 | 38 | 27.97 | **−0.70** | −4.32 … +2.91 | 22–16 | **−4.94** |
| `full40_pins` | 08-17 | **40** | **34.47** | **+2.99** | −0.12 … +6.11 | 26–14 | +1.34 † |
| `full40_skills` | 08-20 | **39** | **36.89** | **+5.29** | **+2.12 … +8.46** | 30–9 | — |
| `full40_main40` | 08-20 | 35 | 37.23 | **+6.00** | **+1.65 … +10.35** | 27–8 | — |
| `full40_skills161` | 08-20 | 35 | 38.71 | **+7.82** | **+5.02 … +10.63** | 29–6 | — |
| `full40_abl40` | 08-20 | 35 | **40.17** | **+9.23** | **+6.13 … +12.34** | 27–8 | — |

The bottom four rows landed on 2026-08-20 and **every one of their intervals excludes zero**.
`full40_skills`'s row previously read n=31 / 34.78 / +6.47 as a snapshot; it is now complete
at 39 of 40 and the point estimate fell to +5.29 as the slower tasks arrived, which is the
direction a snapshot's selection bias predicts. The three arms below it had never appeared in
this document at all: nothing was scoring them, and they would have finished and been thrown
away. See [Four arms nobody was scoring](#four-arms-nobody-was-scoring).

The `cap 5` column is computed on the *same* task set as its row's `n`, which it was not
at first: the four cells read +0.72, +0.36, −4.80 and +1.49 while being paired over 40, 40,
39 and 35 tasks, because the `_score.cap5.json` backups exist for runs the cap-15 pass
refuses — `Chemistry_003` on `arm_2ffaeb4` and `Earth_000` on `full40_v220` are still
`running` / `failed`, and the control's `Math_000` is `failed`. A single `n` on a row whose
two columns exclude different runs is exactly the trap `score_arm.py`'s docstring says it
exists to prevent, and it caught the doc rather than the data.
† `full40_pins`'s cap-5 cell is n=34, not 36: `Material_000` and `Physics_002` have no
cap-5 backup at all. No workspace under `full40_skills` has one, hence the em dash.

**`full40_pins` is now complete at 40 of 40** and its row above is a result, not a
snapshot. Its cap-15 cell moved from the n=36 snapshot (+3.33) to +2.99 over all forty —
the point estimate barely moved and the interval now sits astride zero, so the arm is
**not** distinguishable from the control at 95%. The fortieth task took two extra days to
appear for reasons that had nothing to do with the arm: `Earth_003` finished a 45 KB report,
then failed a schema check four times at Stage 07 and was killed at its wall, and because a
killed run never writes a terminal status the scoring driver skipped it while logging only a
count. See §7.8 of [the routing arm write-up](rcb-skill-routing-arm.md).

`full40_skills` (32 of 40) was **still running** when this was written and its row remains a
snapshot. That arm holds 45 workspace *directories*, which is what the denominator said here
before — relaunch copies, plus five `*_DEAD_launcher_gone` stubs. Counting directories
understates completion and hides that the arm is pairing against a smaller scoreable set.

As of 2026-08-19 `full40_pins` is at **39 of 40**; only `Earth_003` is still running, on its
third launch, and the row above has not been re-scored to include the three tasks that
landed since. It is still a snapshot. What the finished 39 look like under a *second,
independent* instrument is [its own section below](#three-instruments-over-the-same-39-workspaces),
and the answer is that the instrument is worth more points than the arm is: on the pass the
baselines were built with, the arm separates from `arm_2ffaeb4` and still does not separate
from the control.

**`full40_skills` is the first arm whose interval excludes zero.** Before reading it as a
result, two checks that were run:

- *Selection.* The 8 unscored tasks score 28.39 on the control against 28.31 for the 31
  scored ones — a 0.08 gap, so they are not the *control's* hard tasks. That is the wrong
  axis, and reading it as reassurance was the mistake. Those 8 are missing because **this
  arm** has not finished them: 7 are still `running` (5 of those after a launcher death and
  a relaunch on 08-18) and `Math_002` is `failed`. The paired set is therefore selected on
  the arm's own success, and no balance check on the control side can see that. `failed`
  does not score 0 — `score_arm.py` maps it to `None` and drops the task, so the arm's own
  failures leave the mean rather than dragging it down. (`Math_002` wrote a 21.7 KB report;
  "no substantive report" is the scorer's label for `status: failed`, not a reading of the
  file.) Sensitivity: if the 8 land at parity with the control the arm reads +5.15
  (+1.47 … +8.83); if they land as arm-zeros it reads −0.68 (−6.75 … +5.39). The sign is
  not yet robust. Two of the 8 (`Astronomy_000` 50, `Information_000` 47) are tasks the
  control does *well* on.
- *Sisters.* No other arm reproduces it yet, and the three complete arms sit at ±1 (+0.39,
  −0.88, −0.70). The nearest sister, `full40_pins`, is at +3.33 — and is itself a snapshot,
  which is the same reason skills is one.

---

## What was chased and refuted

Kept because a refuted hypothesis is cheaper to read than to re-run.

- **"AutoR loses by 5 points."** From `full40` and then `full40_head`, both read in
  isolation. Three sister arms did not reproduce it. *A result one arm shows and its
  siblings do not is a property of that arm.* This check is cheap and was skipped twice.
- **"The arms ran on different hardware."** Both `slurm_control.sbatch` and
  `slurm_autor_head.sbatch` are `--partition=eval`; the H100 split is incidental placement
  in a heterogeneous partition. The natural experiment had already run: `arm_2ffaeb4` *had*
  an H100 on Chemistry_001 and still scored 0 and 2 on two of that task's five criteria
  where the control scored 45 and 48 — with a GPU in hand it still chose frozen-checkpoint
  inference. The binding constraint is the decision not to train, not the hardware. Read as
  a task result this is not a rout in the other direction either: at the corrected cap
  `arm_2ffaeb4` *wins* Chemistry_001, 19.05 to 18.45. It is evidence about two criteria.
  (0 and 3 against 36 and 45 was the same pair of criteria at the superseded cap 5.)
- **`--stage-timeout 1800`.** Four arms carry it — `full40`, `full40_v220`, `full40_head`,
  `full40_skills` — and they completed 40/40, 39/40, 40/40 and 32/40 tasks; the two arms
  that do not carry it, `arm_2ffaeb4` and `full40_pins`, completed 39/40 and 37/40 —
  `full40_pins` has since reached 39/40, which strengthens the bullet rather than changing
  it. (Both the "two arms" and the 34/40 and 23/40 written here before were wrong: no arm
  on disk has
  either completion count, and the two figures came from two different metrics.) Not the
  driver, and the flag's spread across the arms makes that a stronger statement than the
  version it replaces, not a weaker one.
- **"AutoR's absence rate is worse."** Zero-scored criteria, arm against control. True of
  `full40` (24% vs 15%, both at cap 5 — `full40` was never re-scored). False for the two
  arms that were: `full40_head` is 14% vs 15% and `full40_pins` 11% vs 16%, on shared tasks
  at cap 5. The 17% this line paired with `full40_pins` was the control's *cap-15* rate
  against the arm's cap-5 rate, which is two caps in one comparison. Per-criterion scores
  at the corrected cap live only in the workspace `_score.json`, which a re-score
  overwrites — the latest draw reads head 16% vs 17% and pins 7% vs 18% — so the cap-5
  backups are the pair that can be quoted and re-derived. The conclusion holds at both.
- **Three prompt/skill proposals** aimed at the losing criteria — a published-quantity
  reconciliation table, a Stage 02 source-condition checklist, one-figure-per-claim — all
  restated guidance already shipped in the pack. One was checked against its own sister
  arm: `arm_2ffaeb4` writes more hypothesis-verdict figure titles than `full40_head` — 61
  to 45, counting matplotlib title strings containing "supported" or "refuted" once per
  distinct source file (60 to 45 as distinct strings). The 68 to 43 printed here does not
  reproduce under any variant I could find; the direction does, under all of them. What
  does not survive is the score half of the sentence: 5.84 higher was a cap-5 figure, and
  at the corrected cap the paired gap between those two arms is **+1.54** (n=38,
  −2.10 … +5.18). That is inside the noise floor this document states two sections down, so
  the pair refutes nothing either way.

---

## The ceiling on all of it

The four non-`skills` rows are 150 paired comparisons, not the 148 written here before —
148 is what the pins row gives if it is taken from `cap15_pins` (n=34) rather than the
`cap15_pins_preview` the row is actually built from. Treating those 150 diffs as
independent gives a standard error of 0.98, but they are not independent: each control task
appears once per arm. Clustered by task the standard error is 1.54.

Pooled over the three arms that are **complete**, it is 114 pairs with a mean of −0.40 and
a 95% interval of −2.52 … +1.73 (−3.45 … +2.65 clustered). AutoR and bare Claude Code are
indistinguishable. **The pooled instrument does not resolve anything smaller than about 3
points, and a single arm resolves nothing smaller than 3.4–4.5** — the per-arm standard
errors are 1.75 (`arm_2ffaeb4`), 2.07 (`full40_v220`), 1.84 (`full40_head`), 2.17
(`full40_pins`), 2.31 (`full40_skills`). Every row in the table above except `full40_skills`
is inside its own noise floor, `full40_pins`'s +3.33 included. The ±2 this section used to
claim was the precision of the pooled mean being read as though it were the precision of a
row.

The pooling is also doing work that should be said out loud. The arms are not
interchangeable draws of one thing: `full40_pins` beats `full40_head` by +3.54
(n=36, +0.18 … +6.89) and `full40_v220` by +3.96 (n=36, +0.28 … +7.64) on paired tasks,
both intervals excluding zero. So the null is an average over configurations that differ
from each other by more than the instrument's resolution, and the two largest positive
diffs — `full40_pins` +3.33 and `full40_skills` +6.47 — are the two most recent arms.

That is the number to weigh before the next prompt change: more tasks, or more scoring
draws per task, buys more than another edit does. Per-task judge noise is separately about
8.5 points, so a single task's delta means nothing at all — and that one does not need an
outside citation, because this directory holds the experiment. `cap15_pins` and
`cap15_pins_preview` are two independent scorings of the same 35 workspaces: the paired
differences have sd 6.17 and a maximum of 21.2 points (`Astronomy_000`, 54.8 against 33.6),
which puts a single draw's sd at 4.36 and its 95% band at 8.5. The same arithmetic is where
the ~1.0 re-draw noise on an arm mean comes from.

## Three instruments over the same 39 workspaces

The section above measures how much a *re-draw* of one scorer moves an arm. This one
measures two things the document had not: how much the **number of draws** moves it, and
how much the **choice of scoring program** moves it. Both move it further than any arm in
the table above moves, and the first one changes a verdict.

### The draw count decides whether the arm separates from the previous head

`tools/score_rcb_run.py --judge reference --draws 3` writes `_score_gpt51.json` beside each
workspace, averaging three judge draws per criterion. That is the instrument the baseline
arms were scored with, and `/rmeng_data/robtang/rescore_pins/run.sh` exists specifically to
say so: *"one draw carries about ±4 points of judge sampling noise per task … a comparison
across the two is not a smaller number, it is an incomparable one."*

Both sets exist on disk for all four arms. They give different answers:

| paired, `full40_pins` against | n | **3 draws** | 1 SE | t | **1 draw** | 1 SE | t |
|:---|---:|---:|---:|---:|---:|---:|---:|
| `arm_2ffaeb4` | 39 | **+5.84** | 1.99 | **2.94** | +3.23 | 2.05 | 1.58 |
| `full40` (pre-repair) | 39 | +11.57 | 1.75 | 6.59 | +11.00 | 1.98 | 5.57 |
| control, bare Claude Code | 39 | +3.05 | 1.58 | 1.93 | +2.97 | 1.76 | 1.69 |

**Read on its own instrument the arm separates from the previous head and does not separate
from the control.** On one draw it separates from neither. The verdict on the row that the
whole arm exists to settle depends on the draw count, and the draw count is not visible in
a score file's name.

Arm means, three draws: `full40_pins` **34.65** (n=39), `arm_2ffaeb4` **28.75**,
`full40` **23.07**, control **31.48**.

**Almost all of the movement is in the baseline, not the arm.** Over the same 39 tasks
`full40_pins` reads 34.55 at one draw and 34.65 at three — a tenth of a point — while
`arm_2ffaeb4` reads 31.32 and 28.81, two and a half points apart. An arm re-scored at a
different draw count is not the number that moved; its comparator is. Checking the draw
count of *both* sides is the cheap step that was skipped, and it is cheap: a multi-draw
result carries a **`draws`** field, a single-draw one has no such key at all. Failing that,
`judge_calls ÷ len(items)` reads **1.0** on the one-draw sets and **6.0** on the three-draw
ones — six, not three, because the pass makes two calls per criterion per draw. Neither the
filename nor the directory name carries it, which is how two instruments ended up in one
comparison.

The three-draw files also record what a single draw was hiding. `total_spread` is the range
of the three draws' totals for one task:

| arm | tasks | median spread | mean | worst task |
|:---|---:|---:|---:|:---|
| `full40_pins` | 39 | 7.55 | 8.01 | `Math_003` **30.5** — 44.5, 14.0, 23.25 |
| `arm_2ffaeb4` | 40 | 5.48 | 6.32 | `Information_000` 20.5 — 32.0, 31.0, 51.5 |
| control | 40 | 4.60 | 7.37 | `Physics_000` 26.3 — 34.9, 55.9, 61.2 |

Seven of 39 pins tasks, seven of 40 `arm_2ffaeb4` tasks and nine of 40 control tasks have
three draws spanning more than ten points on unchanged artifacts. The ~8.5-point single-draw
band this document quotes is not an outside citation any more — it is measurable from these
files, and the worst cases are three to four times it.

### The program matters too, and by about as much

`full40_pins` has also been scored by two different programs, over the same workspaces:
the 39 `run_id`s match one by one with zero mismatches, and no `report.md` or figure under
any of the 39 was written after the earlier of the two scorings, so both programs were
handed the same artifacts. (Scores read 2026-08-19 08:45 UTC; `cap15_pins` is still being
appended to by another session, so re-derive before quoting.)

| | pipeline | judge | scores in |
|:--|:--|:--|:--|
| **A** | `tools/score_rcb_run.py`, driven by `pins-watch/watch_pins.py` | `gpt-5.1` | `/rmeng_data/robtang/pins-watch/scores` |
| **B** | `~/rcb_tools/score_arm.py` + `gpt51_judge.py` | `gpt-5.1` | `~/rcb_results/cap15_pins`, `…_preview` |

Both are nominally at the corrected fifteen-image window. They do not agree.

| comparison | n | paired mean | 1 SE | t | sd | A/first wins |
|:---|---:|---:|---:|---:|---:|---:|
| **B against B′** — same pipeline, two draws | 37 | +0.54 | 0.99 | 0.55 | 6.04 | 16–21 |
| **A against B** — different pipelines | 39 | **+2.37** | 0.72 | **3.29** | 4.49 | 26–13 |
| **A against B′** — different pipelines | 37 | **+2.75** | 0.93 | **2.95** | 5.67 | 26–11 |

**The within-pipeline difference is unsigned and consistent with zero. The cross-pipeline
difference is signed, three standard errors from zero, and reproduces against both of the
other pipeline's independent draws.** That is not judge noise. It is an offset carried by
the scorer, and at +2.4 to +2.8 points it is the size of every arm effect in the table
above: `full40_pins`'s own +3.33, `arm_2ffaeb4`'s +0.39, `full40_head`'s −0.70.

Arm means over the same 39 tasks: **A 34.55, B 32.19, B′ 31.90**, and the superseded cap-5
pass `gpt51_pins` **28.94**. The disagreement is not concentrated in one task — the four
largest gaps are `Chemistry_000` +10.4, `Material_003` +9.0, `Astronomy_002` +8.8 and
`Astronomy_000` −8.3, and it changes sign. What does survive is the *ordering*: 88.4% of
the 741 task pairs rank the same way under both pipelines. The pipelines agree about which
tasks are hard and disagree about what the arm is worth.

**Consequence for everything above.** The table in [The arms](#the-arms) is built entirely
from pipeline B, so its rows remain comparable to each other. A number from pipeline A may
not be dropped into it — which is the same failure this document opens with, one layer
further out: the first time it was one scorer clipping images, this time it is two scorers
that both look correct, and a third difference — the draw count — hiding inside one of them.

### What the arm is worth

On its own instrument (three draws, `_score_gpt51.json`, the pass the baselines were built
with), over the 39 tasks finished so far:

| against | paired mean | 1 SE | t | W–L |
|:---|---:|---:|---:|:---|
| `arm_2ffaeb4` | **+5.84** | 1.99 | 2.94 | 26–13 |
| `full40` (pre-repair) | +11.57 | 1.75 | 6.59 | 34–5 |
| control, bare Claude Code | +3.05 | 1.58 | 1.93 | 25–14 |

**`full40_pins` is the second arm whose interval excludes zero, and the first to do it
against the previous head rather than against the control.** It still does not separate from
bare Claude Code: +3.05 at 1.93 SE is the same inconclusive three points every recent arm
has produced, and the pooled instrument does not resolve it. So the honest reading is
*better than the AutoR it replaced, still not distinguishable from no scaffold at all.*

Three cautions on the +5.84 before it is quoted:

- The arm is at 39/40. The missing task is `Earth_003`, which has now failed to complete on
  three launches, so it is missing for a reason that correlates with difficulty. The paired
  set is selected on this arm's own success — the same trap recorded above for
  `full40_skills`, and no balance check on the comparator side can see it.
- +11.57 against the pre-repair arm is the `--stage-timeout 1800` confound this file
  already documents. Upper bound, not measurement.
- One draw of the same comparison reads +3.23 and does not clear its own noise. The
  three-draw number is the better instrument, not a second opinion to be averaged with the
  first.

Two blemishes found while checking, neither load-bearing:

- One task of the 40 in `arm_2ffaeb4` — `Astronomy_002` — was scored against benchmark
  revision `595f318`, before the five-to-fifteen image change; the other 39 are on
  `bfffc48`. Dropping it moves the comparison from +3.23 to **+3.64 ± 2.06**, still inside
  the floor. A `bench_revision` field mixed inside one arm is worth checking for by default;
  nothing warns about it.
- Eleven of the 39 pins runs publish 14 images and ten publish 15, so about half the arm
  sits at or above the window. The off-by-one in `gpt51_judge.py` noted above — fifteen
  minus the target leaves fourteen workspace images — therefore bites on roughly half of
  pipeline B's runs and none of pipeline A's, which is one mechanism available to explain
  the sign of the offset. It is a hypothesis, not a measurement: it was not tested by
  re-scoring at a matched count.

`full40_pins` was still one task short when this was written. `Earth_003` is on its third
launch and had reached `04_implementation` at 11 h 48 m.

## Four arms nobody was scoring

`full40_skills`, `full40_main40`, `full40_abl40` and `full40_skills161` ran to completion
with **no scorer attached to any of them**. `pins`, `a9c`, the topology pair and the two
FIRE-Bench trials each had a watcher; these four had none, and `full40_skills` alone was
sitting on 36 finished tasks and zero scores on the instrument its baselines were measured
with. They would have finished and been discarded.

They are scored now, by `score-unscored/score_unscored.py`, at three draws — the same pass
as the control, for the reason the section above gives.

**The scaffold is ahead of the bare agent it wraps.** Four arms, four intervals excluding
zero, on the same judge and the same forty tasks. The sentence this document and
`framework.md` §6.8 have carried for two weeks — that the scaffold is worth less than no
scaffold — does not survive them and should be retired rather than hedged.

### The pin ablation, which is the one that stings

`full40_abl40` is `full40_main40` with 40 task-scoped skill directories deleted and their
pins struck. Same commit, same flags, same forty tasks; the skills are the only difference.
Paired over the 33 tasks both arms finished:

| | mean on the 33 shared | paired difference | 95% CI | W–L |
|:---|---:|---:|:---|---:|
| `main40` − `abl40` | 37.38 vs 40.53 | **−3.16 ± 1.48** | **−6.06 … −0.25** | 10–23 |

**The pinned skills are worth negative three points, and the interval excludes zero.** The
arm in front of every other arm in this file is the one with them removed.

Three things that make the effect *larger* than −3.16 rather than smaller, all of which
argue against reading this as noise:

- **The manipulation is not uniform.** The struck pins fall on a minority of the forty
  tasks and the rest lose nothing, so a 40-task mean dilutes whatever happened on the
  tasks that actually changed. −3.16 is the diluted number.
- **Both arms are ahead of the control.** +6.00 and +9.23. This is not a scaffold-versus-
  nothing result, it is a within-scaffold result, and the two arms share every other
  source of variance the pairing does not already cancel.
- **The loss count carries it, not one collapse.** 23 of 33 tasks, not a handful of
  outliers dragging a mean.

What it does not license:

- **It is 33 pairs.** That resolves about 3 points at 80% power and the effect is about
  that size, so the sign is better supported than the magnitude.
- **Each arm is 35 of 40**, so each is selected on its own completions, and the two arms
  are missing *different* tasks — `main40` lacks `Information_003` and `Physics_000`,
  `abl40` lacks `Astronomy_001` and `Energy_000`. The 33-task intersection is what the
  pairing is over; neither arm's own 35-task mean is comparable to the other's.
- **It does not say which skills.** Forty directories were struck together. Attributing
  the −3.16 to any one of them needs an arm that strikes one of them.

## Reproducing the table

```bash
# Pipeline B, which every row in "The arms" is built from.
# score an arm at the corrected cap; the tool caches on the output name, so a
# name that already has results is never re-scored — use a fresh one to re-measure
python3 ~/rcb_tools/score_arm.py <arm> <out_name>
python3 ~/rcb-watch/table.py          # paired table, skips arms not yet scored
```

Pipeline A is a different program and its numbers do not belong in that table — see
[Three instruments over the same 39 workspaces](#three-instruments-over-the-same-39-workspaces). It
scores one workspace at a time and is driven by a watcher that waits for a task to be
recorded finished, because `collect_figures` trims `report/images/` to the referenced set
only at export:

```bash
python3 <AutoR>/tools/score_rcb_run.py \
  --workspace /rmeng_data/robtang/rcb_runs/<arm>/<Task>_<ts> \
  --bench ~/RCB --out <dir>/<Task>.json
```

Its output carries `total_weight`, `judge_model`, `judge_failures` and `bench_revision`;
pipeline B's does not. That is the quickest way to tell which program produced a score file
you have found on disk.
