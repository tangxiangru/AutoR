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
| Run 5 | 35 | 8 h + raised retry limits | shared Gemini 3.7 Flash | 16/35 approved Stage 03 | direct 43.6 |

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
the harness killed them at sixty-one minutes. The number measures a missing deadline in the
prompt, not missing knowledge.

> **Correction.** This paragraph used to end "the eleven that finished average 28.4". They
> average **9.4** — the same figure as the arm row above it, which is what the table's
> "scoreable 11/35" denominator already means. 28.4 is `claude-stock`'s F1 in **Run 1**,
> the withdrawn pilot: a number carried across from a retracted table into later prose.
> See the corrections section at the end of this file.

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

Run 4 with the limits that actually bound it raised: `--max-attempts` 2→6, `--max-auto-skips` 1→4, `--max-operator-calls-per-stage` 4→8, and the clock 3 h→8 h. In Run 4 every failed stage had used exactly two attempts and been auto-skipped, so this is the direct test of whether the pipeline was unable or merely cut off — and the extra attempts are spent and convert: Stage 03 went from 12 approved / 22 skipped to 16 / 4, with thirteen cells passing on the third attempt, four on the fourth and one on the sixth.

> **This table replaces a mid-flight snapshot.** The section published here first was written by a finisher script that fired when `squeue` briefly emptied between the array ending with 40 SIGTERMed cells and a resubmission resuming them; it scored 65 of 105 cells and its numbers ran the other way. Every figure below is from the complete campaign.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 35/35 | 30.1 ± 26.1 | 43.4 ± 32.4 | 30.1 ± 25.2 |
| `autor-direct` | 35/35 | 38.8 ± 23.9 | 58.5 ± 30.7 | 43.6 ± 23.7 |
| `claude-stock` | 29/35 | 16.1 ± 14.0 | 49.2 ± 31.8 | 21.0 ± 18.1 |

Counting an unscoreable run as 0, which is what upstream's scorer does:

| arm | Prec. | Recall | F1 |
|:---|---:|---:|---:|
| `autor-pipeline` | 30.1 ± 26.1 | 43.4 ± 32.4 | 30.1 ± 25.2 |
| `autor-direct` | 38.8 ± 23.9 | 58.5 ± 30.7 | 43.6 ± 23.7 |
| `claude-stock` | 13.4 ± 14.2 | 40.8 ± 34.4 | 17.4 ± 18.2 |

`autor-direct − autor-pipeline`: 35 complete pairs, median **+12.0 F1**, 22 wins / 12 losses / 1 ties.

`claude-stock` produced no scoreable conclusion on 6 task(s): `premise_order_effects`, `prompt_formatting_sensitivity`, `questbench`, `seca_hallucination`, `to_cot_or_not_to_cot`, `uncertainty_in_instruction_following`.

---

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

The obvious explanation is shape: the bare arm's scored text is a median 3,228 characters
against a 255-character reference, and precision is a ratio over the agent's own claims.
It was tested and it is wrong. One extra call restated each bare answer in the reference
register — no new information, no new experiment, not even a new reading of the task:

| | chars | claims extracted | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|---:|
| `claude-bare`, as produced | 3,228 | 12 | 14.0 | 39.2 | 16.3 |
| the same answers, compressed | **1,164** | **12** | 13.8 | 39.9 | **17.1** |

**36% of the characters, the same twelve claims, and no score.** The grader decomposes
propositions, not sentences; writing shorter compresses the prose around the assertions
and leaves the assertions. Claim count does track precision *across* arms — 12 claims →
14.0, 11 → 24.6, 7 → 41.8 against a 5-claim reference — but it is not reachable by writing
shorter. It is reached by asserting less, which means deciding what the question asked.

### What it is instead

The floor arm recites the literature's consensus, and the literature's consensus **is** the
reference. An arm that actually experiments reports what *it* measured — on this deployment,
against substituted models, at whatever scale fits the clock — and that often differs from
the paper. The honest run is the one that diverges.

This is the same mechanism as the ceiling case described under Run 3, seen from the other
side: a correct null reported at a ceiling scores near nothing, while a sentence recalling
what the literature says scores well.

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

## Run 8 — the three skills

35 tasks × 2 arms = 70 cells · deadline **28800 s** · Run 5's limits · `src/skills/` seated

Run 5 with three skills available: `a-ceiling-is-not-a-null`, `both-arms-or-no-claim`,
`a-conclusion-is-not-a-report`. Each was written from a *failure mechanism* visible in the
runs rather than from any task's answer, and `tests/test_firebench_skills_do_not_leak.py`
holds them to that.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 35/35 | 27.7 ± 20.3 | 45.3 ± 28.0 | 30.4 ± 22.3 |
| `autor-direct` | 35/35 | 45.3 ± 30.2 | 57.1 ± 30.6 | 46.2 ± 27.8 |

`autor-direct − autor-pipeline`: 35 complete pairs, median **+10.3 F1**, 23 wins / 8 losses / 4 ties.

Against Run 5, `direct` moves 43.6 → 46.2 and `pipeline` 30.1 → 30.4. Read that as *not
distinguishable from Run 5 at this sample size* rather than as a small gain: the paired
per-task spread within one configuration is wide enough (see "Two things about the numbers
themselves") that a 2.6-point arm mean is inside it.

**The skills only ever reached one arm.** The audit that follows Run 9 found `pipeline`
loaded 3,981 skills across 34 cells and `direct` loaded **0** across 35 — `install_run_skills`
was called on the pipeline branch only. So this row is not "AutoR with skills" versus
"AutoR without"; it is the pipeline with skills against the direct profile with none, and
the direct arm's 46.2 owes nothing to them.

---

## Run 9 — search off

35 tasks × 2 arms = 70 cells · deadline **28800 s** · Run 5's limits · `--web-search off`

Whether the agents were recovering the papers' findings rather than rediscovering them.
`--web-search off` declines to seat AutoR's Gemini search server and denies Claude Code's
own `WebSearch`/`WebFetch`; it is not a general network kill switch, and an agent that
shells out to `curl` is not stopped by it.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 28/35 | 27.4 ± 19.4 | 44.8 ± 31.9 | 29.4 ± 19.9 |
| `autor-direct` | 28/35 | 38.2 ± 29.2 | 51.4 ± 30.7 | 39.6 ± 28.3 |

Both arms failed to produce a scoreable conclusion on the *same* seven tasks. That is the
finding, not the means: seven of thirty-five tasks are ones where **both** profiles die
without search, so the seven are a property of the task, not of the profile. The 29.4/39.6
are computed over the twenty-eight that survived and are therefore not comparable to Run 5's
thirty-five — the seven that dropped out are not a random seven.

---

## Run 10 — the paired rerun after the audit

35 tasks × 2 arms = 70 cells · deadline **28800 s** · Run 5's limits · four audit fixes

An audit of Runs 3–9 found four defects that had been live the whole time, and this run is
the clean-configuration repeat with all four fixed:

1. **The reviewer was never confined.** `strict_mcp` was applied via
   `getattr(reviewer, "operator")`, and the attribute is `_operator`, so it silently read
   `None`. Six campaigns ran with an unconfined reviewer; six real `ai4ai-web-search` calls
   came out of `review_start`. Fixed by threading `strict_mcp` through
   `ApprovalAgent.__init__`.
2. **Skills reached one arm only** — 3,981 loads on `pipeline`, 0 on `direct`.
   `install_run_skills` now runs on both branches.
3. **`median_draw` returned the max on an even number of samples.** Ten cells were affected.
   Now lower-middle.
4. **`OPENAI_BASE_URL=""`** in four campaigns, which sends the SDK to `api.openai.com`
   instead of the deployment.

| arm | scoreable | Prec. | Recall | F1 |
|:---|---:|---:|---:|---:|
| `autor-pipeline` | 35/35 | 28.5 ± 19.0 | 49.6 ± 28.1 | 32.2 ± 20.1 |
| `autor-direct` | 35/35 | 39.9 ± 25.8 | 57.2 ± 29.0 | 42.4 ± 24.3 |

`autor-direct − autor-pipeline`: 35 complete pairs, median **+7.8 F1**, 20 wins / 12 losses / 3 ties.

This is the run to quote. It is the only campaign in which every cell in both arms scored,
every known configuration defect is fixed, and the two arms differ in the profile and
nothing else. The ordering it reports — `direct` ahead of `pipeline` by a median of 7.8
paired F1 — is the same ordering Runs 5, 8 and 9 reported, at a smaller margin.

---

## Run 11 — **WITHDRAWN**: the treatment was never applied

35 tasks × 2 arms = 70 cells · plan byte-identical to Run 10 · **do not quote its numbers**

Run 11 was meant to add three open-weight Llamas (Vertex Model Garden, `provider="vertex-maas"`)
to the model catalogue and change nothing else. It reported `autor-pipeline` 32.2 → **43.8**
and `autor-direct` 42.4 → 43.2, flipping the ordering between the profiles.

**The catalogue never reached a single prompt.** Run 11 was submitted from a virtualenv
with no `openai` installed. `agents/claude/run.py` imports the benchmark's helper directly
and `fire_agent.py` probed it in a subprocess under the same interpreter, so both lost it;
`_probe_model_catalog` returned `None` and the goal contract substituted its no-catalogue
fallback. Measured, not inferred:

- **69 of 69** Run 11 prompts contain `No model catalogue was supplied to this run.`
- **0 of 69** contain the open-weight line.
- **70 of 70** Run 10 prompts contain the full frontier catalogue.
- Same task, same arm: the prompt shrank 8205 → 7166 bytes.

So Run 11's agents did not get *more* than Run 10's. They got **less** — the whole model
block, including the paragraph telling them not to drop an arm whose model is missing.
Whatever moved pipeline 11.6 points, it was not the treatment this run was named after,
and the run cannot be used to argue for or against the open-weight hypothesis.

The capability did reach the sandbox by a side channel: 63 of 70 cells made successful
Vertex MaaS calls after reading the staged `ws/utils/llm_inference.py` themselves. That is
a genuine finding about what agents discover, and it is not the registered experiment.

**The registered prediction failed, and failed backwards.** Even taken at face value, the
gain sits where the mechanism said nothing should move: in `autor-pipeline`, the 23 tasks
naming a Llama moved a median of **+0.0**, and the 12 naming none moved **+22.9** (11 of 12
up, permutation p ≈ 0.011). The prediction's premise was also wrong — 30 of the 35 tasks
name an open-weight model, not 20, so the "control group" it assumed barely exists.

Three further reasons its numbers are unusable, each independent:

1. **Four uncontrolled variables moved with it** — the interpreter, `cpus-per-task` 1→2,
   the node pool, and `a-ceiling-is-not-a-null/SKILL.md`, which was rewritten two minutes
   after Run 10 launched and staged differently into the two campaigns (md5 e3d86c28 →
   96475c06).
2. **The out-of-memory cells gained the most.** Twelve cells were OOM-killed at 12 GiB
   (8 pipeline, 4 direct); pipeline's OOM cells moved a median **+28.3** against **+5.6**
   for the rest. The gain is unusable without ruling that out.
3. **The noise floor for this comparison has never been measured.** Both plans are
   `repeats: 1`. Run 7's three repeats sit inside a single array and estimate cell-level
   noise (per-task sd ≈ 21), not campaign-level offset — and a campaign offset of only
   3.4 F1 is enough to erase the result. Judge noise alone gives a per-cell 3-draw range
   with a median of 13.9 points, so no single task's delta means anything.

### What replaced it

`_probe_model_catalog` now tries several interpreters and records why each failed, a
missing catalogue is **fatal by default** (`--allow-missing-model-catalog` to override),
and `fire_trial.py slurm` refuses to write an sbatch whose interpreter cannot read the
catalogue — one subprocess at submission time, which is the only cheap moment to catch it.
`tests/test_firebench_adapter.py::ModelCatalogueProbeTests` holds all three.

Run 11b and Run 12b were then launched from an interpreter that can: 70 of 70 Run 11b
prompts contain the open-weight line and 0 contain the fallback, checked before the run
was left alone. Run 12b adds `claude-bare` and `claude-stock` at the same 8 h budget and
the same catalogue, so that a bare-Claude-Code comparison finally exists at one
configuration. Both run at 24 GiB.

**None of this rescues Run 11.** It is a lost campaign, kept here for the defect.

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

**The judge is very noisy, and noisy enough to reorder the arms.** Re-scoring one whole
six-task matrix — the same logs, a fresh set of judge draws, nothing else changed — moved
every arm's mean by 4.5 to 5.5 F1 points, moved one cell by **23.1** (`cot_in_planning`,
pipeline arm, 100.0 → 76.9), and **changed the ordering**: `autor-pipeline` was second on
the first pass and third on the second, below `claude-stock`. Both passes are preserved as
`fire-trial/report-pass1.json` and `fire-trial/report.json`.

> **Correction.** This paragraph used to say the largest task move was 13.7 and that the
> ordering did *not* change. Both are false against the two surviving reports, and the
> second was the load-bearing half — it was the basis for "treat the ordering as the
> result". On six tasks the ordering is not stable either. It also cited a 57.1 / 92.3 /
> 100.0 triple from an early single-log probe whose artifacts were not kept; that number is
> withdrawn for want of evidence, and the measured within-cell spread that *is* recoverable
> is the per-metric `min`/`max` in every `_score/summary.json`.

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

---

## Corrections

**Run 11's headline was withdrawn before it was ever quoted outside this file** — the
model catalogue it was named after reached 0 of 69 prompts. The defect it exposed is the
general one: a silently missing input removed a whole section of the goal contract, every
cell still produced a scoreable conclusion, and the only visible symptom was an arm moving
eleven points for no nameable reason. A degradation that leaves the artifact well-formed
is invisible to everything downstream of it.


Five published claims in this file were wrong. They are listed rather than silently edited,
because four of the five share one cause worth naming.

**The cause: numbers carried out of Run 1 after Run 1 was withdrawn.** A retracted table
stops being cited, but its figures had already been written into surrounding prose, and
prose is not re-derived when a table is. The fix in the tooling is
`tools/fire_report_md.py` — tables are now generated from `report.json` — but every
sentence *around* a table is still typed, and that is where all of these were.

| claim as published | what the artifacts say |
|:---|:---|
| "the eleven that finished average **28.4**" (Run 2) | **9.4** — the same figure as the arm row two lines above. 28.4 is `claude-stock`'s F1 in the withdrawn Run 1. |
| the ceiling case "scored **0.0**, while the direct arm found the effect at p = 0.0001 and scored **80.0**" | Neither number exists in any surviving run. `premise_order_effects` is pipeline 54.5 / direct 68.6 in Run 2, 57.7 / **0.0** in Run 3 — the 0.0 is the *direct* arm — and 58.5 / 70.6 in Run 4. The 80.0 was Run 1's. The **mechanism** is real and recoverable from the run tree (~700 billed calls per arm, corrupted control at 0.15, strong model 1.000 in all nine conditions, a null reported anyway); the two scores attached to it were not. |
| compression: "3,217 → **967** characters, a third" | 3,228 → **1,164.5** (medians), 36%. The 967 was one cell's value read as if it were the median. The conclusion is unchanged and in fact slightly stronger: the claim count did not move at all. |
| "moved one task by **13.7** — *without changing the ordering of the arms*" | The largest cell move is **23.1**, and **the ordering did change**: `autor-pipeline` was second on the first pass and third on the second, below `claude-stock`. This was the load-bearing half of the sentence — it was the stated reason to "treat the ordering as the result". On six tasks the ordering is not stable either. |
| "the same unchanged log scored three times returned F1 of **57.1 / 92.3 / 100.0**" | No surviving artifact. Withdrawn for want of evidence. The within-cell spread that *is* recoverable is the per-metric `min`/`max` in every `_score/summary.json`. |

**And one structural error, of a different kind.** The Run 5 section published here first
was a **mid-flight snapshot**: a finisher script waited on `squeue`, which briefly emptied
between the array ending — with 40 cells SIGTERMed by preemption — and a resubmission
resuming them. It scored 65 of 105 cells and wrote a table whose trend ran the opposite way
to the finished campaign's. The waiter should have keyed on cells completed against cells
planned, not on the scheduler being momentarily quiet.

### What was *not* wrong

Every arm row in Runs 2, 3, 4, 6 and 7 recomputes exactly from its `report.json`, as do the
paired medians, the win/loss counts, the parametric floor (29.4 / 26.2), the claim-count
gradient, the Stage 03 attempt-exhaustion diagnosis, and "24 of 35 stock runs produced no
conclusion". The errors were all in prose written *beside* generated tables, not in the
tables.
