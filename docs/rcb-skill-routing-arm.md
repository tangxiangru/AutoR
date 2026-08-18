# The skill-routing arm: what was changed, what it cost, and how it is being measured

A record of one ResearchClawBench arm — `full40_pins`, AutoR pinned at `bb32a8c`,
launched 2026-08-17 07:42 UTC — and of the four changes it exists to measure.

It is written while the arm is still finishing, so the results section states the
analysis **before** the numbers arrive rather than after. That ordering is the
point: this repository's own Stage 02 freezes a decision rule before a result
exists, and an arm's write-up should be held to the standard the pipeline is.

---

## 1. The baseline, corrected

Every number below is produced by one command, and the command matters more than
it looks:

```bash
python3 tools/score_rcb_run.py --workspace <w> --bench <RCB> \
    --judge reference --draws 3 --out <w>/_score_gpt51.json
```

`--judge reference` is `gpt-5.1`, which is what ResearchClawBench scores with;
judge choice has been measured to move a score by roughly sixteen points, so a
number carrying another judge is not a smaller number but an incomparable one.
`--draws 3` is there because one draw on one task carries about ±4 points of judge
sampling noise, which is larger than any difference these arms are separated by.

Scored that way, over all forty tasks:

| arm | mean | median |
|---|---:|---:|
| `control_bare_cc` — bare Claude Code (Opus) | **31.48** | 30.11 |
| `full40_v220` | 28.77 | 29.03 |
| `arm_2ffaeb4` | **28.75** | 27.20 |
| `full40` | 23.07 | 21.60 |

Paired over the forty tasks, `arm_2ffaeb4` against the control is
**−2.73 ± 1.78** (1 SE).

**This supersedes the widely-quoted −0.18.** That figure came from a pass which
scored the two arms differently, and it is the least uniform of the passes
available. The sign is now consistent across three independent scorings, and at
n=40 none of them is significant — so the honest summary is *AutoR is not ahead of
the agent inside it, and is probably a little behind*, not *AutoR ties*.

Two qualifiers that any use of these numbers needs:

- **The arms did not get the same budget.** `arm_2ffaeb4` consumed 788.74 h of
  agent time (the sum of the forty `DONE` durations in its `batch.log`, at
  concurrency 40) against 108.48 h for the control, which was not starved — its
  longest task ran 9.60 h and none hit a timeout. The defensible sentence is
  **"about seven times the agent time and not ahead."**
- One workspace in the archive, `Astronomy_002`, was judged at an older bench
  revision with a five-image window rather than fifteen. It is one of AutoR's
  larger wins, so any table that includes it is quoting one cell measured
  differently from the other seventy-nine.

---

## 2. What the arm measures

`full40_pins` runs AutoR pinned at `bb32a8c`, the first tree carrying all three
routing layers plus the two failures they exposed. At that commit the pack held 45
skills, of which 15 tasks were pinned to 24 skills between them. *(The pack on
`main` has since grown well past that; this arm measures `bb32a8c` and nothing
else.)*

**Why any of it was built.** Measured over the `2ffaeb4` arm — 40 runs, 19.7 h
median each — the skill pack drew **78 `Skill` tool calls in total**, 1.75 distinct
skills per run, and thirteen of the then-34 skills were never opened once.
Attributing each call to the stage that made it:

    01_literature_survey   31 launches in 31 runs
    02_hypothesis_generation 14 in  8
    03_study_design        25 in  7
    04_implementation       3 in  2
    05_experimentation      0 in  0
    06_analysis             2 in  1
    07_writing              3 in  1

Stage 01 is the only stage that reliably reaches for a skill, and it is the only
stage whose prompt named one in the imperative. The stages that produce the results
and write the graded artifact account for five launches across forty runs.

The four changes, in the order they were made:

| | what | why |
|---|---|---|
| #237 | Name each general skill at the stage whose decision it covers | The one imperatively-named skill fired in 31 of 40 runs; the three a prompt said were "installed for this stage" fired in none |
| #242 | `applies_when` — install a skill only for briefs whose shape it addresses | The field filter cannot separate four tasks that share a field |
| #251 | `configs/task_skill_pins.json` — pin skills to a task identifier | For tasks already scored, the criteria they lost are known, and that is not derivable from the task statement |
| #261, #262 | Two defects the arm itself exposed | Below |

---

## 3. The instrument is part of the result

The arm was first scored by a different tool — one draw, no record of the judge or
the bench revision — and the numbers looked usable. They were not comparable to the
baselines above, and the size of the gap is not subtle. On `Astronomy_000`, over
identical artifacts:

| pass | score |
|---|---:|
| one draw, `score_arm.py` | 32.40 |
| three draws, `score_rcb_run.py --judge reference` | **47.40** |

Fifteen points, from the scoring pass alone. The arm is therefore being re-scored
with the baseline's exact command, serially, into `_score_gpt51.json` beside each
workspace, and only those numbers will be quoted.

The rule this is an instance of: **a benchmark comparison is a claim about two
configurations**, and the judge, the draw count, the image window and the bench
revision are all part of the configuration. A result that does not name them is
not reproducible even by the person who produced it.

---

## 4. What broke

Four incidents, three of them defects in this repository, one in how the arm was
scheduled. Each is here because it cost something measurable.

**A degree sign in a CSV ended a run (#261).** `_infer_tabular_schema` read a file
the agent had written as strict UTF-8. The agent had written `0xb0`. The
`UnicodeDecodeError` travelled `_scan_artifacts` → `write_artifact_index` → the
`artifact_index` channel → `_build_stage_prompt` and out of `manager.run`, killing
Life_002 at Stage 03 of 7, nine hours in. Schema inference is a convenience that
describes files nobody reads; it had the power to end a run. Fixed in two layers —
lenient decoding, and a `_infer_schema` that cannot raise.

**An aborted run was recorded as a completed one (#262).** The adapter caught that
exception, synthesised a report from the partial state, and exited zero. So
`_meta.json` said `completed`, the batch runner logged `DONE`, the judge scored the
salvage **22.6**, and that number entered the arm looking like every other. The
evidence — `"pipeline_completed": false` beside `"report_source": "synthesized"` —
was in the run's own output and nothing downstream read it. `BenchmarkResult` now
distinguishes `completed`, `aborted` and `failed`, and an auto-skipped stage is
deliberately still `completed`: the distinction is finishing versus stopping, not
degraded versus perfect.

**31 GB is on the OOM threshold, not clear of it.** A task was OOM-killed on a
4 CPU / 31 GB node, taking the node with it. This had been recorded once before and
the small-node half of the arm was scheduled at that size anyway, on the argument
that one task per node was the best available packing. It cost one task an eleven
hour restart.

**An `srun --overlap` step lives only as long as its host job.** Three tasks were
restarted as extra steps inside allocations this account already held, which starts
them instantly when the cluster is full. Two were then killed when the host
element's own task finished — twice for the same task. The mechanism degrades
safely, because `run_arm.py` re-runs a task whose claim exists but whose work is
neither running nor finished, but the recovery costs a full restart each time. Use
an overlap step to *start* work under contention; do not leave the arm's critical
path in one.

---

## 5. The scheduling, and the confound it introduces

The eight large nodes were held by an older arm, so the forty tasks were placed
across whatever was free. Three resource classes resulted:

| placement | tasks | per task |
|---|---:|---|
| `c3nodeset`, 5 tasks per node | 10 | 8 CPU / 64 GB |
| `c3smallnodeset`, 1 task per node | ~27 | 4 CPU / 31 GB |
| `a3`, whole node per element | 3 | 208 CPU / 1.8 TB |

**Any per-task comparison across these is confounded.** The class is echoed into
each element's Slurm output (`class=`, hostname, CPU count, memory) so the split is
recoverable at analysis time.

One thing this did settle. The crowded nodes ran at load 90–95 on 44 cores while
the single-task nodes sat near zero, and after eleven hours the two groups had
identical progress — 3.30 against 3.40 mean approved stages. **The workload is
bound by model latency, not by CPU.** Redistributing running tasks would have cost
a restart each and bought nothing measurable.

---

## 6. The analysis, written before the numbers

When all forty `_score_gpt51.json` files exist, report:

1. **The paired difference against `control_bare_cc` and against `arm_2ffaeb4`**,
   over the tasks common to both, with a paired standard error. Quote the SE, not a
   p-value: at n=40 with a per-task sd near 11, this design resolves about 5 points,
   and saying so is more useful than a significance verdict.
2. **Pinned against unpinned, as a pre-specified split.** 15 tasks carry a pin and
   25 do not. This is the only comparison in the arm that isolates the pin layer,
   and it is confounded by the pinned tasks having been *selected for being bad*,
   so regression to the mean pushes it positive on its own. Report it with that
   stated, and report the unpinned group as the cleaner read on #237 and #242.
3. **Every pin against the criterion it was aimed at.** `_rationale` in the pin
   table records, per task, which checklist index each pin targets and how many
   weighted points were recoverable there. A pin that moved the task but not its
   target criterion did not work for the reason claimed.
4. **The two pins aimed at uncontested zero** — Neuroscience_000 and Astronomy_001,
   criteria on which *both* arms scored 0. There is no control result to beat there,
   only an empty cell, which makes them the best target for raising a score and the
   worst for demonstrating anything. Report them separately from the rest.
5. **Skill launches per stage**, the same census as §2. This is the change's own
   falsifiable prediction and it does not depend on the score: stages 05–07 should
   move off five launches across forty runs, and the four task-scoped skills should
   appear in the runs their predicates select and in no others.
6. **Anything that did not finish cleanly.** Every workspace whose export says
   `pipeline_completed: false`, listed by name and excluded from the mean rather
   than folded in. The arm was launched from a tree that predates #262, so this has
   to be done by reading the export events rather than by trusting `_meta.json`.

**What will not be claimed.** That the arm's mean is better or worse than a
baseline, unless the paired difference clears its own standard error. Three scoring
passes of the same artifacts have already disagreed by more than the effect being
looked for.

---

## 7. Reproducing it

```bash
# The pinned tree the arm measures
git -C ~/autor-pinned251 rev-parse --short HEAD     # bb32a8c

# What each task-scoped skill selects, over the briefs the installer actually reads
python3 tools/skill_selectivity.py --from-runs /rmeng_data/robtang/rcb_runs/arm_2ffaeb4

# Score one workspace the way every number here was produced
python3 tools/score_rcb_run.py --workspace <w> --bench ~/RCB \
    --judge reference --draws 3 --out <w>/_score_gpt51.json
```

Related: [Running on ResearchClawBench](researchclawbench.md) ·
[The benchmark landscape](researchclawbench-landscape.md) ·
[Development](development.md#agent-skills)
