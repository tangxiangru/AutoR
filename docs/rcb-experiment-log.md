# Five configurations on ResearchClawBench, and what each one bought

Every full-benchmark run of AutoR on ResearchClawBench, with the number it produced, the
prediction it was launched to test, and — where the prediction was wrong — what was wrong
with the reasoning behind it.

One document rather than a paragraph in each feature's page, because the only question
worth asking of a change here is whether the score moved, and that question is not
answerable from inside the run that made the change. Four of the five entries below
contradict something the change's own PR predicted.

## The measurement, held fixed

Everything here is the same 40 tasks, scored the same way. A number produced under a
different judge or a different image window is not comparable and is not in this table;
see [the judge is part of the result](researchclawbench.md#the-judge-is-part-of-the-result).

| | |
| --- | --- |
| Tasks | all 40, `tasks/*/target_study/checklist.json` |
| Judge | **gpt-5.1** via Azure, key read at call time from `~/api.txt` |
| Image window | **15** (ResearchClawBench raised it from 5 on 2026-08-14) |
| Scale | 0–100 per checklist item, **50 = matches the published paper**, weight-weighted mean |
| Scorer | `~/rcb_tools/score_arm.py`, which refuses to record a judge failure as a zero |
| Comparison | paired per task, `t` on the paired difference |

Single-draw noise on one task is **sd 3.4** over eight redraws of identical artifacts, so
a per-task difference under about 8 points is not readable. Only the paired means are.

## The five

| # | Configuration | 40-task score | Against bare Claude Code |
| --- | --- | ---: | ---: |
| 0 | **Bare Claude Code + Opus 5**, no AutoR | **27.44** | — |
| 1 | AutoR `3ef61e5` — before the reviewer-chain fix | 22.72 | −4.72 |
| 2 | AutoR `1069e77` — skill pack + coverage fixes (#217, #219, #220) | **27.23** | −0.22 |
| 3 | AutoR `f16878b` — bounded reviewer loop (#230–#233) | 24.09 | −3.35 |
| 4 | AutoR `9e6aadd` — 75 task-written skills + pin routing (#264, #257) | **36.08\*** | **+9.50\*** |

\* 32 of 40 tasks. The other eight are re-running; see [what is incomplete](#what-is-incomplete).

Paired, on the 40 tasks all of 0–3 completed:

| Comparison | Δ | t | won |
| --- | ---: | ---: | ---: |
| #2 − #1 | **+4.51** | +3.18 | 28/40 |
| #2 − bare | −0.22 | −0.12 | 20/40 |
| #3 − #2 | **−3.13** | −1.90 | 16/40 |
| #3 − bare | **−3.35** | −2.25 | 18/40 |

Paired, on the 32 tasks #4 has finished:

| Comparison | Δ | t | won |
| --- | ---: | ---: | ---: |
| #4 − #3 | **+12.59** | +5.84 | 30/32 |
| #4 − #2 | **+9.22** | +4.63 | 26/32 |
| #4 − bare | **+9.50** | +4.73 | 27/32 |

## #1 → #2: the parser, the coverage, and a control that should have existed first

`3ef61e5` scored 22.72 with 11 tasks at or near zero. All eleven traced to one defect: the
verdict parser read the wrong JSON object out of a reviewer transcript, so stages were
refused that had passed. Fixing it, plus the coverage work in #217/#219/#220, moved the
score to 27.23 — **+4.51 paired, t = 3.18**, the largest and steadiest gain in this table.

The finding that mattered more was the control. Until it was run there was no answer to
"is the scaffold worth anything", and the answer turned out to be **no**: the best AutoR
had was a dead heat with the bare agent at seven times the wall clock (14.7 h against
2.1 h).

## #2 → #3: cutting the review loop cost three points

`f16878b` bundles four PRs. #230 bounded the automated reviewer's send-backs, measured its
directed rounds instead of exempting them, and gave the router grounds to depart; #231–#233
added a withdrawal ledger, a walk ratchet and invertible writes.

**#230's PR predicted the score would not move.** The argument was that the review loop had
been measured not to pay:

- 1115 reviewer-directed revisions, **71% moved the internal rubric by exactly 0.000**
- the polish ratchet's champion saturates at 0.999, variance 0.031 across 40 tasks, and
  correlates **−0.04** with the benchmark score
- paired, spending more time did not buy more score (r = +0.06…+0.14)

**The score fell 3.13 points**, and against the bare agent 3.35 with t = −2.25. So the
review loop was doing something the internal rubric could not see and the judge could.

The measurements were not wrong; the inference from them was. A nine-criterion mechanical
rubric registering no change is evidence about the rubric, not about the work — which is
the argument several skills in this pack make to the agent, and it was not applied here.

Two other predictions from that PR also failed:

- **"Removing 61% of the directed rounds will cut the median run from 15.4 h to 9–10 h."**
  It did not. The rounds were removed — replay of the 1116 recorded rounds through the
  landed predicates refuses 686 of them — and the median went **up**, to 16.9 h. Rounds per
  stage fell only from 6 to 5: cutting one loop let another expand into it. Work here is
  close to conserved.
- **"#232's walk ratchet is the source of the extra rounds."** Asserted from the shape of
  the change, then measured: it recorded **one excursion across 40 runs**, because it only
  fires on backward moves and the router departs at 6%.

Because four PRs shipped in one configuration, the −3.13 cannot be attributed to any one
of them. That was stated when the run was launched and it is the cost of the decision.

## #3 → #4: writing the skills from the losses, and making them reachable

Two changes, measured together.

### What the losses actually were

The 25 tasks that lost were re-scored **per checklist item for both arms**, so a loss
attaches to a named criterion and its weight rather than to a total. Over 92 items:

| | items | AutoR | bare | items lost | recoverable weight |
| --- | ---: | ---: | ---: | ---: | ---: |
| text | 35 | 28.7 | 35.2 | 69% | 92.1 |
| **image** | **57** | **23.2** | **31.9** | **65%** | **176.3** |

**It was not that AutoR drew too few figures.** On every task whose image criteria lost
badly it published *more* than the control — 12 against 5, 12 against 6, 11 against 8 —
all planned in `report_plan.json`, almost none dropped. It fills the 15-image window with
its own workflow diagnostics (validation statistics, sensitivity panels, component
breakdowns) and omits the figure the field expects. The judge's words, repeatedly: *"none
of them show a spatial map of production cost"*, *"there is no SSP370 hotspot map"*, *"none
of the AI-generated figures include a Janus-style two-faced image"*.

The text half is the same failure in prose: *"describes the framework conceptually but does
not perform any ablation"*, *"directly analyses robustness but does not run explicit
simulations"*, *"mentions grid, road and water as modelled components"*.

### The funnel, which was the real problem

Before this change, per run:

| | #2 `1069e77` | #3 `f16878b` |
| --- | ---: | ---: |
| skills installed | 16 | 16 |
| **skills actually opened** | **median 1**, mean 1.43 | **median 1**, mean 1.57 |
| runs that opened none | **25%** | 12% |
| distinct skills opened across all 40 runs | 17 | 17 |

`citation-discipline` alone took about half of every read, and **27 of the 45 shipped
skills were never opened once in the whole benchmark**. Writing more skills into that
funnel would have changed nothing.

What changes it was already measured and already in the code: a skill a prompt tells the
operator to **read** fired in 31 of 40 runs; skills a prompt said were "installed for this
stage" fired in **0 of 40**. Pins are announced imperatively, so #264 raised the pin cap
from 3 to 15, routed pins to the stages their `SKILL.md` names (announcing fifteen pins in
all seven prompts would be the listing problem the cap existed to avoid), and gave all 120
skills a `stages:` field — 41 had none.

### What it produced

| | #4 `9e6aadd` |
| --- | ---: |
| skills installed | 67 |
| **skills actually opened** | **median 9**, mean 7.88, max 16 |
| runs that opened none | **0%** |
| distinct skills opened across all 40 runs | **76** |

`draw-the-source-figure-panel-for-panel` went from **0 reads in the entire benchmark** to
29. It is the skill the adversarial review named for 14 of the 25 losing tasks as advice
the library already carried and nobody read.

The projection before the run was 7.6 reads per run, from 10 pins at the 78% rate measured
when a prompt names *one* skill. Measured at 7.88 with prompts naming 4.5 — so the rate per
named skill does fall as more are named, and not by much.

**Score: 36.08 on 32 tasks, +9.50 against the bare agent, t = 4.73, winning 27 of 32.** The
first configuration to beat the bare agent rather than draw with it. Four tasks cleared 50,
which is the published paper's own level.

## What is incomplete

Eight of #4's tasks are not in its number, and they are not missing at random — they are the
slowest eight. Five (Astronomy_000, Chemistry_000, Information_000, Information_001,
Information_003) lost their launcher mid-stage with a zero-byte report and are re-running
from scratch; two (Material_000, Math_001) are being finished by a separate job; one
(Math_002) burned two consecutive 30-minute stage timeouts at stage 01 and failed with no
stage approved.

On those same 32 tasks the bare agent scores 26.58 against its 40-task 27.44, so the subset
is mildly harder for the control. Whether it is harder for #4 is unknown until they finish.
**The +9.50 should be read as provisional until the table says 40.**

Two of #4's runs were **salvaged rather than re-run**: their launcher ended after
`report.md` was written but before the status was flipped. Both were checked head and tail
for truncation and marked complete in place, with the reason recorded in their
`_meta.json` under `_salvaged`. No stage was re-executed.

#4 also ran at a different concurrency from the others — 20 tasks to a node rather than 5,
after another session relaunched it. Stage-01 wall time is 8.7 min against 7.2, and the
30-minute stage timeout fires on 4% of stages against 1%. That inflates the failure rate;
it does not change the skill-read counts, which happen in the first minutes of a stage.

## What none of this establishes

The 75 skills were written **from the per-item losses of these 25 tasks**. Every body was
checked against its own task's rubric for proper nouns and measured values — five hits, all
false positives — and the adversarial pass dropped 17 of 69 proposals and rewrote 45 for
handing over an answer rather than a method. So they are not the answer key.

They are still specific to tasks that have been scored. **+9.50 says that writing method
guidance from a task's measured losses and then forcing the agent to read it works. It does
not say AutoR is better on a task nobody has scored yet**, and no run in this table tests
that. The honest generalisation claim is the one the pin table makes about itself: a pin is
derived from a score, so it names identifiers and generalises to nothing outside them.

## Reproducing any row

```bash
# Pin the code. A benchmark run measures the clone it was launched from, not the branch.
git worktree add --detach ~/pin <sha>

# Run the 40. RCB_MAX_CONCURRENT sets tasks per node; 5 fits a 44-core node's memory.
sbatch ~/rcb_tools/slurm_autor_head.sbatch        # edit the arm name inside

# Score with gpt-5.1 at the 15-image window.
python3 ~/rcb_tools/score_arm.py <workspace-root> <results-dir>

# Per checklist item, for diagnosis rather than a leaderboard.
python3 ~/rcb_tools/score_items.py <workspace-root> <results-dir> <task>...

# How many skills each run actually opened.
python3 ~/rcb_tools/skill_reads.py <workspace-root>

# Where the wall clock went.
python3 ~/rcb_tools/timing_breakdown.py <workspace-root>
```

Sizing, measured inside a node carrying five tasks: `cgroup memory.peak` **260 GB**, load
average **1.6–1.9**, summed process CPU **0.1 cores**. Ask for the memory and 4 cores. An
earlier `--cpus-per-task=40` was a node selector for the memory, and on a 656-core
partition it held 36 cores per element that the job never touched.
