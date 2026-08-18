# AIRS-Bench

[AIRS-Bench](https://github.com/facebookresearch/airs-bench) ([arXiv:2602.06855](https://arxiv.org/abs/2602.06855))
is the third benchmark AutoR is wired to, and the first one whose score no model produces.
ResearchClawBench judges a report; FrontierScience grades an answer against a rubric.
AIRS-Bench runs `scipy` over a CSV.

Twenty tasks, each a `<problem, dataset, metric>` triplet with a SOTA value taken from a
published paper. The agent is given a prepared dataset and asked for `submission.csv`; the
benchmark's own `evaluate.py` scores it against held-out labels the agent never sees. There
is no judge, no rubric, no prose, and no partial credit — a submission with the wrong number
of rows is refused outright.

That makes it a useful third instrument here for one specific reason. The other two
benchmarks measure AutoR through a model's reading of what AutoR wrote, and a
[judge choice is worth more than most of the effects being discussed](researchclawbench.md).
This one has no reading step at all: the same submission scores the same number every time.
A change that moves this needle moved something real.

## Contents

[What the adapter is](#what-the-adapter-is) · [Quick start](#quick-start) ·
[The output contract](#the-output-contract) · [The normalized score](#the-normalized-score) ·
[Running an arm, and its control](#running-an-arm-and-its-control) ·
[What running it found in the benchmark](#what-running-it-found-in-the-benchmark) ·
[Results](#results) · [What is not measured](#what-is-not-measured)

## What the adapter is

Four files, and one of them is the one that matters.

| File | What it owns |
| --- | --- |
| [src/airsbench.py](../src/airsbench.py) | The adapter core: reading a task specification, composing the brief, exporting and checking the submission, and the benchmark's normalized score |
| [airs_agent.py](../airs_agent.py) | Run AutoR unattended against one task |
| [tools/airs_setup.py](../tools/airs_setup.py) | Stage the raw dataset and build the workspace with the benchmark's own `prepare.py` |
| [tools/score_airs_run.py](../tools/score_airs_run.py) | Score a finished workspace with the benchmark's own `evaluate.py` |
| [tools/airs_arm.py](../tools/airs_arm.py) | Run one arm of a comparison over several tasks, and compare two arms |

**AutoR reimplements none of the benchmark.** `prepare.py`, `evaluate_prepare.py` and
`evaluate.py` are the task's own files and are invoked as subprocesses, unmodified. A
harness that reimplements a scorer is measuring its reimplementation, and the two agree
only until one of them is edited.

## Quick start

AIRS-Bench ships the task specifications and not the data, and it needs two Python
environments — the download and the tasks need different major versions of `datasets`, and
there is no version that does both:

```bash
git clone https://github.com/facebookresearch/airs-bench.git ~/airs-bench

# The task environment: what prepare.py, evaluate.py and the agent's own code run under.
python3.12 -m venv ~/airs-env && ~/airs-env/bin/pip install \
    'datasets==4.0.0' pandas numpy scipy scikit-learn torch transformers

# The download environment. Nine of the sixteen datasets are script-based on the hub and
# datasets>=4 refuses to load a script at all: "Dataset scripts are no longer supported".
python3 -m venv ~/airs-dl && ~/airs-dl/bin/pip install 'datasets==3.6.0'
```

Then stage a task and run it:

```bash
python tools/airs_setup.py --list --repo ~/airs-bench

python tools/airs_setup.py --repo ~/airs-bench --raw-dir /data/airs-raw \
    --task TextualSimilaritySickSpearmanCorrelation \
    --workspace /runs/sick --python ~/airs-env/bin/python \
    --download-python ~/airs-dl/bin/python

python airs_agent.py --repo ~/airs-bench --raw-dir /data/airs-raw \
    --task TextualSimilaritySickSpearmanCorrelation \
    --workspace /runs/sick --task-python ~/airs-env/bin/python --model opus
```

`airs_agent.py` prepares the workspace itself if it has not been staged, so the middle step
is only needed when several workspaces share one download. Scoring runs at the end by
default — it is deterministic and costs seconds — and writes `score.json` into the
workspace. `--no-score` turns it off; `tools/score_airs_run.py` does it separately.

**Where the labels go.** `evaluate_prepare.py` writes the test split *with its labels* into
whatever directory it is handed. The adapter hands it a scratch directory that is deleted
afterwards, never the workspace: a resumed run can still read the workspace, and putting
the answers next to the question would make every later score meaningless.

## The output contract

`<workspace>/submission.csv` is the entire deliverable. The workspace also has `data/`
(read-only, staged by `prepare.py`), `code/` and `outputs/`, and the goal contract tells
every stage to keep them current — but nothing except the submission reaches the score.

Three consequences, all of them stated to the agent in the brief:

1. **A missing or malformed submission scores nothing at all** — not a low score, no
   score. So the brief asks for a valid submission from a simple baseline early, improved
   in place. A sophisticated method still training when the run ends is worth less than a
   mean predictor that finished.
2. **The row count must match the prepared test split**, in its order. `evaluate.py` reads
   the file with `pd.read_csv(path, header=0)` and refuses a count that does not match.
3. **The report, the figures and the prose score zero.** AutoR's stage gates still ask for
   them, and `AUTOR_STAGE_NOTE` — the one paragraph the bare control arm does not get —
   says so explicitly: produce them honestly, and where a stage must choose between a
   better model and a better write-up of the model it already has, choose the model.

**The export never writes a submission.** This is the single most important line in the
adapter, and it is the opposite of what `src/rcb.py` does. That adapter has four report
sources ending in a deterministic fallback, because a partial report scores better than no
report. Here the equivalent move — writing a mean predictor when the run produced nothing —
converts a failed run into a measured one, and a mean predictor is a perfectly respectable
score on several of these tasks. `export_submission` copies and checks; the only file it
can produce is one the run produced. `ExportNeverWritesASubmissionTest` holds that property
across every path through it, including the one where there is no run tree at all.

The walk stops at **Stage 06** by default (`--final-stage`). Stage 07 writes a report the
benchmark never opens and Stage 08 packages it; both are real AutoR stages and both are
wall clock spent on nothing the score can see. `--final-stage 07_writing` runs the writing
stage anyway, which is a legitimate thing to want and is not what is being measured.

## The normalized score

Reproduced from the benchmark's README rather than approximated:

$$
\text{NS}_t^a = \frac{\phi_t(s_t^a) - \phi_t(s_t^{\min})}{\phi_t(s_t^{\text{sota}}) - \phi_t(s_t^{\min})},
\qquad \phi_t(s) = -\log_{10}(|s - s_t^{\text{opt}}|)
$$

`metadata.yaml` carries all three reference points per task — `sota_score`,
`estimated_worst_score` and `optimal_score` — so the transform is exact rather than fitted.
SOTA normalizes to 1.0 and the estimated worst to 0.0, both to twelve places.

Two decisions worth stating:

- **Not clipped to `[0, 1]`.** The published figure explicitly calls out tasks where agents
  routinely pass human SOTA, so clipping would delete the one outcome the benchmark says is
  interesting. A score below the estimated worst is likewise real information about a run.
- **A missing submission is not a zero.** `TaskScore.value` is `None` and
  `valid_submission` is `False`, and both are reported separately from the metric. Several
  of these metrics take 0.0 as a genuine value — accuracy on a task the agent got wrong is
  0.0 — so "no result" and "zero" have to stay different objects the whole way through.
  AIRS-Bench reports *valid submission rate* as its own headline for exactly this reason.

**What the agent is not told.** `metadata.yaml` has the SOTA score;
`project_description.md`, which is what the benchmark hands its own agents, does not.
`build_task_brief` composes the brief out of the description and the workspace contract
only, and the test suite asserts that none of the three reference numbers appears in it —
on the fixture, and on all twenty shipped tasks when `AIRS_BENCH_REPO` names a checkout.
An adapter that handed the agent its own target would produce a number that means nothing
beside the published leaderboard.

## Running an arm, and its control

`tools/airs_arm.py` runs a list of tasks under one arm and writes `arm_manifest.json`.
There are two arms and the point of the file is that they differ in exactly one thing:

| | `--arm autor` | `--arm bare` |
| --- | --- | --- |
| Brief | `build_task_brief(...)` | `build_task_brief(...)`, byte for byte |
| Plus | `AUTOR_STAGE_NOTE`, one paragraph | — |
| Scaffold | the eight-stage walk, reviewer gate, validity chain | one `claude -p` session |
| CLI, model, permission mode, denied tools | same | same |
| Workspace, prepared by the same `prepare.py` | same | same |
| Wall-clock cap, and whether it was hit | same, recorded | same, recorded |

```bash
python tools/airs_arm.py --arm autor --tasks TASK_A TASK_B --root /runs/airs \
    --repo ~/airs-bench --raw-dir /data/airs-raw --task-python ~/airs-env/bin/python \
    --model opus --wall-clock 14400 --concurrency 5
python tools/airs_arm.py --arm bare  --tasks TASK_A TASK_B --root /runs/airs ...   # identical
python tools/airs_arm.py --compare /runs/airs/autor/arm_manifest.json \
                                   /runs/airs/bare/arm_manifest.json
```

`--compare` prints a paired difference and refuses to let it stand alone: if the two
manifests disagree on the model, the CLI, the wall-clock cap, the denied tools, the task
python, the task list or the checkout, it prints **THESE ARMS ARE NOT COMPARABLE** and
names the fields. That check exists because of what happened the last time this repository
published an AutoR-versus-bare margin: the two arms had been given different per-stage
budgets, 28 of 40 AutoR runs hit theirs, and the headline
[−5.67 became unquotable](../README.md#the-re-run-and-the-control-that-matters-more).
It also refuses to be read as significant below six paired tasks, and says so in the output.

**Two environment facts that would otherwise silently break the comparison**, both handled
in one function each so the arms cannot drift:

- `--web-search off` removes only the CLI's *built-in* `WebSearch` and `WebFetch`. AutoR
  does not pass `--strict-mcp-config`, deliberately, so an MCP server configured on the
  machine is still connected and still reaches the internet — the first smoke run of the
  arm runner came back under `off` with `mcp__…__web_search` in its tool list. An arm that
  means no search has to name that server with `--deny-tool`, and the manifest records what
  was denied.
- The Claude CLI kills a stream that has been silent for ~300 s, and for a research agent
  silence is thinking, so the default removes the hard tasks rather than the slow ones.
  `arm_environment` raises `CLAUDE_STREAM_IDLE_TIMEOUT_MS` for both arms.

**The cheating audit.** AIRS-Bench's own agents run in a container with no network, so
"the agent did not fetch the held-out labels" is enforced for them by the environment. Here
it is not: the datasets are public and the labels are one `load_dataset` call away. So the
brief states the rule — use only `<workspace>/data/`, do not download the dataset, do not
go looking for the labels — and every arm's stream log is counted afterwards for the
private paths and the hub download entry points. The counts go in the manifest. It is a
count and not a verdict: `load_dataset` appears in the task's own description and the agent
will quote it back, so a non-zero count means there is a line to go and read.

## What running it found in the benchmark

Three things, all of which change what a score means and none of which is AutoR's:

**1. One task's specification scores zero if you follow it.**
`CoreferenceResolutionWinograndeAccuracy` tells the agent *"it should be of shape
(1531, 1)"* and its `metadata.yaml` says `shape: [1531]`. Its `prepare.py` hands over
`winogrande_xl`'s **validation** split, which has **1,267** rows, and its `evaluate.py`
scores against exactly that — refusing any other count. An agent that believes the
description produces 1,531 rows and scores nothing. The adapter therefore measures the
prepared split (`len(load_from_disk('./data/test'))`, one line inside the workspace the
agent was given) and states both numbers in the brief. Believing the declaration would make
this adapter refuse a correct submission and accept a wrong one, in that order.

**2. Two tasks' `metadata.yaml` disagrees with their own `prepare.py` about where the data
lives.** `Pavithree/eli5` and `Yelp/yelp_review_full` are read without their config
component, so a raw-data directory staged from the `dataset`/`config` pair puts the files
one directory from where the script looks. `raw_relpath_for` reads the path out of the
script instead — the failure mode otherwise is a `FileNotFoundError` at Stage 04 rather
than at setup.

**3. The download instructions do not run as written.** The README's
`./datasets/download_hf_datasets_text.sh` is named `download_hf_datasets.sh` in the tree,
and it pins `datasets==3.6.0` while every task pins `datasets==4.0.0` — necessarily, since
`datasets` 4 removed script-based datasets and nine of the sixteen are script-based. Both
versions read the same saved Arrow directory, so the two-interpreter setup above is the
resolution rather than a workaround.

A fourth, worth knowing rather than fixing: `MathQuestionAnsweringSVAMPAccuracy` ships
`gold_submission.csv` and two permuted copies inside its own task directory. They are not
staged into the workspace, so no agent sees them, but a harness that mounted the task
directory would hand that task away.

## Results

<!-- results:begin -->
_To be filled by the first scored arm._
<!-- results:end -->

## What is not measured

- **This is not a leaderboard number and cannot be placed beside one.** The published table
  is a mean over all twenty tasks at ten or twenty seeds per agent. Anything less is a
  description of the runs it came from. `tools/score_airs_run.py` prints that sentence with
  every score, deliberately.
- **The arms are not containerised.** AIRS-Bench's reference agents run with no network at
  all; these run on a machine that has one, with a stated rule and a post-hoc audit in
  place of an enforced boundary.
- **One seed per arm per task.** The benchmark's own metric is deterministic given a
  submission, but the *agent* is not deterministic, and nothing here estimates that
  variance. Two arms at one seed each is two observations, not an effect.
