# FIRE-Bench

[FIRE-Bench](https://github.com/maitrix-org/FIRE-Bench) evaluates agents on the
**rediscovery of scientific insights**: it turns published empirical-analysis papers
into tasks where an agent is given a research question and a set of resources, has to
design and run its own experiments, and is scored on the conclusion it writes at the
end — by atomic claim, against the conclusion the paper's authors wrote.

It is AutoR's third benchmark, and the third different shape.

| | deliverable | scored against | must run experiments? | wall clock |
| --- | --- | --- | --- | --- |
| [ResearchClawBench](researchclawbench.md) | `report/report.md` + figures | a weighted checklist, images ≈61% of it | yes | none imposed |
| [FrontierScience](frontierscience.md) | one written answer | a rubric summing to 10 points | no | none imposed |
| **FIRE-Bench** | one written **conclusion** | one reference conclusion, claim-level P/R/F1 | yes | **3600 s, enforced** |

The pieces mirror the other two: `src/firebench.py` (task reader, workspace, goal
contract, conclusion export, log publisher, metadata — pure), `fire_agent.py`
(`--profile direct|pipeline`), `tools/fire_trial.py` (the arm matrix),
`tools/score_fire_run.py` + `tools/fire_eval_driver.py` (the benchmark's own scorer,
driven repeatedly), and `templates/firebench_agent_run.py` (the file you drop into a
FIRE-Bench checkout to register AutoR as an agent).

---

## What this benchmark punishes that the others reward

Four things were measured off the checkout, and each one inverts a habit that is
correct on ResearchClawBench.

**1. The scored text is short, and longer is strictly worse.** The 35 reference
conclusions are one to three sentences — 117 to 372 characters, median 255. Precision is
*the fraction of the agent's own atomic claims that the reference supports*, so a true,
well-evidenced, interesting finding that the reference does not happen to mention still
costs precision. On ResearchClawBench an uncovered result scores zero and coverage beats
polish. Here an uncovered claim costs recall once, and a superfluous claim costs
precision permanently. AutoR's writing stage produces 35 kB reports; without the goal
contract saying this in the prompt, the pipeline loses on length before it loses on
anything else.

**2. Numbers are deleted before scoring.** The evaluator pipes the extracted text
through a summariser instructed to omit "all concrete values, specific numbers,
background details, methods, file names, or references to artifacts". So *accuracy fell
from 0.82 to 0.31* is scored as *accuracy fell*. The experiments are what make the
direction true — they are just not what is read.

**3. The harness kills the agent at one hour.** `FIRE-Bench/run_agent.py` runs each
agent under `subprocess.run(..., timeout=3600)`. A measured ResearchClawBench run of the
same pipeline took 27,005 s. This is the single biggest constraint on the design, and it
is why `fire_agent.py` is deadline-driven rather than stage-count-driven.

**4. The scored artifact is the last line of a log file, and two other patterns
outrank it.** The evaluator's extractor tries an OpenHands `final_thought='…', outputs=`
match anywhere in the file, then — if three or more `[YYYY-MM-DDTHH:MM:SS]` stamps are
present — the text *between the third-last and the last of them*, and only then the last
line as `{"result": …}`. An AutoR trajectory is JSON events with ISO timestamps in them.
Copied through verbatim, a run is scored on a slice of its own progress log, and the
symptom is a plausible paragraph with a plausible score. `sanitise_log_body` breaks both
patterns with a zero-width space; the tests assert against a transcription of the
evaluator's own three readers, with a negative control that shows the unsanitised text
*does* get stolen.

---

## Quick start

```bash
git clone https://github.com/maitrix-org/FIRE-Bench ~/FIRE-Bench

# one task, the pipeline arm, under the harness's own clock
python3 fire_agent.py --bench-root ~/FIRE-Bench --task cot_in_planning \
    --profile pipeline --model opus --review-model opus

# read the contract the agent will be given, without creating anything
python3 fire_agent.py --bench-root ~/FIRE-Bench --task cot_in_planning --print-goal

# score it, three times, because the judge is noisy (see below)
python3 tools/score_fire_run.py --bench-root ~/FIRE-Bench \
    --log-file ~/FIRE-Bench/log/autor/opus/cot_in_planning/<stamp>/log.log \
    --task cot_in_planning --draws 3
```

To run it through the benchmark's own harness instead:

```bash
mkdir -p ~/FIRE-Bench/agents/autor
cp templates/firebench_agent_run.py ~/FIRE-Bench/agents/autor/run.py
cd ~/FIRE-Bench && bash run_experiment.sh --agents autor --tasks cot_in_planning --models opus
```

---

## The two arms

**`--profile direct`** — one operator call. The backend CLI with its tools, given the
goal, left to work. This is not "one API call": it can write code, run it and iterate,
which is what FIRE-Bench's own `agents/claude` baseline is and therefore what a paired
difference has to be measured against. Same model, same denied tools, same sandbox, same
goal text, same deadline.

**`--profile pipeline`** — the stage walk, Stage 02 through Stage 05, then one synthesis
call. Everything the direct arm has, plus hypothesis generation, study design,
implementation, experimentation, and a reviewer between each of them.

Pipeline minus direct is the pipeline's effect and nothing else. `tools/fire_trial.py`
adds a third arm, `claude-stock` — the benchmark's own agent given the raw
`instruction.txt` — because direct minus stock is the *goal contract's* effect, and
without it a pipeline that beats the published baseline could be a pipeline that worked
or a prompt that told the model how the grader works.

### Why the walk stops at Stage 05

Two independent reasons, either sufficient. Stage 06 is the first stage whose gate
demands figures, and `resolve_min_report_figures` clamps the floor to at least one, so
there is no configuration in which an image-free benchmark clears it — and FIRE-Bench
scores no images at all. And the deadline: four stages in 3600 s is already tight. The
analysis Stage 06 would have done is one synthesis call here, which costs a call instead
of a stage, a reviewer and a figure.

### Why the walk starts at Stage 02, and browsing is off by default

Every FIRE-Bench task is the rediscovery of a published finding whose paper is on the
open web with its conclusion in the abstract. Stage 01 is a literature survey. A run that
does a literature survey on this benchmark is running a search for the answer key, and
the number it produces is not a measurement of research ability. `--web-search off` is
the default for the same reason, and `_meta.json` records the denial per seat so the
claim is checkable rather than asserted. Note the limit of that claim: the denied-tool
list covers `WebSearch` and `WebFetch`, and `curl` lives inside `Bash`, so "did not
browse" is something the transcript witness can testify to afterwards, not something the
flag guarantees.

---

## The deadline

`Deadline` owns the total. Per-stage timeouts are slices of *what is left* divided by
*how many stages have not yet written a summary*, with a floor of 240 s — below that a
stage is not fast, it is a timeout with a cost. A reserve (default 480 s) is held back
that only the synthesis-and-publish step may spend.

Three things make a killed run still scoreable:

- **The goal tells the agent the clock.** "Write the conclusion as soon as you have a
  defensible answer, and rewrite it when you learn something that changes it."
- **A watcher thread republishes.** Every 20 s it checks `conclusion.md`, and if it has
  improved and passes the same refusals the exporter applies, it appends a new
  `{"result": …}` line. The evaluator reads the *last* line, so a later conclusion wins
  by being later — and there is never a window in which the file has no result line,
  which is exactly when a SIGKILL would land.
- **A deadline hit ends the walk rather than the process.** The walk runs in a daemon
  thread; when the reserve boundary is reached the run stops waiting for it, reaps its
  own backend descendants (by pid, out of `/proc` — never a pattern kill, because
  another session's multi-hour benchmark is usually running on the same box), and
  proceeds to synthesis with whatever stages were approved.

---

## What is published, and what is refused

`export_conclusion` looks in one order — **agent** (the agent's own `conclusion.md`, or
the direct arm's reply) → **synthesized** (one call over approved stage work) →
**fallback**. There is no `stage` source, unlike the other two adapters: a stage summary
promoted verbatim is a document with headings, and against a precision metric computed
over the agent's own atomic claims that is a document full of claims nobody asked for.

The synthesizer refuses when nothing was approved. Without that guard, a pipeline arm
whose walk collapsed calls a model with the task statement and an empty memory file, gets
a competent single-shot answer back, and publishes it as the pipeline's result — so the
paired difference measures one model against itself and reports the variance as the
pipeline's effect.

**A fallback is never published to the log.** A run that produced no conclusion has to be
*unscoreable* — the evaluator's extractor returns `None` and the run is visibly skipped —
rather than scored on a placeholder, which is a zero that reads like a measurement.

Refusals are namespaced strings written into `_meta.json`: `length:below_floor:…`,
`content:conclusion_is_a_plan:…`, `driver:no_approved_stage`. The content check is
deliberately *not* FrontierScience's: that one refuses any text carrying a stage heading,
`Key Results` among them, which on a three-sentence prose conclusion refuses good
answers. What is refused here is a plan, a transcript, and a placeholder.

## The exit code

Six clauses over the same dictionary that is written to `_meta.json`, so any holder of
the artifact can recompute the verdict without rerunning anything:

| clause | what it refuses |
| --- | --- |
| `conclusion_present` | no conclusion at all |
| `conclusion_not_fallback` | this adapter's own placeholder |
| `conclusion_within_bounds` | outside 80–1500 characters |
| `conclusion_published_to_log` | a conclusion that never reached the file the evaluator reads |
| `no_content_refusal` | a plan, a transcript, or placeholder text |
| `procedure_completed` | a walk that did not finish |

The shape is copied from FrontierScience's, and the reason is the measurement behind it:
over forty real ResearchClawBench runs, 39 wrote `status: "completed"` and the fortieth
wrote no result line at all, while 31 had auto-skipped a stage and 8 had auto-skipped
*the stage being scored* — none of which appeared in the metadata.

---

## Scoring

FIRE-Bench's evaluator is `eval/RAGChecker/eval.py`, built on RAGChecker and RefChecker.
AutoR does not reimplement it; `tools/fire_eval_driver.py` calls it and
`tools/score_fire_run.py` drives that repeatedly.

**The judge is very noisy.** Measured on this deployment: the *same log*, the same
configuration, scored three times, returned F1 of 57.1, 92.3 and 100.0 — a 43-point range
with nothing changing but sampling. The unstable part is the decomposition: the same
paragraph comes back as three atomic claims one time and six the next, and the
denominator moves with it. The benchmark's own published baselines carry per-task
standard deviations of 23–25 F1 on top of that.

So: **a single draw on a single task is not a measurement.** `score_fire_run.py` prints
the median and the range together and refuses to print a mean of one, and
`fire_trial.py`'s report gives paired per-task differences rather than a difference of
means.

**A draw that produced no number is not a zero.** `no_conclusion`, `unknown_task`,
`judge_failed` and `error` draws are counted, named, and excluded from the statistics.
Only `overall_metrics` (precision, recall, F1) is meaningful: `eval.py` requests all
eleven metrics while hardcoding `retrieved_context: []`, so the eight retriever and
generator metrics are empty-input fallbacks that read like measurements.

### Making the shipped scorer run at all

Two things, neither of them optional, both outside this repository:

1. A virtualenv with `ragchecker`, `refchecker`, `openai` and `python-dotenv`
   (RefChecker pins `torch>=2,<3`, so this is a few gigabytes and does not belong in the
   interpreter AutoR runs under). `score_fire_run.py` defaults to
   `~/.venvs/firebench/bin/python`.
2. An extractor/checker model the deployment actually serves. The shipped default is
   `openai/gpt-4.1`; on a deployment without it, litellm raises `BadRequestError`,
   RefChecker classifies that as retryable, and the run sleeps ten seconds and retries
   **forever** — no traceback, no exit, a progress bar frozen at 0%. The wrong value here
   does not fail, it hangs. `gpt-5` is also not a valid value: RefChecker hardcodes
   `temperature=0` and `1e-5`, gpt-5 rejects both, and the same handler swallows that
   into the same infinite retry.

---

## Known holes in the benchmark's own harness

Found while wiring this up, and worth knowing whichever agent you run. None of them is
AutoR's to fix, but `templates/firebench_agent_run.py` and this adapter route around all
of them.

- **`agents/claude/run.py` crashes on 20 of the 35 verified tasks.** It calls
  `shutil.copytree(benchmark/papers/<task>/data, sandbox)` unconditionally and 20 tasks
  ship no `data/` directory. It raises above the line that creates the log directory, so
  those tasks produce no log at all — while `run_agent.py`, which never checks a return
  code, prints that the task "completed in 0.0 minutes". The other three shipped agents
  already guard this.
- **The sandbox is inside the checkout.** Every shipped agent puts it in
  `<checkout>/runs/`, and runs with `--dangerously-skip-permissions`. From there,
  `../../benchmark/papers/<task_id>/conclusion.txt` — the answer this run is scored
  against — is two directories away and readable. This adapter's sandbox defaults to
  `$FIREBENCH_RUNS_DIR` (`~/fire-bench-runs`), outside the checkout.
- **`extract_single_final_thought` can raise `UnboundLocalError`** rather than returning
  `None`, because `extracted` is bound inside the `try` and returned outside it.
- **A failed Claude CLI run emits `{"type": "result", …}` with no `result` key**, so
  "the agent failed" and "the agent never ran" are indistinguishable downstream.
- **`utils/llm_inference.py` imports `transformers` at module scope** (46 s cold on the
  box this was built on) even though most tasks never touch a local model, always sends
  `max_tokens` (which reasoning-era deployments reject outright), has no `base_url`, has
  no Vertex path, and silently prices unknown models at gpt-4o-mini's rate.
- **`batch_generate` turns every per-prompt exception into `{"error": …}` in the result
  list**, with no counter. An agent that averages over the results will not notice that
  the whole batch failed.

## Substituting models

Every task's `instruction.txt` names the models the *source paper* used — gpt-3.5-turbo,
gpt-4o, llama-2-70b, gemini-1.5-pro. A deployment that serves none of them turns every
task into a zero that is a property of the box rather than of the agent. So the goal
contract carries a **model catalogue**, probed at run time from the benchmark's own
helper, and tells the agent to substitute so that the *contrast the question is about*
survives — weak against strong, short against long, one format against another — and to
name the substitution in the conclusion only where it changes what can be claimed. The
same note is given to every arm, so the substitution is not a difference between them.
