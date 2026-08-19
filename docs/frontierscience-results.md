# What AutoR scores on FrontierScience-Research

A sixty-task paired trial, run 2026-08-17 to 2026-08-18. This page is the experiment record:
what was run, what it cost, what it scored, and which of the earlier claims on this branch it
overturns. [frontierscience.md](frontierscience.md) is the other half — how the benchmark is wired
and how to run it.

> **Not comparable to the paper's table.** Every score here was produced by **`gpt-5.1`** at high
> reasoning effort against the paper's verbatim Appendix B prompt, at **one draw per task**. The
> paper grades with GPT-5 and averages thirty draws; that deployment returns 404 on the endpoint
> available here. Judge choice alone has been measured to move a total by about sixteen points on
> the sibling benchmark. A number from this page may not be placed beside the paper's 25.2 / 19.4 /
> 17.5 without this paragraph.

---

## The two arms

Both arms answer the same sixty questions with the same model, the same verbatim task instruction,
and browsing denied. They differ in one thing: whether AutoR is between the question and the answer.

| | `direct-opus` | `58e8491-autor-ideate` |
|:---|:---|:---|
| what it is | one Claude CLI call | AutoR entered at Stage 02 and stopped there, five-lens ideation panel on, answer synthesized from the approved stage |
| model | `claude-opus-5[1m]` | `claude-opus-5[1m]`, reviewing with the same |
| task instruction | identical, frozen in the plan digest | identical |
| browsing | denied, and witnessed at zero | denied on **all seven model seats**, each witnessed |

Plan digest `0b46222767267097`, frozen before the first launch. The treatment arm ran from a
worktree pinned at the commit its label names.

**`--model opus` resolves to `claude-opus-5[1m]` on this box**, so the control arm is bare Claude
Code with Opus 5 and one turn. It is *not* the same instrument as the same model called through the
Anthropic API: on one question the CLI arm wrote 43,075 characters and scored 9.375 where an API
call wrote 5,822 and scored 5.75. Only the CLI arm is the paired control.

---

## Accuracy

The benchmark's own metric: the share of tasks scoring at least 7 of 10 rubric points.

**All sixty tasks, a refused run scored 0.** No selection of any kind — every task counts, and an
arm that produced no answer is scored the way the benchmark would score one.

| arm | overall | physics | chemistry | biology |
|:---|---:|---:|---:|---:|
| Opus 4.5, API *(reference)* | 21.7% ± 5.3 | 10.0% | 30.0% | 25.0% |
| **`direct-opus`** | **51.7% ± 6.5** | **30.0%** | 60.0% | **65.0%** |
| **`58e8491-autor-ideate`** | **50.0% ± 6.5** | **15.0%** | **80.0%** | 55.0% |

**The forty-three complete pairs**, where both arms produced an answer. Same population for both
arms, so like for like — but that population is the subset on which the pipeline converged, which
flatters it by an unknown amount.

| arm | overall | physics | chemistry | biology |
|:---|---:|---:|---:|---:|
| `direct-opus` | 60.5% ± 7.5 | 36.4% | 68.8% | 68.8% |
| `58e8491-autor-ideate` | 67.4% ± 7.1 | 27.3% | **93.8%** | 68.8% |

The two framings disagree about the sign, and that disagreement is the first result: a reader who
is handed one number has been handed a choice somebody else made. A third framing — admitted runs
only, different populations per arm — puts the pipeline further ahead still, at 65.2% against
55.4%, and is the least defensible of the three.

The reference row is a different model on a different substrate and is here for one reason: the
paper reports Claude Opus 4.5 at **17.5%** under a GPT-5 judge, and this harness puts it at 21.7%
under gpt-5.1 — agreement inside one standard error. That anchor is what says the jump to 51.7% is
the model and the substrate rather than a lenient judge.

### The subject interaction is the finding

The overall numbers are nearly identical, 51.7% against 50.0%, and they hide two large effects
pointing in opposite directions.

| subject | accuracy | mean rubric points |
|:---|:---|---:|
| chemistry | 60.0% → **80.0%** | **+0.799** |
| physics | 30.0% → **15.0%** | −0.464 |
| biology | 65.0% → 55.0% | −0.253 |

Over the complete pairs the chemistry effect is larger still: 68.8% → **93.8%**, fifteen of sixteen.
The pipeline roughly halves physics and clearly gains chemistry, and the two nearly cancel in the
total. Reporting only the total would have hidden both.

Per-task, the largest movements in each direction:

| | task | direct → ideate | |
|:---|:---|:---|---:|
| gains | `fs:020` chemistry | 6.000 → 10.000 | +4.000 |
| | `fs:022` chemistry | 6.500 → 10.000 | +3.500 |
| | `fs:034` chemistry, `fs:047` biology, `fs:052` biology | | +2.500 |
| losses | `fs:044` biology | **10.000 → 6.000** | −4.000 |
| | `fs:009` physics | 4.000 → 1.000 | −3.000 |
| | `fs:054` biology | 3.000 → 1.000 | −2.000 |

`fs:044` is the sharpest artifact in the trial: ten rubric items, every one of the form *give the
point if the answer states X*, where X is a named protein — ACLY, PANK2, PANK4, Akt. The control
scored a perfect ten. The pipeline's answer is only 18% shorter, so this is not compression; it
names the graded entities roughly a third as often (ACLY 42 mentions against 11, PANK2 24 against
12, PANK4 26 against 14). What the pipeline spent its length on was not the thing being scored.

---

## What the pipeline costs

Over the runs that produced an answer:

| | `direct-opus` | `58e8491-autor-ideate` | ratio |
|:---|---:|---:|---:|
| wall clock, median | 607 s | 3,916 s | 6.5× |
| wall clock, range | 7 – 1,800 s | 1,797 – 14,816 s | |
| wall clock, whole arm | 13.1 h | **70.0 h** | 5.3× |
| backend calls, median | 1 | 9 | 9× |
| output tokens, median | 44,707 | 288,947 | 6.5× |
| output tokens, whole arm | 3.16 M | **14.08 M** | 4.5× |
| answer length, median | 67,558 chars | 50,399 chars | 0.75× |

**The pipeline spends four and a half times the tokens and five times the wall clock to produce an
answer a quarter shorter, for a paired mean difference of +0.085 ± 0.233 over forty-three pairs.**
It wins seventeen, loses seventeen, ties nine. The median difference is exactly zero.

At forty-three pairs and a difference standard deviation of 1.531, the minimum effect detectable at
80% power is **0.654 points** — above the 0.5 declared as the minimum effect of interest, so this
trial is slightly underpowered for the effect it set out to find. The observed effect is 0.085,
which is well below both. This is not an effect the sample failed to resolve; it is an absence.

---

## Refusals, which are two different things

| arm | refused | rate |
|:---|---:|---:|
| `direct-opus` | 4 / 60 | 6.7% |
| `58e8491-autor-ideate` | **14 / 60** | **23.3%** |

**The control's four refusals were not the benchmark and not AutoR.** All four hit the front end's
thirty-minute answer timeout. Two of them (`fs:008`, `fs:011`) were still writing when it fired, at
363,301 and 310,293 characters, over the length ceiling. The other two (`fs:019`, `fs:026`) were cut
off before a result event was ever written, so the transcript witness came back all-null and the
admission clauses refused them — correctly, because a `browsing_tool_calls == 0` clause must refuse
a run with no evidence rather than admit it as a zero. Those two exited the front end with code 0
and were caught by the trial's gate rather than the run's, which is the second gate doing the job
the first cannot.

This is an artifact of the harness, and it is not neutral: the runs it removed are the ones where
the model wrote longest, and length correlates with score on this rubric. It biases the control
*downward*.

**The pipeline's fourteen refusals are the pipeline.** Thirteen are one shape: Stage 02 was never
approved within its two attempts, so the synthesizer refused to write an answer from zero approved
summaries rather than quietly asking the model the original question again — which would have
produced a plausible document, a `synthesized` source and an exit code of 0. `answer_not_fallback`
and `pipeline_completed` both named each one. **Roughly a quarter of pipeline runs cannot get a
single stage past its own reviewer.** That costs a whole task, not a point, and it is the largest
single lever on this benchmark.

---

## The trial withheld its own headline, and that was right

`max_refusal_rate_for_publication` is 0.20. The pipeline arm refused 23.3%, so the report declines
to publish the paired difference at all, and prints the refusal rates as the trial's result. The
rule was written before there was anything to apply it to; this is the first time it has fired.

The reasoning is in the report and it holds: refusals are not random with respect to arm. A pipeline
arm can be refused for a stage timeout, an auto-skipped stage or a synthesized answer; a single-call
arm structurally cannot be refused for any of the three. The surviving pairs are the tasks the
pipeline found easy.

The numbers above are published here anyway, in three framings side by side, precisely so that no
single one of them can be mistaken for *the* result. The one the evidence supports as a headline is
the all-sixty framing with a refusal scored zero, because it is the only one with no survivorship in
it — and it is also the one least flattering to the pipeline.

---

## A defect in the control arm, found after publication

**Fifty-five of the control arm's sixty answers carry the answer twice. None of the pipeline arm's
do.** Forty are an exact byte-for-byte halving; fifteen more arrived in several streamed blocks so
the copy is not symmetric, and only five are clean. The judge prompt is a fixed template plus the
whole file, so on all but five tasks the control's answer was handed to the judge twice and the
pipeline's once. **Forty-two of the forty-three paired tasks are affected.** None of this was known
when the numbers above were first published.

The cause is in the shared streaming reader, not in the model's output. The Claude CLI's stream
emits the reply as assistant text and then emits a terminal result event whose payload is the same
reply again; the fragment extractor harvests strings under a key set that includes both, so a
consumer that keeps the whole reply gets it twice. Stage-shaped consumers are immune because they
parse a delimited section rather than the raw stream — which is why the pipeline arm is clean, and
why **all forty ResearchClawBench reports on this box are clean too.** The blast radius is the
FrontierScience `direct` path, which by design keeps the reply rather than a file the model was
asked to write.

### What it did to the score

Measured rather than argued: twelve doubled control answers, spread across the recorded score range,
cut back to a single copy and re-judged with the same prompt and the same model. The array is
`~/fs-runs/dedup_recheck.json`, twelve records, each carrying `recorded_doubled`,
`rejudged_single` and their difference.

| | |
|:---|---:|
| mean change from de-duplicating | **+0.033 points** |
| sd | 0.633 |
| median | 0.000 |
| negative / zero / positive | 4 / 5 / 3 |

**Duplication did not move the control's score.** The mean is a thirtieth of a point in the
*opposite* direction to the one a reader would guess, its standard error is 0.183, and seven of the
twelve did not move at all. No re-judged answer crossed the pass threshold in either direction, so
the control's accuracy is unchanged. Whatever the doubling did to the judge, it was not worth a
measurable number of rubric points on this sample.

> **Correction, 2026-08-19.** An earlier revision of this section reported this table as
> **−0.307 points** over **eleven** answers, sd 0.606, census 5/5/1, and concluded that duplication
> had flattered the control by three tenths of a point and that the paired difference should move
> from +0.085 to roughly +0.384. **Every one of those figures was wrong.** They are not in
> `dedup_recheck.json`, they are not in `dedup_recheck.log` — which prints the same twelve deltas
> and its own conclusion, "a mean delta near zero means the duplication did not move the control's
> score" — and they are not recoverable from that array by dropping any record: reaching −0.307 over
> eleven of these twelve would require deleting a value of +3.777, and the largest is +1.150. The
> claim that "`fs:014` went 7.000 → 5.5" was a splice of two different records; `fs:014` is
> `7.000 → 7.000, delta 0.000`, and 5.5 is `fs:034`'s re-judged value, down from 6.000 and nowhere
> near the threshold. The prose was not a rounding of the array. It disagreed with it in n, in sign,
> in sd and in census, and it reached this page, `src/operator.py` and a test docstring before
> anyone compared the two. The structural finding underneath — 40 of 60 control answers carrying a
> copy against 0 of 60 pipeline answers — is unaffected and was verified independently; what was
> fabricated is the price.

### What that means for the numbers on this page

Less than the earlier revision of this section claimed, and in the opposite direction.

The duplication is still **arm-asymmetric and real**: 40 of the control's 60 answers repeat
themselves and none of the pipeline's do, so on most paired tasks the judge was handed the control's
answer twice and the pipeline's once. That is a difference between the arms that has nothing to do
with the pipeline, and it should not exist.

What the re-judging shows is that it **did not buy the control anything measurable**. +0.033 ± 0.183
over twelve tasks does not move the published +0.085, and the honest reading is that the paired
difference stands where it was: near zero, well below the 0.654 this sample could detect at 80%
power, and not resolvable in either direction. The earlier revision used the fabricated 0.31 to
argue that the confound and the effect were the same size; on the actual array they are not, because
the confound's measured effect is indistinguishable from nothing.

The reason to re-run the control arm is therefore not that the duplication is worth points. It is
that an arm-asymmetric artifact should not be in a comparison at all, that the same arm turned out
to carry two more (the capture defect, and the shared memory channel — both below), and that a
measurement whose defects have to be priced after the fact is worth less than one that does not
carry them.

The accuracy tables stand as a record of what these two configurations scored. They are not a clean
measurement of the pipeline's effect, and the reason is above rather than in a footnote.

The writer is fixed on this branch. `tests/test_the_reply_is_captured_once.py` holds the repair, and
reverting it fails three of its eight tests.

---

## The capture defect, verified fixed

Twelve `direct` runs on the repaired reader (`391cc0097251`), same model, same denied tools, same
task instruction:

| | defective reader | repaired |
|:---|---:|---:|
| answers opening with tool output | **6 / 28** | **0 / 12** |
| refused by a content clause | 6 | **0** |

Every first line is now the answer itself. The six that were thrown away were never bad answers —
one ran to 62,491 characters and ended in a complete chemistry conclusion — they were good answers
with a directory listing stapled to the front by the stream reader. See #297.

The shape was also more varied than the first diagnosis said. Re-read across the eleven refusals in
the trial's `direct` arm, only three open with the `ls` output originally described. Six open with
`1\t---`, which is the `cat -n` rendering of a `Read` tool result, and two open with
`{"type":"system","subtype":"init"` — the raw ndjson stream, 313,083 and 337,093 characters, which
failed the length clause rather than the content clause. All the same defect from three directions.

## A channel between runs, which the environment digest did not cover

The `Read` results in those six answers are the more interesting finding, because of *what* was
being read.

Claude Code's auto-memory store is keyed on an **ancestor of the working directory**, not on the
run. Probed against the real binary (2.1.229): a session whose cwd was
`/rmeng_data/robtang/memprobe` and a benchmark stage whose cwd was
`/rmeng_data/robtang/fs-trial-skills/workspaces/fs024_direct-opus_.../.autor/<ts>` both report the
same `memory_paths.auto` — `~/.claude/projects/-rmeng-data-robtang/memory/`. Every run under one
results directory shares one store, and its `MEMORY.md` index is loaded into each agent's context at
session start. Nothing in the harness put it there: the word "memory" appears zero times in the
prompt these runs were given.

The store held 1,456 files, 294 of them written that day, and its two most-read entries were notes
an **earlier run** had written about this harness's own exit clauses:

```
92 reads  fs-ideate-write-answer-md-yourself-to-preempt-synthesis.md
56 reads  an-existing-answer-md-outranks-the-synthesizer.md
11 reads  MEMORY.md
 4 reads  the-reviewer-sees-the-first-16000-characters.md
```

**Cause or consequence is separable, and the answer differs by subject.** The position of the read
in the run's tool sequence says which. In the physics block it lands at call 68–151 of a 66–239 call
run — an agent that worked the problem, got stuck, and went looking. In the chemistry block it is
**tool call 1**, in *both* arms, before the agent has read the problem.

It is also asymmetric, which is what makes it a problem for a paired design rather than a curiosity:
**32 of 37 pipeline runs reached the store against 8 of 37 direct ones.** A channel that both arms
used equally would cancel out of a paired difference. This one does not.

**What did not happen: cross-task answer leakage.** Exactly one file in the 1,456 held solved content
for a specific task — `fs:017`'s Schrödinger-Poisson constants, `eps = -0.692229`, `M_c r_c = 2.6794
hbar^2/Gm^2` — and the only run that read or wrote it was `fs:017`'s own. A run taking notes on
itself is not contamination. The channel was wide open and, on the answer content, it was not used.

The store is closed for this benchmark from #298 onward, and `_meta.json` now records
`auto_memory_isolated`. It is tri-state: `null` on every run above, because they ran with the store
open and no field to say so, and defaulting that to `false` would assert a measurement nobody made.

**None of this is repaired retroactively.** The trials on this page ran with the channel open, in a
paired design that digested a comparability environment which did not include it. Their
per-configuration accuracies stand as a record of what those configurations scored. The paired
*difference* now carries a second arm-asymmetric confound alongside the duplication one, and the
conclusion of the section above — that the difference is not quotable in either direction until the
arms are re-run — is unchanged, with one more reason behind it.

## What the `pipeline_completed` clause discards

The five forced skills changed the *shape* of the pipeline arm's refusals rather than their count.
In the trial before them, thirteen of fourteen refusals were `driver:fallback`: a 236-character
placeholder, because the synthesizer would not write an answer from zero approved stages. With them,
**every refusal is `answer_source: agent` with 35,097–78,794 characters of real answer** and exactly
one clause failing — `pipeline_completed`, because Stage 02 never cleared its reviewer. Zero
fallbacks. That is the first skill working: it says write the graded file first, and the file is
there.

The count is similar; what is being thrown away is not. Scored offline with the same judge, the same
prompt and one draw — **outside the admitted set, and they stay outside it**, because an admission
clause that decides after the score is known is not an admission clause:

| task | chars | score |
|:---|---:|---:|
| fs:004 | 38,632 | 4.00 |
| fs:012 | 60,720 | 3.50 |
| fs:013 | 63,965 | 8.00 |
| fs:014 | 56,996 | 8.00 |
| fs:017 | 60,629 | 8.25 |
| fs:019 | 78,794 | 5.30 |
| **fs:022** | 35,097 | **10.00** |
| fs:023 | 64,954 | 2.50 |
| **mean** | | **6.194** (sd 2.719) |

**Four of the eight clear the pass threshold, and one is a perfect score.** The admitted pipeline
answers average about 5 points; the refused ones average 6.2. The clause is not filtering out weak
work — it is discarding the arm's better answers on a procedural ground, and because it fires on one
arm only, every one of these kills a *pair* and removes the task from the comparison entirely.

This is a finding about the clause, not a correction to the numbers. It is not an argument for
loosening the gate mid-trial, which is the thing this design specifically forbids; it is the
measurement a future plan needs before it decides what `pipeline_completed` should mean for a run
whose answer exists and whose process did not finish.

## Corrections to earlier claims on this branch

**A three-task calibration is not a result, and this trial is the demonstration.** The calibration
landed in an earlier change reporting `fs:010` at 2.500 for the pipeline against 9.375 for the
control, a 6.875-point loss, described as pointing the same way as the sibling benchmark. In the
full trial, the same task under the same configuration:

| `fs:010` | calibration | full trial | swing |
|:---|---:|---:|---:|
| `direct-opus` | 9.375 | 8.875 | −0.500 |
| `58e8491-autor-ideate` | **2.500** | **8.750** | **+6.250** |

The pipeline arm's run-to-run swing on one task is at least 6.25 points — larger than any effect
this trial measured. That single pair was noise, and the conclusion drawn from it was wrong. Two
pairs cannot carry a direction; forty-three say the effect is +0.085.

**The headline metric was wrong too.** This work initially reported mean rubric points and treated
pass-at-seven as a footnote, on the grounds that pass rates would be near zero. That was true of the
water level it was decided at — gpt-5.1 answering its own exam scores 2 to 3 points — and false of
the arms actually run, which pass half the time. Accuracy is the benchmark's own metric and is the
headline here.

---

## What would refute this

The next trial has to be able to. The baseline it must beat or fail against is the all-sixty
framing above: **physics 15.0%, chemistry 80.0%, biology 55.0%, overall 50.0%, fourteen refusals, a
paired mean of +0.085 over 43 pairs.**

Three things would move it and are worth separating:

1. **The refusals.** Thirteen tasks where Stage 02 never passed its reviewer. Recovering them is
   worth up to thirteen tasks of accuracy, far more than any per-answer improvement measured here.
2. **Physics and biology.** The mechanism is under diagnosis; the artifacts are all retained.
3. **The control's own ceiling.** Raising the front end's answer timeout above thirty minutes would
   return the control's four refusals, and they are its longest and probably strongest answers. Any
   future comparison should do this first, or the control is being handicapped.

Two of those three now have a measurement behind them rather than a guess. The refusals are worth
**6.194 points each on average, four of eight above the pass threshold**, so recovering them is the
largest single lever on this page — and the barrier is a procedural clause, not answer quality. And
a re-run has to close the memory channel, which #298 does; a comparison against the baseline above
that leaves it open is measuring two changes at once.

---

## Provenance

| | |
|:---|:---|
| state directory | `/rmeng_data/robtang/fs-trial-full60/` — `plan.json`, `runs/`, `scores/`, `judge-raw/`, `workspaces/`, `report.md` |
| plan digest | `0b46222767267097`, frozen before the first launch |
| dataset | `research_test.jsonl`, sha256 `96c0434a…`, 60 rows, checked on every load |
| task instruction | sha256 `cae42a4c…`, byte-identical in both arms |
| judge | `gpt-5.1`, high effort, 1 draw, serial, paper's Appendix B prompt verbatim |
| API reference arm | `/home/robtang_google_com/fs-probe/opus_baseline/` |
| figure | `/home/robtang_google_com/fs-runs/accuracy.html`, data derived by `chartdata.py` |
| repaired-reader control | `/rmeng_data/robtang/fs-direct-clean/` — 12 `direct` runs on `391cc0097251`, 0 refusals, 0 leaks |
| refused-answer scoring | `/rmeng_data/robtang/fs-refused-scored/` — `summary.json`, `raw/`; produced by `~/fs-runs/score_refused.py`, **outside the admitted set** |
| memory-channel probe | `memory_paths` off the CLI's own `init` event; isolated run at `/rmeng_data/robtang/fs-memprobe-run/` reports `null` |

Two notes for whoever runs the next one. The Claude CLI kills a stream after 300 s of silence and
the variable that governs it is `CLAUDE_STREAM_IDLE_TIMEOUT_MS`, not the `BYTE_`-prefixed one that
looks like it should; 1,800,000 is the ceiling it clamps to, and a larger value is silently reduced.
And the report's INTERIM banner fires whenever the pair count is below the planned task count, which
cannot distinguish a trial that has not finished from one that finished with refusals — here it
reads "43 of 60 pairs" over a completed trial.
