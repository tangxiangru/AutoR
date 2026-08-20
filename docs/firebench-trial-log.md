# FIRE-Bench trial log

A record of what was actually run against [FIRE-Bench](firebench.md), in order, including
the two runs whose numbers were withdrawn. It is kept because the withdrawals are the
useful part: both were invisible in the artifacts — every cell produced a plausible
conclusion and a plausible score — and both were found by diffing the adapter against the
official implementation rather than by anything going wrong.

Dates are 2026-08-18/19. Executing and reviewing model is `opus` (`claude-opus-5[1m]` via
Vertex) throughout, and within any one run every arm is held to the same wall clock.

| | tasks | budget | search | pipeline walk completed | best arm's F1 |
|:---|---:|---:|:---|---:|---:|
| Run 1 | 6 | 3600 s | AutoR: none · stock: built-ins | 0/6 | **withdrawn** |
| Run 2 | 35 | 3600 s | AutoR: none · stock: built-ins | 0/35 | direct 41.5 |
| Run 3 | 35 | 3600 s | shared Gemini 3.7 Flash | 0/35 | direct 40.2 |
| Run 4 | 35 | 3 h | shared Gemini 3.7 Flash | **13/34** | direct 44.0 |
| Run 5 | 35 | 8 h + raised retry limits | shared Gemini 3.7 Flash | *in flight* | *in flight* |

**Read every number against a floor of 29.4, not against zero.** One `opus` call with no
tools, no data and no experiment scores **F1 29.4** on these 35 tasks (Run 7) — more than
either Claude Code arm achieves with three hours of real experimentation. These papers are
in the model's training data, and the benchmark cannot tell recall of the literature from
rediscovery of it.

**The one result that has not moved across every condition**: `autor-direct` — one agentic
call with the same goal, model, tools and clock — beats `autor-pipeline` on every one of
them, by a median of +8.9, +7.1 and +6.2 F1. The gap narrows as the pipeline is given more
room, which is the reason Run 5 exists.

---

## The three arms

| arm | what it is | what it isolates |
| --- | --- | --- |
| `autor-pipeline` | `fire_agent.py --profile pipeline`: Stage 02→05 plus one synthesis call | — |
| `autor-direct` | `fire_agent.py --profile direct`: one agentic operator call, **same goal text, model, tools, sandbox and deadline** | pipeline minus direct = the pipeline |
| `claude-stock` | the benchmark's own `agents/claude/run.py` on the raw `instruction.txt` | direct minus stock = the goal contract |

Without the third arm, a pipeline that beat the published baseline could be a pipeline that
worked or a prompt that told the model how the grader works, and the run cannot say which.

---

## Run 1 — 6 tasks — **WITHDRAWN**

Pilot, run on one node with a thread pool. Reported, then withdrawn on the same day.

| arm | scoreable | Prec. | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| autor-pipeline | 6/6 | 23.8 ± 28.0 | 30.6 ± 40.0 | 25.7 ± 31.5 |
| autor-direct | 6/6 | 60.8 ± 20.1 | 61.7 ± 14.3 | 60.6 ± 17.2 |
| claude-stock | 2/6 | 18.1 ± 9.8 | 66.7 ± 23.5 | 28.4 ± 14.4 |

**Why it was withdrawn.** Two defects, both found by audit, neither visible in any artifact:

1. **The AutoR arms had no OpenAI credentials and the stock arm did.** The benchmark's own
   agents call `load_dotenv()` and hand the sandbox its keys; the adapter did neither, and
   `utils/llm_inference.py` reads `os.getenv`. Ten of twelve AutoR cells logged
   `Missing credentials` on their first OpenAI call. So the two arms had different model
   catalogues — and the goal contract told both of them the larger one, which made it a
   false statement in one arm's prompt.
2. **Two cells read the source papers.** `--web-search off` denies `WebSearch` and
   `WebFetch` and declines to seat AutoR's own Gemini server; a *user-level* MCP server in
   `~/.claude.json` is outside all of that by design. On this box that was
   `ai4ai-web-search`, and `mcp__ai4ai-web-search__web_search` was called nine times across
   two cells — on a benchmark where every answer is in a paper's abstract.

It also carried a reporting defect, fixed separately: the per-cell row took the median of
each metric independently, so its three numbers came from three different judge draws and
`F1 = 2PR/(P+R)` failed on two of them. Rows now come from one draw (`median_draw`).

---

## Run 2 — 35 tasks — **superseded**

First full split. SLURM array, 105 cells, credentials and MCP confinement fixed. Browsing
**denied** in the AutoR arms (`--web-search off`) and Claude Code's built-ins left in place
on the stock arm.

| arm | scoreable | Prec. | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| autor-pipeline | 33/35 | 36.7 ± 29.0 | 33.4 ± 27.9 | 30.7 ± 26.5 |
| autor-direct | 35/35 | 37.6 ± 23.3 | 56.1 ± 31.2 | 41.5 ± 22.2 |
| claude-stock | 11/35 | 11.1 ± 13.8 | 21.8 ± 24.1 | 9.4 ± 13.9 |

Counting an unscoreable run as 0, which is what upstream's own scorer does:

| arm | Prec. | Recall | F1 |
| --- | ---: | ---: | ---: |
| autor-pipeline | 34.6 ± 29.4 | 31.5 ± 28.2 | 29.0 ± 26.7 |
| autor-direct | 37.6 ± 23.3 | 56.1 ± 31.2 | 41.5 ± 22.2 |
| claude-stock | 3.5 ± 9.2 | 6.9 ± 16.6 | 3.0 ± 8.8 |

`autor-direct − autor-pipeline`: 33 complete pairs, median **+8.9 F1**, 20 wins / 10 losses
/ 3 ties. Health: 0 `Missing credentials`, 0 user-MCP search calls, 0 backend 429s.

**Why it is superseded, not withdrawn.** Nothing in it is wrong; it answers a different
question. The arms were not searching with the same thing — the AutoR arms could not browse
at all and the stock arm had Claude Code's built-in `WebSearch` — so the `direct − stock`
contrast conflates the goal contract with a difference in what each arm could look up. It
stands as the **browsing-denied** condition.

**What the stock arm's 9.4 is, and is not.** It is not a search deficit. Twenty-four of its
thirty-five runs produced *no conclusion at all*: given the raw `instruction.txt`, which
asks for a full report and never mentions a deadline, they were still building figures when
the harness killed them at sixty-one minutes. The eleven that finished average 28.4. The
number measures a missing deadline in the prompt, not missing knowledge.

---

## Run 3 — 35 tasks, shared search, harness budget

35 tasks × 3 arms = 105 cells · deadline **3600 s** · adapter defaults

All three arms on `mcp__autor-search__web_search` (`gemini-3.7-flash` on Vertex), Claude Code's built-ins denied, `--strict-mcp-config` always. The stock arm is additionally told the wall clock and asked to write `conclusion.md` early. **This is the only condition whose budget matches the published baselines'.**

The stock arm goes from 11/35 scoreable in Run 2 to **35/35** here. Two sentences of prompt and a `conclusion.md` fallback, not a better agent: its F1 rises from 9.4 to 16.7 because runs that used to be killed with nothing now say something, and what they say is mediocre.

The pipeline arm completed its walk on **0 of 35** tasks, exactly as in Run 2.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 35/35 | 30.2 ± 28.4 | 39.7 ± 30.3 | 29.9 ± 25.9 |
| `autor-direct` | 35/35 | 38.2 ± 28.8 | 53.9 ± 35.3 | 40.2 ± 27.1 |
| `claude-stock` | 35/35 | 13.8 ± 13.3 | 37.6 ± 32.7 | 16.7 ± 17.4 |

Counting an unscoreable run as 0, which is what upstream's scorer does:

| arm | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| `autor-pipeline` | 30.2 ± 28.4 | 39.7 ± 30.3 | 29.9 ± 25.9 |
| `autor-direct` | 38.2 ± 28.8 | 53.9 ± 35.3 | 40.2 ± 27.1 |
| `claude-stock` | 13.8 ± 13.3 | 37.6 ± 32.7 | 16.7 ± 17.4 |

`autor-direct − autor-pipeline`: 35 complete pairs, median **+7.1 F1**, 20 wins / 8 losses / 7 ties.


---

## Run 4 — 35 tasks, shared search, three-hour budget

35 tasks × 3 arms = 105 cells · deadline **10800 s** · adapter defaults

Run 3 with the wall clock tripled and nothing else changed.

**Not one pipeline cell was stopped by the clock**: `deadline_hit` is False on all thirty-five. They ran 1.4–2.5 h and the walk ended on its own — a stage exhausted `--max-attempts 2`, was auto-skipped, and the second skip spent `--max-auto-skips 1`. Seventeen approved exactly one stage, and the run tree shows `03_study_design.md` and `04_implementation.md` written but never approved. Tripling the budget still raised walk completion from 0/35 to **13/34**, which is what more retries inside a longer clock buys; Run 5 raises the retry limits themselves.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 34/35 | 31.4 ± 24.4 | 48.5 ± 30.9 | 33.4 ± 24.5 |
| `autor-direct` | 35/35 | 42.5 ± 24.8 | 55.8 ± 29.8 | 44.0 ± 23.5 |
| `claude-stock` | 33/35 | 15.2 ± 16.9 | 41.8 ± 33.3 | 18.0 ± 16.7 |

Counting an unscoreable run as 0, which is what upstream's scorer does:

| arm | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| `autor-pipeline` | 30.5 ± 24.6 | 47.1 ± 31.5 | 32.4 ± 24.8 |
| `autor-direct` | 42.5 ± 24.8 | 55.8 ± 29.8 | 44.0 ± 23.5 |
| `claude-stock` | 14.3 ± 16.7 | 39.4 ± 33.8 | 17.0 ± 16.8 |

`autor-direct − autor-pipeline`: 34 complete pairs, median **+6.2 F1**, 21 wins / 8 losses / 5 ties.

`autor-pipeline` produced no scoreable conclusion on 1 task(s): `counterfactual_simulatability`.

`claude-stock` produced no scoreable conclusion on 2 task(s): `premise_order_effects`, `prompt_formatting_sensitivity`.

## Run 5 — 35 tasks, shared search, eight-hour budget, retry limits raised

35 tasks × 3 arms = 105 cells · deadline **28800 s** · --max-attempts 6 --max-auto-skips 4 --max-operator-calls-per-stage 8 --reserve-seconds 1800

Run 4 with the limits that actually bound it raised: `--max-attempts` 2→6, `--max-auto-skips` 1→4, `--max-operator-calls-per-stage` 4→8, and the clock 3 h→8 h. In Run 4 every failed stage had used exactly two attempts and been auto-skipped, so this is the direct test of whether the pipeline was unable or merely cut off.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 19/35 | 24.4 ± 15.6 | 46.9 ± 36.9 | 28.1 ± 23.1 |
| `autor-direct` | 23/35 | 36.3 ± 22.7 | 50.4 ± 29.5 | 38.8 ± 24.0 |
| `claude-stock` | 17/35 | 13.6 ± 14.0 | 53.5 ± 26.9 | 18.9 ± 17.9 |

Counting an unscoreable run as 0, which is what upstream's scorer does:

| arm | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| `autor-pipeline` | 13.2 ± 16.7 | 25.5 ± 35.8 | 15.3 ± 22.0 |
| `autor-direct` | 23.8 ± 25.3 | 33.1 ± 33.9 | 25.5 ± 26.9 |
| `claude-stock` | 6.6 ± 11.8 | 26.0 ± 32.8 | 9.2 ± 15.6 |

`autor-direct − autor-pipeline`: 19 complete pairs, median **+8.3 F1**, 13 wins / 5 losses / 1 ties.

`autor-pipeline` produced no scoreable conclusion on 16 task(s): `fallback_behaviors`, `fractal_complexity_of_language`, `hallucination_awareness`, `hallucination_snowballing`, `hallusionbench_illusion`, `icl_from_repetition`, `introspective_learning`, `lifebench_length_following`, `llm_confidence_elicitation`, `llm_racial_bias_in_medicine`, `llm_value_consistency`, `llms_assume_rationality`, `llms_lack_self_correction`, `lost_in_the_middle`, `mathvista_visual_math`, `mcq_selection_bias`.

`autor-direct` produced no scoreable conclusion on 12 task(s): `fallback_behaviors`, `fractal_complexity_of_language`, `hallucination_snowballing`, `icl_from_repetition`, `introspective_learning`, `lifebench_length_following`, `llm_confidence_elicitation`, `llms_assume_rationality`, `llms_lack_self_correction`, `lost_in_the_middle`, `mathvista_visual_math`, `mcq_selection_bias`.

`claude-stock` produced no scoreable conclusion on 18 task(s): `fallback_behaviors`, `fractal_complexity_of_language`, `hallucination_awareness`, `hallusionbench_illusion`, `icl_from_repetition`, `introspective_learning`, `llm_value_consistency`, `llms_assume_rationality`, `llms_lack_self_correction`, `lost_in_the_middle`, `mathvista_visual_math`, `mcq_selection_bias`, `premise_order_effects`, `prompt_formatting_sensitivity`, `questbench`, `seca_hallucination`, `to_cot_or_not_to_cot`, `uncertainty_in_instruction_following`.

## Run 6 — bare Claude Code, three-hour budget

35 tasks × 1 arms = 35 cells · deadline **10800 s** · adapter defaults

Upstream's agent with none of this repository's task-facing additions: no wall-clock sentence, no request for a conclusion file, and Claude Code's own `WebSearch` rather than the shared Gemini server. It keeps only the fixes that decide whether a run can be recorded. Compare against Run 4's arms, which share its budget.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `claude-bare` | 34/35 | 13.8 ± 13.1 | 35.7 ± 29.2 | 16.3 ± 14.5 |

Counting an unscoreable run as 0, which is what upstream's scorer does:

| arm | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| `claude-bare` | 13.4 ± 13.1 | 34.7 ± 29.4 | 15.8 ± 14.6 |

`claude-bare` produced no scoreable conclusion on 1 task(s): `llms_assume_rationality`.

---

## Run 7 — the floor: what the benchmark scores with no experiment at all

The premise of FIRE-Bench is **rediscovery**: an agent designs and runs experiments and
arrives at a finding the paper's authors also arrived at. That premise assumes the finding
is not already in the model. These are published papers, most of them from 2023–2024, and
the model under test is later than all of them.

So: one call per task, the research question only, **no tools, no data, no experiment, no
browsing** — `claude -p` with every tool denied by name and `--strict-mcp-config` over an
empty server list, so "did not run anything" is enforced rather than requested. Same
binary, same model, same grader as the arms.

| | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| **parametric floor** (`opus`, one call, nothing else) | 25.2 ± 16.4 | 55.4 ± 31.9 | **29.4 ± 20.6** |
| the same probe on `gpt-5.1` | 28.0 ± 18.8 | 33.5 ± 25.1 | 26.2 ± 19.1 |
| `claude-bare` — three hours of real experiments | 13.8 ± 13.1 | 35.7 ± 29.2 | **16.3 ± 14.5** |
| `claude-stock` — three hours of real experiments | 15.2 ± 16.9 | 41.8 ± 33.3 | 18.0 ± 16.7 |
| `autor-pipeline` | 31.4 ± 24.4 | 48.5 ± 30.9 | 33.4 ± 24.5 |
| `autor-direct` | 42.5 ± 24.8 | 55.8 ± 29.8 | 44.0 ± 23.5 |

**Answering from memory beats three hours of real experimentation, on both precision and
recall.** Reading any of these numbers as an absolute is therefore wrong; only the distance
above 29.4 can be attributed to the research:

| arm | F1 | above the floor |
|:---|---:|---:|
| `claude-bare` | 16.3 | **−13.1** |
| `claude-stock` | 18.0 | **−11.4** |
| `autor-pipeline` | 33.4 | +4.0 |
| `autor-direct` | 44.0 | **+14.6** |

Two arms score *below* the cost of doing nothing.

### It is not the length of the answer

The obvious explanation is shape: the bare arm's scored text is a median 3,217 characters
against a 245-character reference, and precision is a ratio over the agent's own claims.
It was tested and it is wrong. One extra call restated each bare answer in the reference
register — no new information, no new experiment, not even a new reading of the task:

| | chars | claims extracted | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|---:|
| `claude-bare`, as produced | 3,217 | 12 | 14.0 | 39.2 | 16.3 |
| the same answers, compressed | 967 | **12** | 13.8 | 39.9 | **17.1** |

A third of the characters, **the same twelve claims**, and no score. The grader decomposes
propositions, not sentences; writing shorter compresses the prose around the assertions
and leaves the assertions. Claim count does track precision *across* arms — 12 claims →
14.0, 11 → 24.6, 7 → 41.8 against a 5-claim reference — but it is not reachable by writing
shorter. It is reached by asserting less, which means deciding what the question asked.

### What it is instead

The floor arm recites the literature's consensus, and the literature's consensus **is** the
reference. An arm that actually experiments reports what *it* measured — on this deployment,
against substituted models, at whatever scale fits the clock — and that often differs from
the paper. The honest run is the one that diverges.

This is the same mechanism as the `premise_order_effects` case in Run 4, seen from the
other side: 112 items × 9 orderings × 2 models, a corrupted-item control at 0.15, and a
correct null reported at a ceiling — scored 0.0, while a sentence recalling what the
literature says would have scored well.

### Why the published table is higher, and what part of the gap this is

FIRE-Bench's Table 3 puts Claude Code (Sonnet-4) at 52.1 / 48.3 / **46.7**, against
`claude-bare`'s 16.3 here. Four contributors, in what the evidence supports as descending
order:

1. **The models the tasks name are not served here.** Every task's `instruction.txt` lists
   the models the source paper used — `gpt-3.5-turbo`, `gpt-4o`, `llama-2-70b`,
   `gemini-1.5-pro`. The intersection with this deployment is **empty**. Every arm
   substitutes frontier models, and several of these papers' effects are gone at the
   frontier. An agent that reproduces the paper's *design* on models the paper never used
   gets the paper's conclusion wrong, correctly.
2. **A different claim judge.** The shipped extractor/checker is `openai/gpt-4.1`, which
   404s here; ours is `openai/gpt-5.1`. It decides both the decomposition (the denominator
   of precision) and every entailment verdict. Untestable here, and not small.
3. **A different executing model** (`opus` vs Sonnet-4), whose final-message style is
   longer and more structured — which costs claims.
4. **A different task population** — 35 verified here, 30 in the paper's table.

None of this makes the arm-to-arm comparisons in this log wrong: within a run they share
the judge, the model, the catalogue, the clock and the tools. It makes the *absolute*
numbers incomparable to the paper, and it makes the floor, not zero, the origin.

### Reproducing

```bash
python3 tools/fire_parametric_probe.py --bench-root ~/FIRE-Bench \
    --out-root ~/fire-parametric --model opus --backend claude-cli --score
```

---

## What may and may not be compared to the paper

FIRE-Bench's Table 3 best row is CC(Sonnet-4) at **52.1 ± 26.1 / 48.3 ± 24.8 / 46.7 ± 23.4**.
Nothing here is a like-for-like comparison to it, for four reasons that are worth keeping
separate:

1. **A different judge.** The shipped extractor/checker is `openai/gpt-4.1`, which this
   deployment does not serve — and an unserved name does not fail there, it hangs forever
   in RefChecker's retry loop. Ours is `openai/gpt-5.1`. It decomposes both texts into the
   atomic claims that are the denominator of both precision and recall, so this moves
   numbers.
2. **A different executing model** (`opus` vs Sonnet-4).
3. **Substituted subject models.** None of the models the tasks name is served here, so
   every arm substitutes from one catalogue and every arm answers a slightly different
   question from the one the papers answered. This is also the likeliest source of the
   ceilings that turn a faithful reproduction into a null: several of these papers measured
   gpt-3.5 and Llama-2-era models.
4. **A different task population.** 35 verified tasks here; the paper's table covers 30.

What *is* sound is the comparison between arms: within a run they share the judge, the
model, the catalogue, the clock and the tools, and every difference between them is the one
being measured.

## Two things about the numbers themselves

**A row is one draw.** Each cell is scored three times and the reported row is the draw
whose F1 is the median — one run, so `F1 = 2PR/(P+R)` holds on it. Across tasks each metric
is averaged independently, which is what the paper does and is correct at that level: its
own 52.1 and 48.3 give a harmonic mean of 50.1, not the 46.7 it prints.

**The judge is very noisy.** The same unchanged log scored three times returned F1 of 57.1,
92.3 and 100.0. Re-scoring one whole six-task matrix moved every arm's mean by 4–5 F1 points
and moved one task by 13.7 — *without changing the ordering of the arms*. Treat the ordering
as the result and any single number as one draw of a noisy instrument.

## Reproducing

```bash
python3 tools/fire_trial.py plan   --out ~/fire-trial/plan.json --tasks $(ls ~/FIRE-Bench/benchmark/papers)
python3 tools/fire_trial.py slurm  --plan ~/fire-trial/plan.json --throttle 105 --cpus 1 --mem 3G
python3 tools/fire_trial.py score  --plan ~/fire-trial/plan.json --draws 3 --concurrency 6
python3 tools/fire_trial.py report --plan ~/fire-trial/plan.json
```

The throttle is a **quota** number, not a node count: what runs out first is the
per-base-model request pool the backend shares with every other session on the machine.
Measured headroom when this was written was 24 concurrent with zero 429s, and 105 concurrent
1-CPU cells also ran clean once the cluster had the cores.
