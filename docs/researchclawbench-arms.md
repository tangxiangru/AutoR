# The arm register

An arm is one configuration run over all forty ResearchClawBench tasks. A score without its
arm is not a result: the same 40 tasks have been run thirteen times here, at eight
checkouts, under four different per-stage budgets, on three node classes, and the spread
between the best and worst of those configurations is larger than any effect anyone has
tried to measure with them.

This file is the register. It exists because three separate claims in this repository have
had to be withdrawn for reasons that would have been visible in a table like this one: a
delta attributed to skills that spanned 47 commits of unrelated runtime, a pair of arms
compared across an eight-fold difference in stage timeout, and a judge window read off a
three-week-old checkout. None of those were analysis errors. They were bookkeeping errors.

Nothing here is a leaderboard number. `researchclawbench.md` holds the published result and
its caveats; this file holds what was run.

---

## The register

Means are over the tasks that arm actually scored, judged by `gpt-5.1` through
`tools/score_rcb_run.py`. `n` is scored runs, not workspaces — several roots hold retries.

| arm root | checkout | stage timeout | n | mean | median | measured |
|:---|:---|---:|---:|---:|---:|:---|
| `control_bare_cc` | bare Claude Code, no AutoR | n/a | 40 | 29.24 → **31.53** | 30.70 | 08-12 → re-scored 08-16 |
| `full40` | `autor-pinned`, SHA unrecoverable | 1800 s | 40 | **23.57** | 23.70 | 08-13 |
| `arm_2ffaeb4` | **`2ffaeb4`** | adapter default | 40 | **31.35** | 32.75 | 08-15 |
| `full40_pins` | **`bb32a8c`** | adapter default | 37/40 | **34.65** | 36.10 | 08-17, in flight |
| `full40_a9c2b48` | **`a9c2b48`** | adapter default | 0/40 | — | — | 08-18, in flight |
| `full40_skills161` | **`95861bd`** | 1800 s | 0/40 | — | — | 08-18, queued (re-run) |
| `verdict_fix` | partial probe | 1800 s | 12 | 23.88 | 23.85 | 08-11 |
| `full40_13a918d` | partial probe | 1800 s | 1 | 15.00 | — | 08-13 |

The `control_bare_cc` row carries two numbers because the grader's window moved.
ResearchClawBench slices `generated_images[:N]` for every image criterion and raised N from
5 to 15 in `bfffc48` on 2026-08-14. 29 of that arm's 44 runs publish more than five figures,
so the first pass could only ever show the judge a third of them; **31.53 is the number that
is comparable to everything below it.** `full40` needed no re-score — no run in it publishes
more than five images, so both windows hand the judge an identical list.

### Arms that ran and were never scored

Six roots held finished workspaces with no score directory anywhere on disk — roughly 240
runs, 192 of them carrying a report large enough to hand a judge, that had produced no
number. Scoring them costs judge calls and no compute, which made it the cheapest
unanswered question on the cluster. It is running now (`backfill.py`, six arms concurrent,
same `score_rcb_run.py`, same `gpt-5.1`). Partial, at 84 of 192:

| arm root | checkout | n so far | mean | median | max |
|:---|:---|---:|---:|---:|---:|
| `full40_skills` | `9e6aadd` | 14/34 | **40.10** | 42.90 | 53.40 |
| `full40_head` | `f16878b` | 17/40 | 32.02 | 30.10 | 48.10 |
| `control_search_g37` | bare Claude Code + a second search server | 14/37 | 29.76 | 27.95 | 54.04 |
| `full40_v220` | SHA unrecoverable | 16/40 | 28.76 | 25.00 | 51.33 |
| `full40_gpt54` | AutoR driven by GPT-5.4 | 22/40 | **3.04** | 0.00 | 45.30 |
| `full40_skills161` | `95861bd` | 1/1 | 43.00 | — | — |

Two of these are worth saying out loud before the passes finish.

**`full40_skills` is provisionally the best arm on record.** At 14 of 34 tasks it means
40.10 against 34.65 for `bb32a8c` and 31.53 for the bare control. If that survives the
remaining twenty tasks it is a result that sat unscored on disk for a day while two newer
arms were launched to look for three points.

**`full40_gpt54` did not run.** All 40 of its reports are the adapter's 2.2 kB
`Incomplete run.` placeholder with zero images — every stage was auto-skipped. Its mean is a
statement about a broken configuration, not about GPT-5.4's research ability, and it must
never be quoted as the latter. This is also why it was never scored: the arm that would have
placed AutoR against the leaderboard's bare Codex CLI row, at the model that row was
measured at, still has not been run.

`full40_skills161` was likewise not an arm. Eleven of its twelve workspaces hold no report at
all, so the 12-task comparison it was launched for was never possible. It has been
resubmitted as a fresh 40-task arm.

---

## What a task actually costs

Every submission on this cluster before 2026-08-18 sized its request by guessing. Measured
instead, on five concurrent tasks on one node and three sampled individually:

| | measured |
|:---|---:|
| CPU, steady state | **0.8 core** (load average 3.52 across 44 CPUs, five tasks) |
| resident memory, mid-run | 12.5 – 21.8 GB |
| wall clock, median | 18.4 h |

The task is one agent process waiting on an API for most of eighteen hours. **CPU is not what
limits it, and adding cores buys nothing.** Memory is what kills it, and the peak is well
above the resident figure — from the kill record, somewhere between 28 and 48 GB:

| per-task memory | elements run | OOM-killed |
|---:|---:|---:|
| 28 GB | 157 | 8 (5.1%) |
| 31,408 MB (a whole c3small node, shared with the OS) | 55 | 7 (12.7%) |
| 48 GB | 38 | 1 (2.6%) |
| **64 GB** | 39 | **0** |

So the request that has never lost a task is **64 GB and 2–4 CPU**, one task per array
element. Everything else follows from the ratio that implies.

### Sizing a request, or a machine order

```
tasks per node = min( vCPU / 2 , memory_GB / 64 )
```

A task needs **32 GB per vCPU** at a 2-core request. Every node class here is poorer than
that, which is why every arm so far has been memory-bound and has left CPU idle:

| node class | vCPU | memory | GB/vCPU | tasks/node | what goes unused |
|:---|---:|---:|---:|---:|:---|
| c3small | 4 | 31 GB | 7.9 | **0** | cannot hold one task |
| c3 | 44 | 341 GB | 7.8 | 5 | 77% of the cores |
| a3 | 208 | 1,817 GB | 8.7 | 28 | 73% of the cores |
| a memory-optimised node at 28 GB/vCPU | 64 | 1,792 GB | 28 | 28 | 12% of the cores |

The last row is the point: matching the machine to the ratio takes core waste from 77% to
12%, and one such node replaces 5.6 c3 nodes. **Whether cores are wasted is set by the
cores-per-task in the request, not by how large the node is** — a 16-vCPU and a 64-vCPU node
of the same GB/vCPU waste the same fraction.

What node *size* changes is blast radius. A node holding 28 tasks is 70% of an arm; one
holding 7 is 17%. Given that this project has already lost tasks to a single element dying,
the middle of that range is the right trade.

---

## What each pair can and cannot answer

| pair | what it measures | what it does not |
|:---|:---|:---|
| `bb32a8c` vs `2ffaeb4` | 29 PRs together (+22,438 lines) | any single PR, and specifically not the four new skills |
| `a9c2b48` vs `bb32a8c` | 10 PRs together (+31,571 lines) | the 75 skills of #264, even though skill count goes 45 → 120 |
| `bb32a8c` vs `full40` | code **and** an 8× larger stage budget | the code alone |
| anything vs `control_bare_cc` | AutoR against a bare agent at the same model | anything about other harnesses |

The `bb32a8c` vs `full40` row is the one most likely to be quoted and the least safe. 28 of
the 40 `full40` runs logged `Stage timed out`, and those 28 averaged **22.08** against
**27.06** for the 12 that did not — a 4.99-point gap *inside a single arm*, the same size as
every between-arm difference anyone is chasing. Read the +10.9 as an upper bound on what the
code did.

For `a9c2b48` vs `bb32a8c`, a skills-only control would be an `a9c2b48` worktree with the 75
new skill directories and their pin-table entries removed. That arm does not exist, and until
it does, no sentence of the form "the skills were worth N points" is supported.

---

## How much a 40-task mean moves on its own

Two AutoR batches ran two days apart over the same 40 tasks, on 2026-08-11 and 2026-08-13,
both judged `gpt-5.1`. Their 40-task means are **23.04 and 23.57** — a difference of 0.53.
Per task, the same comparison looks nothing like that:

| | |
|:---|---:|
| median per-task absolute difference | **5.78** |
| largest per-task difference | 28.40 |
| tasks differing by more than 5 points | **23 of 40** |
| sd of the paired difference | 10.44 |
| **implied standard error on a 40-task mean** | **±1.65** |

This is an upper bound rather than a clean noise measurement — the two batches are different
runs and may sit at different checkouts, so code change is folded in with run-to-run
variation and judge variation, and it was briefly misread here as a judge re-draw before the
`run_id`s were checked and found to differ on all forty. Read it as: **a single-attempt
40-task mean carries something on the order of ±1.65 (1 SE) before any code changes at all.**
It is consistent with the eight-draw single-task measurement of sd 3.4.

The consequence is the one that matters for every row above. A between-arm difference of 3
points, measured one attempt per task, is inside this. Resolving effects that size needs more
draws per task, not more tasks.

---

## The two submission shapes that lose tasks

The sizing above says how much one task needs. This is about the other half — how tasks are
grouped into Slurm elements — which has cost this project more runs than the sizing has.

| per-element request | tasks per element | elements | OOM-killed |
|:---|---:|---:|---:|
| 31,408 MB (a whole c3small node) | 1 | 99 | 7 (7.1%) |
| **320 GB / 40 CPU** | **5** | 30 | **2 (6.7%)** |
| 64 GB / 5 CPU | 1 | 41 | 0 |

The middle row is the one that is easy to miss, because 320 GB looks generous. It is 64 GB
per task, which is the safe figure — but the five tasks share one cgroup, so **one greedy
task takes the other four down with it.** The `autorhead` arm lost 2 of its 8 elements that
way, which is up to ten tasks from a submission that looked over-provisioned.

The `bb32a8c` arm paid both. Five of its thirty c3small elements were killed
`OUT_OF_MEMORY`. Three of the five had their task rescued by another element through
`run_arm.py`'s atomic-mkdir claim takeover; **two did not, because by then the rest of the
array had exited and no launcher was left to notice.** `Earth_003` and `Life_002` sat in
`running` for eleven and three hours holding the batch open, and were only recovered by hand.

So `a9c2b48` was submitted one task per array element at 64 GB / 5 CPU. That fixes the blast
radius — an OOM kills exactly one task and 39 elements remain to take its claim — and it
schedules far better: a 320 GB element needs a whole free node and only four could start
against that day's cluster, while 64 GB fits wherever 64 GB is free and **twenty-seven
started immediately**, then all forty within two hours. The request also does the node
selection for free, since no 31,408 MB node can ever satisfy it.

Over-reserving is not free either, and it is paid by the next job in the queue. The rescue
submitted for `Earth_003` and `Life_002` first asked for 320 GB per task, on the reasoning
that more is safer. It held two whole nodes for two tasks and starved the forty-element
`a9c2b48` array of 512 GB — eight tasks that could have been running. Resized to 64 GB, the
running count went from 27 to 37. On a shared partition the cost of a generous request lands
on someone, and here it landed on the same experiment.

CPU is *not* held constant across arms and cannot be: `bb32a8c` ran 8 CPUs per task on big
nodes and 4 on small ones, so it has no single value to match. Any per-task wall clock read
across those two arms is confounded. The scores are not — no task in either arm was scored
off a run the OOM killer touched.

---

## Three things this record cannot tell you

**The runs do not know what code they ran.** `_meta.json` carries a `code_version` field and
it is `None` in twelve of the thirteen roots; only `arm_2ffaeb4` populated it, and only on 39
of its 40 runs. Three arms (`full40`, `full40_v220`, `full40_gpt54`) were launched from
`autor-pinned`, a shared clone whose HEAD has since moved to `1069e77`, so their SHAs are not
recoverable from the clone either. What saved the recent arms is that their sbatch echoes
`git rev-parse` into the Slurm log before starting — which is a convention, not a mechanism.
Populating `code_version` at run start would make this file unnecessary to maintain by hand.

**One attempt per task, everywhere.** The public leaderboard aggregates the *best* score per
(task, agent) pair. Every number here is a single draw, so none of them is comparable to a
leaderboard row in either direction.

**Two controls have never been run.** The adaptive-vs-linear ablation is one flag
(`--stage-graph linear`) and would isolate the graph the whole system is named for. The
skills-only worktree would isolate the skill library. Both are cheap next to the thirteen
arms already spent, and both answer a question the register currently cannot.
