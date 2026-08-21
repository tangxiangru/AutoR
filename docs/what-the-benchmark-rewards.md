# What the benchmark asks, and what it actually rewards

Ten documents in this directory describe methods and results on ResearchClawBench. None of
them says what the benchmark asks. This one does, and then says what the scorer rewards,
which turns out not to be the same thing.

[Running AutoR on ResearchClawBench](researchclawbench.md) covers how to launch it. This is
about what is being launched at.

---

## 1. A task is a paper with its answers removed

Forty tasks, ten fields — Astronomy, Chemistry, Earth, Energy, Information, Life, Material,
Math, Neuroscience, Physics — four tasks each. Every one is a real published study.

**What the agent gets:** a one-paragraph scientific goal, the study's input data, and some
related work. Median two data files per task; one task supplies sixteen.

**What is withheld:** the paper's results, its figures, and its numbers.

Take `Earth_003`. The goal, verbatim from `task_info.json`:

> Develop a cascade machine learning forecasting system using three specialized
> U-Transformer models to mitigate forecast error accumulation and extend skillful weather
> prediction to 15 days, achieving performance comparable to the ECMWF ensemble mean.

The data is ERA5 reanalysis at 0.25°, shaped `(2, 70, 721, 1440)` — two consecutive
six-hour global atmospheric states across seventy channels. That is the whole brief. The
agent must build the system, run it, and write the paper.

**What it is graded against**, from `target_study/checklist.json`, which it never sees:

| # | type | weight | what it asks for |
|---|---|---:|---|
| 0 | text | 0.20 | Z500 skillful lead time extends 9.25 → 10.5 days, T2M 10 → 14.5; higher ACC on 67.92% of 240 variables |
| 1 | **image** | 0.30 | Figure 1: latitude-weighted ACC and RMSE for 8 variables across 15-day lead times |
| 2 | **image** | 0.20 | Figure 2: normalised ACC/RMSE difference against the ECMWF ensemble mean |
| 3 | **image** | 0.30 | Figure 3: Z500 spatial fields at 1/3/5/7/10 days, three-way comparison |

Across the benchmark: **154 criteria, 91 image and 63 text** — 60.6% of the weight is
images. Median three criteria per task, maximum eight. Three tasks have no image criterion;
nine are entirely image.

---

## 2. How a report becomes a number

One judge call per criterion. Each returns an integer 0–100. The task score is the
weighted mean; the arm score is the mean over tasks.

Three properties of that arrangement matter more than they look.

**The judge never sees the paper.** Its entire notion of the target is the criterion
string — median 435 characters — plus, for an image criterion, one target figure. It is
not comparing your report to the study. It is checking your report against a paragraph
describing what the study found.

**50 is the ceiling of "comparable", not the middle of the scale.** The rubric anchors it
as *"as good as the actual published paper — this is a high bar"*, and the 41–50 band is
"roughly comparable". Everything above 50 is "beats the paper".

**Only the text is clipped, not the figures.** An image criterion is shown the first
10,000 characters of the report. The median report is 45.9 KB, so **92.1% of the 942
reports on disk overflow that window** and the image judge reads about a fifth of the
document. This *sounds* like a lever and is not — see §5.

---

## 3. What the scorer actually rewards

This is the part that is not obvious from the design, and it is measured over 664 scored
runs.

**A 60 is not a better answer than a 10. It is more answers.** Score tracks the
weight-fraction of criteria the report attempted on target. Conditional on attempting one
at all, the score it earns is comparatively flat.

**Being silent costs ten times what being wrong costs.** 81% of near-zero criteria are
scored zero for *absence*; only 2% for being *wrong*. A wrong answer averages about 19
points. A missing one averages about 2. **The judge rarely catches a bad answer — it
catches a missing one**, and 63 of 100 zeros use the literal phrase "does not include".

Three ways to score under 10, in order of how often they happen:

1. **Write a critique of the source work instead of a reproduction of its results.** The
   checklist is an inventory of what the paper produced. An audit of the paper scores
   against none of it.
2. **Refuse to manufacture an intermediate the figure needs.** Declining to fabricate a
   missing input is epistemically correct and scores identically to having done nothing.
3. **Analyse the supplied data on its own terms** rather than rebuilding the source's named
   apparatus. Structuring the report around your own findings instead of the source's
   figures forfeits the criteria, which are indexed to the source's figures.

All three are failures of *aim*, not of competence.

---

## 4. Where the ceiling is

**An oracle that assembled the single best attempt at each of the 154 criteria, taken
across every one of the 664 scored runs, would score 51.70.** Not per task — that is the
union of the best work anyone's pipeline has ever produced on every criterion
simultaneously, and it lands barely past "as good as the paper".

**57 of the 154 criteria — 40.4% of the weight — have never reached 50 in any run.** On
four whole tasks, no criterion ever has.

**The "beats the paper" band is mostly judge noise.** Of 2,559 item-level results, 121
(4.7%) have a mean-of-three at or above 61, but only 21 (0.8%) have all three draws there.

**Weight is anti-correlated with achievability.** No criterion weighing more than 0.40 has
ever scored ≥61, in 102 attempts. The heaviest criteria are the hardest.

For orientation: bare Claude Code scores 31.48, the best complete arm is around 40, and
the oracle above is 51.70.

---

## 5. What this implies for anyone trying to raise the score

**The lever that measures is figure count.** Within task, across 664 runs, the correlation
between figures published and judged score is **+0.509**; against image criteria alone,
**+0.464**. The median run publishes 12 or 13; the judge is handed 15.

**Front-loading the report is not a lever, despite §2.** The obvious reading of the
10,000-character clip is that figures referenced late are lost. Tested: the fraction of a
run's figures referenced inside the window correlates **−0.113** with its image score,
while total figures correlates +0.464. The scorer collects the images from the workspace
and sends them as images; only the accompanying *text* is clipped. A run is not punished
for referencing a figure on page nine — it is punished for not having one. **This is the
kind of plausible mechanism that costs an arm to disprove, and it cost nothing here.**

**Coverage of the zero band is finished; parity is not.** Weight scoring exactly zero has
fallen from the control's 8.5% to under 2% in every strong arm. But 40.4% of weight has
never reached 50 in any run, and 34–43% now sits in the 21–40 "attempted, flawed or
shallow" band. Given §3, that band is not a quality problem so much as a *completeness*
problem: criteria attempted in part.

**The largest single opportunity is not in the pipeline at all.** Run-to-run spread on a
fixed configuration is a per-task standard deviation near 7.4, and 18 of about 20 arms hold
at least one per-task maximum — the best result on a task is scattered essentially at
random across configurations, which is what noise looks like and not what a better pipeline
looks like. Selecting the best of N attempts with a proxy of correlation ρ is worth roughly
ρ·σ·E[max of N]:

| selector | N=2 | N=3 | N=5 |
|:---|---:|---:|---:|
| figure count (measured, r=+0.509) | +2.12 | **+3.22** | +4.39 |
| report size (r=+0.29) | +1.21 | +1.83 | +2.50 |
| oracle (upper bound) | +4.17 | +6.32 | +8.63 |

**Best-of-three is worth more than every pipeline change ever measured on this benchmark
put together** — the figure floor projects +2.4, the 120-vs-161 skill pack +1.8, the
task-id pins zero, and twenty commits of code +0.33.

Two honest caveats. Figure count is partly *causal* rather than merely predictive, so the
`figfloor` arm may capture much of the same effect, and buying it twice is buying it once.
And best-of-N costs N× the compute per task. Neither changes the ranking.

---

## 6. The instrument has its own defects, and some change what a number means

Found by reading `RCB/evaluation/score.py` and re-derived against the score files. These
are properties of the *measuring device*, not of AutoR, and they bound what any number
above can mean.

**The stock scorer starves a reasoning judge.** `score.py:234-235` sends
`temperature=0, max_tokens=500`, and for gpt-5.x that budget must cover the reasoning
*and* the JSON answer. `tools/score_rcb_run.py` exists partly to repair this — its
docstring says so at line 17 — so **every number in this document comes from the repaired
judge**, and any number produced by the stock path does not.

**Images arrive unlabelled and unordered.** They are sent as bare base64: no filenames, no
captions, no ordering guarantee. `IMAGE_EXTENSIONS` is a `set` (`config.py:31`) iterated at
`score.py:92`, so collection order varies between interpreter invocations, and in 270 of
274 runs the order is filesystem order rather than filename order. A criterion that says
"Figure 1" is matched by a judge that cannot see which image is Figure 1.

**The same image set is sent to every image criterion of a task.** A task with four image
criteria shows the judge the identical fifteen images four times. Nothing is selected per
criterion.

**A zero is not stably a zero.** 48 of 1,057 items scored 0 on one draw and non-zero on
another; only 31 zeros were stable across all three. Read §3's absence-versus-wrongness
split with that in mind — the direction holds, the precision does not.

**A judge failure and a missed criterion are the same row.** One clean instance cost 22.2
points on a task whose report was unchanged.

**A run with no report is a hole, not a zero.** `score_workspace` returns an error dict and
writes no file, so 39 of 315 such runs vanish from any aggregation instead of scoring zero.
That is the same silent-drop shape as the stale-status defect, one layer up, and it
inflates every arm that has one.

**`judge_calls` is exactly double the real count** in 272 of 274 score files — a cumulative
counter on a reused judge object, summed across draws. Do not cost a scoring pass from it.

None of these is a reason to distrust the ranking. Several are reasons to distrust a
single task's number, which is the same conclusion §5 reaches from the variance side.

---

Related: [Running AutoR on ResearchClawBench](researchclawbench.md) ·
[What actually moves the score](what-actually-moves-the-score.md) ·
[How to hill-climb this benchmark](how-to-hill-climb-this-benchmark.md)
