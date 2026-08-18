# FIRE-Bench trial log

A record of what was actually run against [FIRE-Bench](firebench.md), in order, including
the two runs whose numbers were withdrawn. It is kept because the withdrawals are the
useful part: both were invisible in the artifacts — every cell produced a plausible
conclusion and a plausible score — and both were found by diffing the adapter against the
official implementation rather than by anything going wrong.

Dates are 2026-08-18. Executing and reviewing model is `opus` (`claude-opus-5[1m]` via
Vertex) throughout. Every arm in every run is held to FIRE-Bench's own 3600 s wall clock.

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

## Run 3 — 35 tasks, shared search — *in flight*

Same three arms, same clock, same everything, with one change: **all three arms reach the
web through the same tool and only that one.**

| | |
| --- | --- |
| search tool | `mcp__autor-search__web_search` |
| backend | `gemini-3.7-flash` on Vertex AI, location `global`, Google Search grounding |
| denied in every arm | `WebSearch`, `WebFetch` |
| `--strict-mcp-config` | always, in both arms |

Browsing is on because the published baselines had it: Claude Code ships `WebSearch`, and a
run that denies it is not the run the leaderboard describes. What a paired comparison needs
is not that the arms cannot search but that they search identically.

Verified before launch rather than assumed: `gemini-3.7-flash` answers on Vertex and its
grounding fires with real queries and real sources; the stock arm's helper reports
`vertex / gemini-3.7-flash`; a CLI given that config called `mcp__autor-search__web_search`
and returned a grounded answer; and at launch all 35 stock sandboxes held the shared server
config while every AutoR run tree held it alongside `autor-write`.

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
