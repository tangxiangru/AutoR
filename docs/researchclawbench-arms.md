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

## The second measurement fault: the arms shared a memory store

Every arm above ran with Claude Code's auto-memory store open. The store is keyed on an
**ancestor of the working directory**, not on the run root, so every run under
`/rmeng_data/robtang` read and wrote one `MEMORY.md`, loaded into each agent's context at
session start. Probed from that directory against the real binary (2.1.229) on 2026-08-19:

```
no flag:  memory_paths.auto = ~/.claude/projects/-rmeng-data-robtang/memory/
--settings '{"autoMemoryEnabled": false}':  no memory_paths key at all
```

**What hides it is that the transcripts *are* isolated.** Each run gets its own project
directory — `-rmeng-data-robtang-rcb-runs-topo-adaptive-Math-000-...` — and those
directories hold `.jsonl` files and no `memory/`. Per-run isolation looks done from a
directory listing. The memory store resolves separately, and upward.

For the single-arm rows above this is a channel from one run into the next. **For the
paired topology ablation it is a channel between the two things being compared**, because
both arms run the same forty tasks: whichever arm reaches a task first writes notes filed
under that task's name and the other reads them before it starts. Measured while the first
attempt was in flight, the store held 1,531 files / 9.1 MB, took 378 writes on 2026-08-19
alone, and 29 of that day's files are named after a specific task in `tasks40.txt` —
`math-000-score-mixture-disables-track-initialisation.md`,
`energy-001-ships-a-20-bus-two-region-ladder-not-29-nodes.md`, and so on.

The direction matters more than the size. A channel that makes each arm partly a copy of
the other **shrinks the difference the ablation exists to measure**: a real topology effect
would present as absent, and the run would read as a clean null result rather than as a
broken one. That is why the first attempt was cancelled at roughly two hours rather than
footnoted at forty.

Closed for the RCB front end by this change, which passes
`--settings '{"autoMemoryEnabled": false}'` — the mechanism #298 verified for
FrontierScience and did not wire here. Confirmed live rather than by inspection: on a
sampled compute node all three `claude` processes carry the flag and none is without it,
and the shared store took **zero** writes in the period after the relaunch while 27 runs
were active, against 27 in the twelve minutes before it.

The first attempt's 58 workspaces are kept at
`rcb_runs/topo_{adaptive,linear}_v1_shared_memory`. They are evidence, not an arm; nothing
in them should be scored as the ablation.

---

## The arms

Paired against the control. `diff` is AutoR − control in benchmark points; the interval is
95% on the paired mean.

| arm | date | n | mean | **diff (cap 15)** | 95% CI | W–L | diff (cap 5) |
|:---|:---|---:|---:|---:|:---|:---|---:|
| `arm_2ffaeb4` | 08-15 | 38 | 28.65 | **+0.39** | −3.05 … +3.83 | 25–13 | +0.23 |
| `full40_v220` | 08-15 | 38 | 27.33 | **−0.88** | −4.93 … +3.17 | 20–18 | +0.40 |
| `full40_head` | 08-17 | 38 | 27.97 | **−0.70** | −4.32 … +2.91 | 22–16 | **−4.94** |
| `full40_pins` | 08-17 | 36 | 31.91 | **+3.33** | −0.92 … +7.58 | 22–14 | +1.34 † |
| `full40_skills` | 08-17 | 31 | 34.78 | **+6.47** | **+1.95 … +11.00** | 23–8 | — |

The `cap 5` column is computed on the *same* task set as its row's `n`, which it was not
at first: the four cells read +0.72, +0.36, −4.80 and +1.49 while being paired over 40, 40,
39 and 35 tasks, because the `_score.cap5.json` backups exist for runs the cap-15 pass
refuses — `Chemistry_003` on `arm_2ffaeb4` and `Earth_000` on `full40_v220` are still
`running` / `failed`, and the control's `Math_000` is `failed`. A single `n` on a row whose
two columns exclude different runs is exactly the trap `score_arm.py`'s docstring says it
exists to prevent, and it caught the doc rather than the data.
† `full40_pins`'s cap-5 cell is n=34, not 36: `Material_000` and `Physics_002` have no
cap-5 backup at all. No workspace under `full40_skills` has one, hence the em dash.

`full40_pins` (37 of 40 tasks complete) and `full40_skills` (32 of 40) were **still
running** when this was written. Their rows are snapshots, not results. Those arms hold 44
and 45 workspace *directories*, which is what the denominator said here before — relaunch
copies, and for skills five `*_DEAD_launcher_gone` stubs. Counting directories understates
completion and hides that both arms are pairing against the control's 39 scoreable tasks.

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
  that do not carry it, `arm_2ffaeb4` and `full40_pins`, completed 39/40 and 37/40. (Both
  the "two arms" and the 34/40 and 23/40 written here before were wrong: no arm on disk has
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

## Reproducing the table

```bash
# score an arm at the corrected cap; the tool caches on the output name, so a
# name that already has results is never re-scored — use a fresh one to re-measure
python3 ~/rcb_tools/score_arm.py <arm> <out_name>
python3 ~/rcb-watch/table.py          # paired table, skips arms not yet scored
```
