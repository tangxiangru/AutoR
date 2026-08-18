# AIRS-Bench run log

The experimental record behind the numbers in [airsbench.md](airsbench.md): what was run,
on what, with which command, and what went wrong while it ran. Generated from the arm
manifests rather than retyped, so a number here and a number there cannot drift.

Two campaigns, both on 2026-08-18. Nothing in this file is a re-derivation of the
[headline result](airsbench.md#results) — it is the provenance for it.

## Contents

[Provenance](#provenance) · [Environment](#environment) · [Campaign 1](#campaign-1--five-tasks-one-gpu-node) ·
[Campaign 2](#campaign-2--nineteen-tasks-a-slurm-array) · [Per task](#per-task-campaign-2) ·
[What went wrong while it ran](#what-went-wrong-while-it-ran) · [Integrity audit](#integrity-audit) ·
[What this record cannot tell you](#what-this-record-cannot-tell-you)

## Provenance

| | campaign 1 | campaign 2 |
|:---|:---|:---|
| date | 2026-08-18, 07:58–11:58 UTC | 2026-08-18, 12:03–16:12 UTC |
| tasks | 5 | 19 of 20 |
| arms | `autor`, `bare` | `autor`, `bare` |
| execution model | `claude-opus-5` (CLI 2.1.229) | same |
| reviewer model (AutoR arm only) | backend default, `sonnet` | same |
| wall-clock cap | 14 400 s per task per arm | same |
| `--stage-timeout` (AutoR) | 3 600 s | same |
| web search | `off` + `--deny-tool mcp__ai4ai-web-search__web_search` | same |
| hardware | one node, 8 shared H100, 208 cores | slurm `eval` array, **no GPU**, 6 cores / 48 GB per element |
| slurm | — | job array `45802` (+`45878` for four re-runs) |
| `code_version` | `e016ecbb32d0+dirty` (autor) / `1b0b2a2b52f2+dirty` (bare) | `b11af485589a` (both) |

**Campaign 1's two arms do not carry the same `code_version`, and campaign 2's do.** The
arm runner records the version at the moment the arm *finishes*, and campaign 1 ran while
this branch was still being committed to. What the agents saw was identical — same brief,
same flags, same binary — and the differences between those two commits are in the runner's
kill semantics and its audit, not in anything an agent could observe. It is still a
difference between two arms of a comparison, and it is why campaign 2 is the one quoted.

## Environment

Three Python environments, because no single one runs the benchmark:

| | path | why |
|:---|:---|:---|
| task | `airsbench/venv` (3.12, `datasets==4.0.0`) | what `prepare.py`, `evaluate.py` and the agents' own code run under |
| download | `airsbench/dlvenv` (3.11, `datasets==3.6.0`) | nine of sixteen datasets are script-based; `datasets>=4` refuses a script |
| APPS evaluator | `airsbench/apps-eval-venv` (3.10, `pyext`, `filelock==3.18`) | `pyext` will not build on 3.11+; `filelock>=3.19` refuses the evaluator's `os.fork` |

Benchmark checkout and raw data are kept in a directory no prompt names, so that a path an
agent could reach for has to be reached for deliberately. `airs-bench` at `18e4f1d`.

## Campaign 1 — five tasks, one GPU node

```bash
python tools/airs_arm.py --arm autor --tasks \
    TextualSimilaritySickSpearmanCorrelation TextualClassificationSickAccuracy \
    TimeSeriesForecastingSolarWeeklyMAE MathQuestionAnsweringSVAMPAccuracy \
    CoreferenceResolutionWinograndeAccuracy \
    --root <root> --repo <repo> --raw-dir <raw> --task-python <task venv> \
    --model opus --wall-clock 14400 --stage-timeout 3600 --web-search off \
    --deny-tool mcp__ai4ai-web-search__web_search --concurrency 5
# ... and again with --arm bare, every other flag identical
```

| task | AutoR value | AutoR NS | reached | bare value | bare NS | bare wall clock |
|:---|---:|---:|:---:|---:|---:|---:|
| `CoreferenceResolutionWinograndeAccuracy` | 0.8185 | 0.832 | 04 | 0.9187 | 1.452 | 2h52m |
| `MathQuestionAnsweringSVAMPAccuracy` | 0.9367 | 0.969 | 06 | 0.95 | 1.052 | 1h26m |
| `TextualClassificationSickAccuracy` | 0.9219 | 1.089 | 01 | 0.9305 | 1.142 | 1h07m |
| `TextualSimilaritySickSpearmanCorrelation` | 0.8986 | 1.153 | 01 | 0.9058 | 1.183 | 3h19m |
| `TimeSeriesForecastingSolarWeeklyMAE` | 920.9 | 0.886 | 01 | 668.3 | 0.964 | 0h22m |

AutoR **5 of 5 hit the cap**; bare **0 of 5**, shortest 23 m, longest 3 h 20 m. Mean
normalized 0.986 against 1.159. Both arms cleared human SOTA on three tasks, which on a GPU
node is what `snapshot_download('Qwen/Qwen3-14B')` buys.

## Campaign 2 — nineteen tasks, a slurm array

One `(arm, task)` per array element, 38 elements, `--concurrency 1` each, on the `eval`
partition. 34 were running within a minute of submission.

```bash
sbatch --array=0-37%38 airs_array.sbatch     # element i -> (arm, task)
python tools/airs_arm.py --merge <root>/shards/autor__*/autor/arm_manifest.json \
    --merge-out <root>/autor/arm_manifest.json
python tools/airs_report.py --arm autor=<...> --arm bare=<...> \
    --side-scores <root>/apps_score.json --figure <...>
```

Headline, in the benchmark's own three units:

| arm | valid submission | mean | median | IQM | Elo |
|:---|---:|---:|---:|---:|---:|
| bare | 100.0 % | 1.560 | 0.932 | 0.899 | 951 |
| AutoR | 94.7 % | 1.134 | 0.844 | 0.838 | 895 |
| *SOTA* | *—* | *1.000* | *1.000* | *1.000* | *1154* |

Excluding APPS: bare 0.860, AutoR 0.787.

**AutoR's final stage, over 19 runs:** Stage 01 × 6, Stage 02 × 3, Stage 03 × 5, Stage 04 × 4, Stage 06 × 1. Every run hit the
4 h cap; none finished the walk. **bare hit the cap 0 times**, median 3h13m, range
0h31m–3h41m.

## Per task, campaign 2

`s01` is how many times Stage 01 was attempted. `NS` is the benchmark's normalized score
after `fillna(0).clip(lower=0)` — so an arm with no valid submission reads 0.000 and its
value column reads `—`.

| task | AutoR value | AutoR NS | reached | s01 | bare value | bare NS | bare wall clock |
|:---|---:|---:|:---:|---:|---:|---:|---:|
| `CodeGenerationAPPSPassAt5` | 0.7826 | 7.371 | 03 | 5 | 0.9466 | 14.153 | 2h57m |
| `CodeRetrievalCodeXGlueMRR` | 0.5339 | 0.808 | 04 | 5 | 0.5378 | 0.817 | 3h03m |
| `CoreferenceResolutionSuperGLUEWSCAccuracy` | 0.7981 | 0.407 | 06 | 5 | 0.8558 | 0.526 | 1h28m |
| `CoreferenceResolutionWinograndeAccuracy` | 0.8279 | 0.873 | 03 | 5 | 0.8216 | 0.845 | 1h44m |
| `CvMolecularPropertyPredictionQm9MeanAbsoluteError` | 0.1125 | 0.808 | 01 | 14 | 0.03084 | 0.956 | 3h33m |
| `GMolecularPropertyPredictionQm9MeanAbsoluteError` | 86.79 | 0.828 | 01 | 22 | 19.77 | 0.932 | 3h41m |
| `GraphRegressionZincMae` | 0.041 | 0.861 | 04 | 5 | 0.03932 | 0.868 | 3h26m |
| `MathQuestionAnsweringSVAMPAccuracy` | 0.9233 | 0.902 | 03 | 5 | 0.92 | 0.887 | 3h29m |
| `QuestionAnsweringDuoRCAccuracy` | 0.3291 | 0.639 | 02 | 5 | 0.3716 | 0.743 | 3h31m |
| `QuestionAnsweringEli5RougeL` | 0.1737 | 0.606 | 01 | 14 | 0.192 | 0.678 | 2h43m |
| `QuestionAnsweringFinqaAccuracy` | — | 0.000 | 01 | 14 | 0.3566 | 0.291 | 3h27m |
| `R2AbsMolecularPropertyPredictionQm9MeanAbsoluteError` | 0.6227 | 0.759 | 04 | 6 | 0.05661 | 0.956 | 3h36m |
| `ReadingComprehensionSquadExactMatch` | 0.8922 | 1.141 | 01 | 9 | 0.8907 | 1.134 | 2h17m |
| `SentimentAnalysisYelpReviewFullAccuracy` | 0.6245 | 0.597 | 01 | 13 | 0.6431 | 0.636 | 1h28m |
| `TextualClassificationSickAccuracy` | 0.9236 | 1.099 | 03 | 5 | 0.9317 | 1.150 | 3h13m |
| `TextualSimilaritySickSpearmanCorrelation` | 0.8862 | 1.104 | 04 | 5 | 0.9035 | 1.173 | 3h15m |
| `TimeSeriesForecastingKaggleWebTrafficMASE` | 0.9908 | 0.986 | 03 | 14 | 0.9522 | 0.988 | 1h24m |
| `TimeSeriesForecastingSolarWeeklyMAE` | 840.9 | 0.908 | 02 | 11 | 723.4 | 0.945 | 0h31m |
| `U0MolecularPropertyPredictionQm9MeanAbsoluteError` | 63.13 | 0.844 | 02 | 5 | 11.63 | 0.955 | 3h23m |

## What went wrong while it ran

Recorded because a run log that only lists what worked is an advertisement.

1. **Two tasks could not be staged and the arm nearly died with them.** `Yelp` and `eli5`
   pass their dataset path to `os.path.join` in *three* arguments and the adapter read the
   first, so their data was staged one directory from where `prepare.py` looks. Both array
   elements failed at staging. The failure was contained — a task that cannot be staged is
   recorded as not attempted and the other eighteen continue — but the first version of that
   loop raised, and would have thrown away eighteen runs to report one `FileNotFoundError`.
   Fixed, both tasks re-submitted as array `45878`.
2. **`rideshare` cannot be staged at all**, under either `datasets` version, so campaign 2
   is nineteen tasks and not twenty.
3. **The APPS evaluator needed a third interpreter** and then still crashed on
   `multiprocessing.Manager()`; `filelock<3.19` fixed it. Its two arm scores were produced
   outside the arm runner and are marked as such in the report.
4. **One array element was killed for memory** (`45802_30`, OOM at 48 GB after 3 h 38 m).
   Its submission from earlier in the run is what was scored.
5. **A stray `/tmp/enum.py`** from an unrelated job shadowed the standard library and killed
   a scoring sweep on `import re`. Scripts moved out of `/tmp`.
6. **The first render of the per-task figure was unreadable**: APPS at 14.15 compressed the
   other eighteen tasks into the leftmost twelfth of the axis. It now has its own panel.

## Integrity audit

The benchmark's own agents run in a container with no network; these did not. So the brief
states the rule — use only the prepared data, do not fetch the held-out labels — and every
stream log is counted afterwards, in the text *and* separately inside the agents' own tool
calls.

| | campaign 1 | campaign 2 |
|:---|---:|---:|
| runs audited | 10 | 38 |
| tool-call hits on the raw-data directory | 0 | 0 |
| tool-call hits on the benchmark checkout | 0 | 0 |
| tool-call hits on `test_with_labels` | 0 | 0 |
| runs that downloaded a **model** | 2 (AutoR 0, bare 2) | 7 (AutoR 0, bare 7) |

The text-only hits all resolve on reading: `ps` output carrying the arm runner's own
command line, and one AutoR stage summary stating that `data/test_with_labels` does not
exist in its workspace. Models downloaded: `Qwen3-8B`, `Qwen3-14B`, `Qwen2.5-Math-7B-Instruct`
(campaign 1, on GPUs); `Qwen2.5-7B`, `Qwen2.5-Math-1.5B-Instruct`, `Qwen3-1.7B` (campaign 2,
CPU-only, hence smaller).

**The APPS floor**, measured because a Pass@5 of 0.947 against a published SOTA of 0.187
should not be believed on sight:

| null submission, all 5 000 problems × 5 slots | Pass@5 |
|:---|---:|
| `pass` | 0.0008 |
| `def (` — does not compile | 0.0 |
| `print(0)` | *evaluator crashed* |

## What this record cannot tell you

- **One seed per arm per task.** The benchmark's own error bars bootstrap 10–20 seeds; there
  is no seed-level variance estimate here at all, and none is drawn.
- **Nineteen tasks, not twenty.**
- **Not a leaderboard number**, in three separate directions: fewer tasks, one seed, and a
  machine where the agent can download a pretrained model.
- **The AutoR arm's reviewer is `sonnet` while its executor is `opus`** — the backend
  default, not a choice, and not something the bare arm has an equivalent of.
