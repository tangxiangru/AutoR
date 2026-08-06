# ResearchClawBench landscape: EvoScientist, ARIS Codex, MIRA

Competitive context for [running AutoR on ResearchClawBench](researchclawbench.md).
Every number below other than MIRA's own was recomputed from the published leaderboard JSON;
the reproduction steps are at the bottom.

*Compiled 2026-08-06. Leaderboard data pulled from
`internscience.github.io/ResearchClawBench-Home/data/leaderboard.json`
(32 agents, 40 tasks). MIRA numbers read from the
[MIRA Tech Report](https://www.deepprinciple.com/papers/MIRA_Tech_Report.pdf), dated
2026-08-03.*

---

## The headline finding

**Only two of the three are on the ResearchClawBench leaderboard.** MIRA is not, and never
has been. Its ResearchClawBench result is **self-reported in its own tech report**, on a
**3-of-10 domain subset that MIRA chose**, against **six agents it selected**.

That is not automatically a problem — but it changes what the numbers mean:

| | EvoScientist | ARIS Codex | MIRA |
|:---|:---|:---|:---|
| On the official leaderboard | ✅ two versions | ✅ | ❌ |
| Result verified by the benchmark authors | ✅ | ✅ (imported run) | ❌ self-reported |
| Tasks evaluated | 40/40 | 40/40 | 12/40 (Chemistry, Energy, Materials) |
| Underlying model | GPT-5.4 | GPT-5.4 | GPT-5.4 |

**MIRA's baselines, however, are real.** I reproduced all six of its comparison agents from
the public leaderboard under MIRA's own protocol. Every one matches to within rounding:

| Agent | Chemistry | Energy | Materials | 3-domain mean | MIRA reports | Δ |
|:---|---:|---:|---:|---:|---:|---:|
| ResearchClaw | 8.47 | 19.01 | 19.26 | **15.58** | 15.60 | −0.02 |
| EvoScientist (0.1.1) | 9.94 | 19.90 | 15.15 | **15.00** | 15.00 | 0.00 |
| Codex CLI | 7.62 | 23.05 | 12.96 | **14.54** | 14.57 | −0.03 |
| OpenClaw | 5.96 | 22.00 | 12.92 | **13.63** | 13.63 | 0.00 |
| ARIS Codex | 7.40 | 13.59 | 12.44 | **11.14** | 11.13 | +0.01 |
| Nanobot | 6.21 | 13.49 | 13.00 | **10.90** | 10.90 | 0.00 |

So MIRA lifted the official runs for its baselines and computed the subset mean correctly.
Only MIRA's own row (17.51) is unaudited.

---

## Full-benchmark standing (all 40 tasks, official leaderboard)

| Rank | Agent | Mean | Median | Best task | $/task | Model |
|---:|:---|---:|---:|---:|---:|:---|
| 1 | Qiushi Engine | 30.19 | 28.3 | 56.9 | 18.30 | GPT-5.5 |
| 2 | InnoClaw | 23.72 | 20.6 | 54.6 | 7.10 | GPT-5.5 |
| 4 | Claude Code | 21.53 | 23.5 | 48.0 | 5.25 | Claude-Opus-4.6 |
| **10** | **EvoScientist (0.1.1)** | **18.76** | 14.3 | 55.6 | 4.08 | GPT-5.4 |
| 12 | Codex CLI | 18.42 | 15.7 | 45.0 | 2.01 | GPT-5.4 |
| **22** | **EvoScientist (0.0.4)** | **15.47** | 13.2 | 47.3 | 1.19 | GPT-5.4 |
| 24 | ResearchHarness (GPT-5.4) | 15.28 | 11.4 | 44.8 | 2.12 | GPT-5.4 |
| **27** | **ARIS Codex** | **13.58** | 11.2 | 47.4 | 0.74 | GPT-5.4 |
| 31 | Nanobot | 12.81 | 9.8 | 44.2 | 0.49 | GPT-5.4 |
| — | *MIRA* | *not evaluated on 40 tasks* | | | | |

Context for the scale: **50 means matching the original human paper.** Across 32 agents and
40 tasks, exactly **three agent-task pairs** have ever crossed it — Qiushi 56.9
(Material_003), EvoScientist 0.1.1 55.6 (Physics_003), InnoClaw 54.6 (Physics_003). No
agent has a *mean* above 31. The whole field is still in partial-rediscovery territory.

---

## Finding 1 — MIRA's "highest score" holds only inside its chosen cohort

MIRA claims it "attains the highest score at the lowest cost per task among seven agents
compared." Both halves are true *as stated*. Neither survives widening the field.

Re-scoring **every** leaderboard agent under MIRA's exact protocol (Chemistry + Energy +
Materials, 12 tasks, unweighted domain mean):

| Rank | Agent | 3-domain | $/task | Model |
|---:|:---|---:|---:|:---|
| 1 | Qiushi Engine | 29.03 | 22.14 | GPT-5.5 |
| 2 | InnoClaw | 20.49 | 12.42 | GPT-5.5 |
| 3 | ResearchHarness (Claude-Opus-4.8) | 20.36 | 5.30 | Claude-Opus-4.8 |
| 4 | Claude Code | 18.85 | 11.18 | Claude-Opus-4.6 |
| 5 | ResearchHarness (Qwen3.7-Max) | 18.69 | 0.58 | Qwen3.7-Max |
| 8 | ResearchHarness (DeepSeek-V4-Pro) | **17.98** | **0.40** | DeepSeek-V4-Pro |
| **11** | **MIRA** *(self-reported)* | **17.51** | **0.67** | GPT-5.4 |
| 16 | ResearchClaw | 15.58 | 0.91 | GPT-5.4 |
| 17 | EvoScientist (0.1.1) | 15.00 | 5.80 | GPT-5.4 |
| 19 | Codex CLI | 14.54 | 2.70 | GPT-5.4 |
| 29 | ARIS Codex | 11.14 | 0.94 | GPT-5.4 |
| 31 | ResearchHarness (GPT-5.4) | 10.56 | 1.64 | GPT-5.4 |

**MIRA is 11th of 33, not 1st of 7.**

The report also asserts: *"No agent in the comparison achieves either a lower cost or a
higher score than MIRA, which therefore dominates all six alternatives on both criteria
simultaneously."* The qualifier "in the comparison" is doing all the work — **ResearchHarness
(DeepSeek-V4-Pro) scores higher (17.98) at lower cost ($0.40)** on the identical 12 tasks.
It strictly dominates MIRA and is absent from the comparison.

**In MIRA's defence:** holding the model fixed at GPT-5.4 is a legitimate and well-motivated
control — it isolates the harness from the model, which is exactly the right question if you
are evaluating an agent architecture. Within the GPT-5.4 cohort MIRA genuinely is first, by
1.93 points over ResearchClaw, and against the bare `ResearchHarness (GPT-5.4)` baseline
(10.56) its harness is worth **+6.95 points** — the largest harness contribution of any
GPT-5.4 system. That is the real, defensible claim. The report just doesn't phrase it that
way in the abstract.

Two caveats remain that the model control does not cover:
- **Domain selection is not neutral.** MIRA picked the three domains matching its own
  specialism (physical science, wired to a materials lab). Ordering changes across subsets:
  on all 40 tasks EvoScientist 0.1.1 (18.76) **beats** Codex CLI (18.42); on MIRA's 12 tasks
  it **loses** to ResearchClaw and sits only 0.46 above Codex CLI.
- **12 tasks is a small n.** With per-task scores spanning 0–56, a 1.9-point margin over
  12 tasks is not a wide gap, and no repeats are reported.

---

## Finding 2 — ARIS Codex costs points relative to bare Codex

ARIS is a skill library layered over Codex CLI / Claude Code. On ResearchClawBench that
layer is **negative**:

| Comparison (same model, GPT-5.4) | Win–Loss over 40 tasks | Mean Δ |
|:---|:---:|---:|
| ARIS Codex vs **Codex CLI** | **8–31** | **−4.84** |
| ARIS Codex vs ResearchHarness (GPT-5.4) | 15–25 | −1.70 |
| EvoScientist 0.1.1 vs ARIS Codex | 26–13 | +5.19 |

ARIS loses to the plain Codex CLI it wraps on **31 of 40 tasks**. It is 27th of 32 overall,
below the minimal ResearchHarness baseline. Its collapse is concentrated in the
analysis-heavy domains — Information 6.0 (vs Codex 17.0), Neuroscience 6.9, Math 11.4
(vs Codex 20.8) — while it holds up in Astronomy (21.3) and Physics (24.7).

Two honest caveats:
- ResearchClawBench's own agent registry lists ARIS as **"One-click launch is not yet
  supported"**; its entry is an *imported* run rather than one the harness launched. The
  configuration is therefore less controlled than the others.
- ARIS is explicitly optimised for a different objective. Its 86 skill directories (the catalog lists 82) target the
  *full paper lifecycle* — adversarial cross-model review, citation audits, integrity
  forensics, venue formatting. ResearchClawBench scores a single `report.md` against a
  published paper's rubric and explicitly does not reward length or process. An
  audit-and-review harness is close to unmeasurable here, and ARIS's sibling project
  (Anti-Autoresearch, 61 integrity signals) suggests its authors are aiming at
  trustworthiness rather than rubric coverage.

Still: if the question is "does this scaffold help an agent do research on RCB," the answer
for ARIS is measurably no.

---

## Finding 3 — EvoScientist has the strongest version-over-version gain in the field

| | 0.0.4 | 0.1.1 | Δ |
|:---|---:|---:|---:|
| Overall mean (40 tasks) | 15.47 | **18.76** | **+3.29** |
| Leaderboard rank | 22 | **10** | +12 |
| Best single task | 47.3 | **55.6** | +8.3 |
| Head-to-head | — | **21–18** | +3.30 mean |
| $/task | 1.19 | 4.08 | 3.4× |

Where the gain came from (per-domain mean):

| Domain | 0.0.4 | 0.1.1 | Δ |
|:---|---:|---:|---:|
| Information | 7.4 | 18.9 | **+11.5** |
| Physics | 26.3 | 35.0 | **+8.7** |
| Neuroscience | 5.3 | 11.4 | +6.1 |
| Chemistry | 4.4 | 9.9 | +5.5 |
| Energy | 24.0 | 19.9 | **−4.1** |

Two things stand out. The jump is real but **paid for**: 3.4× the cost per task, and it is the
most expensive GPT-5.4 agent on the board ($5.80/task on MIRA's subset — 8.7× MIRA's, as the
MIRA report correctly notes). And it is **not uniform** — Energy regressed by 4.1, so the
0.1.1 changes traded something away.

EvoScientist is also the only one of the three that reaches a top-3 single-task score
anywhere: **Physics_003 = 55.6**, one of only three scores above 50 in the entire benchmark.
Its head-to-head record against Codex CLI is losing (16–23) while its mean is higher
(+0.34), meaning its advantage comes from a few large wins rather than broad consistency —
a high-variance system.

---

## Architectural comparison

| | **EvoScientist** | **ARIS Codex** | **MIRA** |
|:---|:---|:---|:---|
| Shape | Python agent framework | Markdown skill library | Multi-agent squad + physical lab |
| Built on | LangChain / LangGraph / DeepAgents | Host coding agent (Claude Code, Codex, Cursor, …) | Proprietary; agent-teams pattern |
| Coordination | Subagents, MCP tools, persistent memory | 86 composable `SKILL.md` workflows (catalog lists 82) | Lead agent + members, shared task board, **mailbox** |
| Distinctive bet | Self-evolving skills/memory that accrete across runs | **Cross-model adversarial review** — executor and reviewer are different model families | **Manufactured disagreement** — members are assigned competing hypotheses and rewarded for refuting each other |
| Execution layer | Local / MCP tools | Local + remote GPU backends (vast, modal) | MIRA Compute (elastic cloud, 1→1000s of jobs) + **AI Materials Factory** (real synthesis and characterisation) |
| Memory | Memory base + skills | Research-wiki + audit trace | Persistent memory + maintained scientific wiki, "discovery episodes" |
| Human role | Human-*on*-the-loop | `human checkpoint: false` by default | Not specified |
| Openness | Apache 2.0, `pip install EvoScientist` | MIT | Closed; hosted at mira.deepprinciple.com |

The three are betting on different bottlenecks:

- **EvoScientist** bets the bottleneck is **accumulated capability** — skills and memory that
  compound. That predicts gains over versions, which is exactly what the 0.0.4→0.1.1 jump
  shows.
- **ARIS** bets it is **self-deception** — an agent grading its own work. Hence a reviewer in
  a different model family, integrity forensics, and provisional-vs-accepted status. That
  bet is invisible to a rubric that only reads the final report.
- **MIRA** bets it is **premature convergence and the simulation-reality gap** — hence
  competing hypotheses with refutation as an objective, and a physical lab closing the loop.
  Neither of those is measurable on ResearchClawBench, which is dry-lab and single-shot.
  MIRA's benchmark result is arguably the *least* representative of what it is built for.

---

## What this says for AutoR

1. **Model choice dominates harness choice.** Six of the ten agents above MIRA on its own
   subset simply use a stronger model. Before tuning the harness, run on the best available
   model.
2. **The bare-harness baseline is the number that matters.** `ResearchHarness (GPT-5.4)` =
   10.56 on the 3-domain subset, 15.28 on all 40. Any AutoR result must be quoted against
   the same-model baseline, or it says nothing. ARIS is the cautionary case: a large,
   thoughtful scaffold that lands **below** the baseline.
3. **Report all 40 tasks.** Subset reporting is where every one of these comparisons gets
   soft. Ordering demonstrably flips between the 40-task and 12-task views.
4. **Cost belongs in the claim.** EvoScientist bought +3.29 points for 3.4× the cost.
   The leaderboard records `cost_usd` per run; there is no reason to omit it.
5. **AutoR's 8-stage pipeline is expensive for this benchmark.** RCB scores one
   `report.md` — it does not reward literature surveys, LaTeX packaging, or dissemination.
   Expect Stage 01 and Stage 08 to cost wall-clock and tokens for little rubric credit.
   Consider a stage subset for benchmark runs.
6. **A realistic target.** Beating the same-model bare baseline is the first bar; the
   GPT-5.4 cohort leader is MIRA's unverified 17.51 / ResearchClaw's verified 15.58 on
   the subset. Crossing 50 on any single task would put AutoR in a group of three.

---

## Reproducing this

```bash
curl -sL https://internscience.github.io/ResearchClawBench-Home/data/leaderboard.json -o leaderboard.json
# schema: {tasks: [40], agents: [32], scores: {agent: {task: {score, cost_usd, duration_seconds, model_display}}}}
```

MIRA's protocol: mean of the four task scores within each of Chemistry, Energy and Material,
then the unweighted mean of those three domain scores.

## Caveats

- Leaderboard entries are **best-of** per (task, agent) pair, not means over repeats. Agents
  with more attempts are flattered. Pass@5 data exists but covers only six ResearchHarness
  variants — none of the three systems here.
- Coverage differs: ARIS and both EvoScientist versions have all 40 tasks; several
  ResearchHarness variants have 33–39, so their means are over different task sets.
- MIRA's 17.51 could not be independently verified. Everything else here was recomputed
  from the published JSON.
- ARIS's leaderboard entry is an imported run, not one launched by the harness.
