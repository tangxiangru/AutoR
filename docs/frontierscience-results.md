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

Measured rather than argued: eleven doubled control answers, spread across the recorded score range,
cut back to a single copy and re-judged with the same prompt and the same model.

| | |
|:---|---:|
| mean change from de-duplicating | **−0.307 points** |
| sd | 0.606 |
| median | 0.000 |
| negative / zero / positive | 5 / 5 / 1 |

**Duplication flattered the control by about three tenths of a point** on the tasks where it
happened. Applied to the forty-two of forty-three paired tasks whose control answer carried a copy,
the correction to the paired mean difference is **+0.300 in the pipeline's favour**, moving the
published +0.085 to roughly **+0.384**.

At n = 11 the effect is not itself distinguishable from zero — standard error 0.183, and a sign test
over the six non-zero deltas gives p ≈ 0.22. One of the eleven crossed the pass threshold: `fs:014`
went 7.000 → 5.5, so the control's accuracy would fall slightly if every answer were de-duplicated.

### What that means for the numbers on this page

The correction runs **in the pipeline's favour**, which is the opposite of the direction a reader
would guess from a bug in the control arm's plumbing. It does not make the difference resolvable:
+0.384 is still below the 0.654 this sample could detect at 80% power, and its standard error is
0.233. But it is no longer near zero, and it is close to the 0.500 declared as the minimum effect of
interest — so "the pipeline makes no difference" is not a conclusion this trial supports either.

It does change what may be said about the sign. **The confound and the effect are the same size.**
A trial cannot report a difference of +0.085 while carrying an arm-asymmetric artifact worth 0.31,
and no amount of caveat repairs that — the honest statement is that the paired difference is not
quotable in either direction until the writer is fixed and the control arm re-run. The per-subject
result is unaffected in shape, because the duplication is spread across subjects, but every
per-subject difference inherits the same caveat.

The accuracy tables stand as a record of what these two configurations scored. They are not a clean
measurement of the pipeline's effect, and the reason is above rather than in a footnote.

The writer is fixed on this branch, and the control arm has to be re-run before the paired
difference means anything. `tests/test_the_reply_is_captured_once.py` holds the repair, and
reverting it fails three of its eight tests.

---

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

Two notes for whoever runs the next one. The Claude CLI kills a stream after 300 s of silence and
the variable that governs it is `CLAUDE_STREAM_IDLE_TIMEOUT_MS`, not the `BYTE_`-prefixed one that
looks like it should; 1,800,000 is the ceiling it clamps to, and a larger value is silently reduced.
And the report's INTERIM banner fires whenever the pair count is below the planned task count, which
cannot distinguish a trial that has not finished from one that finished with refusals — here it
reads "43 of 60 pairs" over a completed trial.
