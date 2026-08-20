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

*Landed 2026-08-18, with 37 of 40 tasks unscored. Section 7 reports against it item by item.*

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

## 7. The result

**All forty tasks.** This section read 39 for two days, and the fortieth was not
missing for any reason to do with the arm — see §7.8. `Earth_003` scores **27.27**,
close enough to both baselines (26.5 and 26.4) to move nothing. Every figure below
is the forty-task version.

The instrument was checked before anything was compared. All three arms:
`bench_revision bfffc480`, `draws 3`, `judge gpt-5.1`, on every workspace.

### 7.1 Headline (§6.1)

| arm | mean over the 40 |
|---|---:|
| **`full40_pins` (bb32a8c)** | **34.47** |
| `control_bare_cc` | 31.48 |
| `arm_2ffaeb4` | 28.75 |

| paired | difference (1 SE) | 95% CI | wins |
|---|---:|:---|---:|
| vs `arm_2ffaeb4` | **+5.72 ± 1.94** | +1.79 … +9.64 | 27/40 |
| vs `control_bare_cc` | **+2.99 ± 1.54** | −0.12 … +6.11 | 26/40 |

Read the two rows differently, because they say different things.

**Against the arm it replaces, the result holds.** +5.72 clears its standard error
nearly threefold and the 95% interval excludes zero.

**Against the bare agent it wraps, it does not.** +2.99 clears one SE, which is the
bar §6 pre-registered, so the claim is admissible under the stated rule — but the
95% interval includes zero by a hair, and a reader who wants significance should be
told it is absent rather than left to infer it. An earlier draft of this section
said *"the first arm in this sequence that is ahead of the bare agent it wraps."*
The point estimate is; the interval is not. The four arms before it scored 23.07,
28.75, 28.77 and 28.81 against the control's 31.5, so the defensible sentence is
that **this is the first arm that is not clearly behind.**

### 7.2 The pre-specified split (§6.2), and regression to the mean

| group | n | vs `arm_2ffaeb4` | wins |
|---|---:|---:|---:|
| pinned | 15 | **+14.11 ± 2.63** | 14/15 |
| unpinned | 25 | **+0.68 ± 2.13** | 13/25 |

The pinned group's baseline mean is 20.85 against the unpinned group's 33.49 —
they were selected for being bad, exactly as §6.2 warned, so some of that +14 is
regression to the mean and none of it is free. Fitting the effect on the *unpinned*
tasks gives `delta = 13.73 − 0.390 × baseline`; a slope that negative is regression
to the mean, and applied to the pinned group's baselines it predicts **+5.6 with no
pins at all**. Pin excess over that prediction: **+8.50 ± 2.52**.

That was where this section stopped, and it was not far enough.

### 7.2a The same pins against the *control*, and why the two disagree

Run the identical split against `control_bare_cc` instead of against `arm_2ffaeb4`:

| group | n | vs `arm_2ffaeb4` | vs `control_bare_cc` |
|---|---:|---:|---:|
| pinned | 15 | **+14.11 ± 2.63** | **+1.68 ± 2.20** |
| unpinned | 25 | **+0.68 ± 2.13** | **+3.78 ± 2.10** |

**The ordering reverses.** Referenced to the old arm the pinned tasks gain twenty
times what the unpinned ones do; referenced to the bare agent they gain *less than
half*. Both numbers come from the same forty score files.

The levels show why:

| group | `arm_2ffaeb4` | control | `bb32a8c` |
|---|---:|---:|---:|
| pinned (15) | 20.85 | 33.28 | 34.96 |
| unpinned (25) | 33.49 | 30.39 | 34.17 |

The pinned tasks are the ones where the old arm trailed the control by **−12.43 ±
2.72**. The unpinned ones are where it *led* by +3.10 ± 1.36. That is not incidental:
`_rationale` in the pin table records `net = autor − control` per task, and **`net`
is what tasks were selected on.** The table was built by ranking tasks on the gap
between the two arms and pinning the worst of them.

Selecting on a difference selects on the noise in *both* terms. The chosen tasks are
those where `arm_2ffaeb4` came out unusually low **and** the control came out
unusually high, and both regress on a re-run. So:

- **+14.11 vs `arm_2ffaeb4` is biased upward** — the baseline it is measured from was
  selected for being low.
- **+1.68 vs the control is biased downward** — the comparator was selected for being
  high.

The §7.2 regression-to-the-mean correction fixes the first bias and not the second:
it fits on baseline *level*, and the selection was on a *between-arm gap*. §6.2
anticipated selection on level and said so. It did not anticipate this, and the
+8.50 inherits the gap.

**So the pin effect is bracketed, not measured: somewhere in +1.68 … +14.11, from a
design that cannot narrow it.** No reanalysis of these forty tasks will, because the
selection used both arms that any reanalysis would compare against. The hold-out in
§8.2 is not a nice-to-have refinement of this number; it is the only way to obtain
one at all.

What survives unchanged is §7.3 — in all fifteen pinned tasks the criterion the pin
was aimed at moved up. The mechanism does what it claims. Its size is what is open.

### 7.3 Every pin against the criterion it aimed at (§6.3)

**In all fifteen pinned tasks, the criterion that moved most moved up.** The pins
are not raising task totals by some diffuse route; the specific criterion each was
written for is the one that changed:

| task | pinned skill | that criterion |
|---|---|---:|
| Physics_000 | `run-the-conditions-the-source-ran` | 10 → **56** |
| Neuroscience_003 | `run-the-conditions-the-source-ran` | 6 → **51** |
| Astronomy_001 | `the-canonical-figure` | 9 → **49** |
| Information_002 | `the-supplied-item-is-the-graded-unit` | 5 → **42** |
| Math_003 | `run-the-conditions-the-source-ran` | 1 → **38** |
| Chemistry_000 | `the-attribution-is-the-deliverable` | 8 → **37** |
| Material_001 | `material-landmark-scalars-in-physical-units` | 1 → **35** |

### 7.4 The two pins aimed at uncontested zero (§6.4)

One worked and one did not, which is the most a two-case split can say.

`Astronomy_001` — target criterion, weight 0.40, both arms previously 9 and 16:
**→ 49**, task +12.40.

`Neuroscience_000` — of its three criteria that *both* arms scored 0 on, one went
0 → 21 and the other two stayed at 0 and 1. The task still fell 1.67, because it
**lost ground elsewhere**: criterion 0 went 33 → 5. Aiming at an empty cell moved
the empty cell and cost more than it gained. §6.4 called this the best target for
raising a score and the worst for demonstrating anything; on this evidence it is
not reliably even the first.

### 7.5 The falsifiable prediction (§6.5) — met

Skill launches, counted from the `Skill` tool-use records and attributed to the
stage session that made each one:

| stage | 2ffaeb4 | bb32a8c |
|---|---:|---:|
| 01 literature survey | 31 | 104 |
| 02 hypothesis generation | 14 | 71 |
| 03 study design | 25 | 67 |
| 04 implementation | 3 | 6 |
| **05 experimentation** | **0** | **28** |
| 06 analysis | 2 | 82 |
| 07 writing | 3 | 36 |
| **total** | **78** | **394** |
| **stages 05–07** | **5** | **146** |

The routing works as a delivery mechanism. Note what that does *not* buy: launches
rose five-fold across every task, and the unpinned tasks gained 0.68. **Being read
is not the same as being useful.**

### 7.6 Runs that did not finish cleanly (§6.6)

`Chemistry_000`, `Information_003` and `Physics_001` carry
`pipeline_completed: false` or `report_source: synthesized` in their exports. The
arm predates #262, so this had to be read off the export events rather than
`_meta.json`. Excluding them moves the headline by +0.17.

### 7.7 Where the movement actually is

Weight by score band, over the 40 tasks. Every cell is checklist weight pooled
across tasks and divided by the arm's total weight, so the three rows are one
method; the 39-task version of this table differed by at most 1.0 point per cell,
and adding `Earth_003` changes no reading below.

| | 0 absent | 1–20 | 21–40 shallow | 41–50 comparable | 51+ beats paper |
|---|---:|---:|---:|---:|---:|
| `arm_2ffaeb4` | 6.0% | 22.7% | 39.1% | 21.0% | 11.2% |
| **`bb32a8c`** | **2.4%** | **15.8%** | 41.2% | 23.7% | **17.0%** |
| control | 7.9% | 18.8% | 33.1% | 27.2% | 13.1% |

**The gain is absent criteria being filled in, not shallow ones being deepened.**
Weight scoring zero fell by more than half, 1–20 fell by seven points, and what
arrived landed at the top (51+ 11.2% → 17.0%). The shallow band did not shrink; it
grew, and at 41.2% it is now the largest block in the arm.

By criterion type — and image criteria carry 60.6% of the weight:

| | image | text |
|---|---:|---:|
| `arm_2ffaeb4` | 28.9 | 28.5 |
| **`bb32a8c`** | **36.1** | **31.9** |
| control | 32.0 | 31.7 |

Image is where the arm passes the control (+4.1); on text it merely draws level
(+0.2). Weighting each by its share, image contributes **+2.47** of the gap and text
**+0.08** — so of the +2.99 in §7.1, **essentially all of it is an image-criterion
gap**, and the arm has no measurable text advantage over the bare agent at all.

The two groups differ in kind, not just in size. Pinned tasks moved weight into
"comparable to the paper": **3.7% → 23.7%**, a six-fold rise, with absent weight
falling 9.0% → 1.3%. Unpinned tasks moved weight *out* of comparable
(30.8% → 22.1%) and into both shallow (33.0% → 38.8%) and beats-paper
(10.8% → 15.4%). Their mean is flat because those cancel: the non-pin changes made
outcomes **more variable, not better**.

### 7.8 The fortieth task, and how it went missing

`Earth_003` is not a scheduling casualty, which is what §7 said about it for two
days. Its run wrote a **45,132-byte report and eleven figures**, then spent four
attempts at Stage 07 failing one schema check and reached its 40 h wall still
trying. The check was `dispersion_type`, an enum of six tokens compared with `==`,
against values like `range of the Z500 skillful lead time across the complete
cascades` — the right measure, refused for the gloss after it (#312).

The wall kill is where it became invisible. `_meta.json` is written once, after the
result exists, so a run ended by a signal keeps the `running` the harness wrote at
launch, forever. The scoring driver skips any workspace not marked `completed`, so
it skipped this one — and logged only `scoreable workspaces: 39`, naming nothing it
had dropped. A finished deliverable sat on disk while the arm was written up at
n=39.

Three separate things had to be wrong for one task to vanish quietly, and all three
are fixed: the enum now accepts a measure with a gloss (#312), a scheduler kill
writes `status: aborted` instead of leaving `running` (#313), and the driver names
every workspace it excludes and why. That last one is the cheap one, and it is the
one that would have surfaced this immediately:

```
SKIP Earth_003  Earth_003_20260818_205245: status='running', report 45132 B
```

**A count with nothing beside it reads as "that is all there was."** It was not.

---

## 8. Why, and what to do next

### 8.1 The attribution problem, stated plainly

`2ffaeb4..bb32a8c` is **29 commits, 128 files, +22,438 lines**. Three of them are
the routing layers this document is named for. Read only against `arm_2ffaeb4`, the
split in §7.2 is uncomfortable and simple:

- The task-id pin table is worth about **+8.5** above what regression to the mean
  predicts, and §7.3 says it works for the reason claimed.
- Everything else in those 29 commits — including #237 and #242 — is worth
  **+0.68 ± 2.13** together. Statistically nothing.

*A lookup table built from the answer key beat a month of architecture.* That was
this section's conclusion, and §7.2a withdraws the number under it. Against the
control the same pinned tasks gain +1.68 while the same "everything else" gains
+3.78, and the two readings cannot both be taken at face value: the pins were chosen
on `net = autor − control`, so the first is measured from a baseline selected for
being low and the second against a comparator selected for being high.

What can still be said, with the arithmetic behind each clause:

- **The arm is ahead of the arm it replaces**, +5.72 (95% CI +1.79 … +9.64), and
  **not distinguishable from the bare agent**, +2.99 (−0.12 … +6.11).
- **The pins repaired a deficit rather than building a lead.** On the fifteen pinned
  tasks the old arm sat 12.4 points *below* the bare agent; `bb32a8c` sits 1.7 above.
  That is a real repair — those tasks were the worst-scoring in the arm — and it is
  not the same claim as the pins making AutoR better than the agent inside it.
- **The unpinned tasks are where the lead over the control actually sits** (+3.78),
  and §7.7 shows how: not by scoring higher on average but by becoming *more
  variable* — weight moved out of "comparable" into both "shallow" and "beats
  paper" at once. A mean that moves by dispersion is a weaker fact than a mean that
  moves by level, and it is the fact available.
- **Which of the 29 commits deserves the credit remains unattributed.** The design
  isolates the pin layer from everything else and nothing else from anything else.

### 8.2 What is not yet known

**The pins were built from this benchmark's own scorecard.** The +8.32 is an
in-sample number: the criteria were read, the skills matched to them, and the same
tasks re-run. It measures that the mechanism *can* deliver a targeted skill and that
the targeted criterion *does* move — both real and both useful — but it says nothing
about a task nobody has scored yet, which is the only case that matters outside a
leaderboard.

**The honest experiment is a hold-out.** Build the pin table from half the tasks,
measure on the other half. Until that is run, "+3.05 against bare Claude Code"
should be quoted as *in-sample* every time it is quoted.

### 8.3 Where the remaining points are

Lifting every criterion in a band to 45 ("comparable to the paper") is worth, per
arm point:

| band | criteria | weight | worth |
|---|---:|---:|---:|
| 0–20 absent or empty | 29 | 18.1% | **+6.46** |
| 21–40 flawed or shallow | 58 | **41.2%** | **+6.13** |
| 41–50 comparable | 37 | 23.7% | +0.17 |

Two observations follow.

**The shallow band is now the biggest single block of weight, and it grew.** It is
the "methodology is right and the number is wrong" band — a reproduction that lands
an order of magnitude off, a trend that comes out inverted. `close-the-gap-to-the-published-number`
was written for exactly this and the band did not move, so the first question is
whether it fires at all and what it changes when it does. The pins moved criteria
from *absent* to *present*; nothing yet moves them from *present and wrong* to
*right*, and that is a different kind of defect — it needs compute spent chasing a
discrepancy, not a paragraph of advice.

**Fourteen of thirty-nine tasks are still behind the bare agent**, led by
Information_000 (−18.1), Neuroscience_003 (−15.6) and Information_001 (−14.7).
Neuroscience_003 is pinned and gained 15 points and is *still* 15.6 behind, which
means its remaining loss is not the thing the pin was aimed at.

### 8.4 Four things worth doing, in order

1. **Run the hold-out.** Split the pin table, rebuild from half, measure on the
   other half. Nothing else here can be banked until this exists.
2. **Attack the 21–40 band.** 40% of the weight, and it grew under everything tried
   so far. Start by measuring whether `close-the-gap-to-the-published-number` is
   read at Stage 05 and what the run does in the hour after it is.
3. **Find the source of the unpinned dispersion.** Something in the 26 non-pin
   commits both helps and hurts by roughly equal amounts. A change that raises
   variance without raising the mean is worth locating before more are added on
   top of it.
4. **Retire the Neuroscience_000 pin.** It moved its empty cell and lost more
   elsewhere. Aiming at criteria both arms scored zero on is the least defensible
   thing in the table and it now has a measured failure beside its one success.

### 8.5 A note on the pack's size

At `bb32a8c` the pack held 45 skills. It has since grown past 160, with more than
40 task-scoped. The measurement that started all of this was that a run reads
**1.75 skills out of the sixteen it is offered**, and that number rose to roughly
nine here only because prompts began naming them. Descriptions compete; a pack that
grows faster than the naming does returns to the state this document opens with. A
census of launches per skill, run against the next arm, would say whether that has
already happened.

---

## 9. Reproducing it

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
