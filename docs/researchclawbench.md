# Running AutoR on ResearchClawBench

[ResearchClawBench](https://github.com/InternScience/ResearchClawBench) evaluates whether an
agent can conduct research end to end: it hands the agent a workspace of raw data and
reference papers, lets it work unsupervised, and then scores the resulting
`report/report.md` against the original published paper with a multimodal LLM judge.

AutoR runs it through `rcb_agent.py`. No human is involved at any point — the approval gate
is a reviewer agent (a second Claude Code instance), and every remaining terminal prompt is
a hard error rather than a hang.

---

## Quick start

```bash
# 1. Point ResearchClawBench at AutoR by adding this entry to evaluation/agents.json.
# 2. Restart the ResearchClawBench server, pick "AutoR", hit Start Run.
```

```json
{
  "autor": {
    "label": "AutoR",
    "icon": "A",
    "logo": "/static/logos/anthropic.svg",
    "cmd": "python3 /abs/path/to/AutoR/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT>"
  }
}
```

The harness substitutes `<WORKSPACE>` with the absolute workspace path and `<PROMPT>` with
the contents of the generated `INSTRUCTIONS.md`. Both flags are optional when running by
hand: the workspace defaults to the current directory (which is what the harness sets it
to) and the instructions default to `<workspace>/INSTRUCTIONS.md`.

Run one task manually:

```bash
cd /path/to/ResearchClawBench
python3 -m evaluation            # start the UI, or build a workspace yourself

cd workspaces/Astronomy_000_20260806_015140
python3 /abs/path/to/AutoR/rcb_agent.py
```

---

## What the adapter does

### 1. Removes the human

| Interaction point | Before | Now |
|:---|:---|:---|
| "Do you have existing resources to include?" | Blocked on stdin **even with `--full-auto`** | Never asked unattended |
| Intake clarification Q&A | Reviewer agent answers (already automatic) | unchanged |
| Stage approval gate | Reviewer agent decides (already automatic) | unchanged |
| Stage exhausted its retries | Blocked on a TTY, aborted the whole run otherwise | Auto-skips, bounded by `--max-auto-skips` |
| Any prompt missed by the above | Would hang the benchmark silently | Raises `UnattendedInputError` |

That last row is the important one. Unattended mode does not merely avoid known prompts —
`TerminalUI` refuses to read stdin at all, so a future prompt added anywhere in the codebase
fails loudly on the first run instead of hanging a benchmark job for hours.

### 2. Bridges the output contract

AutoR produces a run tree with a LaTeX paper package; ResearchClawBench reads four paths
inside the workspace. After the pipeline finishes — **whether or not it succeeded** — the
adapter exports:

| Benchmark path | Source |
|:---|:---|
| `report/report.md` | see below |
| `report/images/*.png` | `workspace/figures`, `writing`, `results`, `artifacts` (PNG only) |
| `code/` | `workspace/code` |
| `outputs/` | `workspace/results` and `workspace/notes` |

The report comes from the first of three paths that yields real content:

1. **`agent`** — Stage 07 wrote `report/report.md` itself. The goal contract injected into
   every stage prompt names the exact path, so this is the normal case.
2. **`synthesized`** — one extra operator call converts the approved artifacts into the
   benchmark's markdown format.
3. **`fallback`** — pure-Python assembly from the approved stage summaries, with any
   auto-skipped stages named explicitly.

A partial report scores better than no report, so a crashed or incomplete pipeline still
exports everything it produced. The exit code tracks whether a report reached the harness,
not whether every stage was approved.

### 3. Streams progress

`rcb_agent.py` writes JSON lines to stdout, which the harness captures into
`_agent_output.jsonl`. The first line carries the model name so the run browser can display
it.

---

## Web search on deployments where `WebSearch` is disabled

Stage 01 (Literature Survey) needs real search. Some Claude Code deployments — notably
**Claude Code on Vertex AI** — ship with the built-in `WebSearch` tool disabled, which
quietly guts that stage: the agent cannot search, so it either stalls or invents citations.

AutoR ships a replacement backed by the Gemini API's Google Search grounding:

```bash
export GEMINI_API_KEY=...      # or GOOGLE_API_KEY, or configs/diagram_config.yaml

python3 tools/web_search.py "black hole superradiance constraints"
python3 tools/web_search.py "diffusion model scaling laws" --json --max-results 8
```

Both `main.py` and `rcb_agent.py` take `--web-search`:

| Value | Behaviour |
|:---|:---|
| `auto` (default) | Gemini when a key is configured, native search otherwise |
| `gemini` | Always Gemini. Use this where `WebSearch` is blocked. |
| `native` | Leave the backend's own search tool in charge |

When Gemini search is active, a `# Web Search Capability` block is injected into every stage
prompt telling the operator that `WebSearch` is disabled, how to call the replacement, and
that every citation must come from a URL the tool actually returned. `auto` degrades to
native rather than advertising a tool that would fail on first use.

The search model defaults to `gemini-2.5-flash` and is overridable with
`AUTOR_WEB_SEARCH_MODEL` or `GEMINI_MODEL`.

---

## Options

```
--workspace PATH        Benchmark workspace. Defaults to the current directory.
--prompt TEXT           Instructions as a literal string (this is what <PROMPT> expands to).
--prompt-file PATH      Instructions from a file. Defaults to <workspace>/INSTRUCTIONS.md.

--operator {claude,codex}       Execution backend. Default: claude.
--model NAME                    Execution model. Default: the backend default.
--review-operator {claude,codex}  Reviewer backend. Default: the execution backend.
--review-model NAME             Reviewer model. Default: the backend default.

--stage-timeout SECONDS  Per stage attempt. Default: 3600, lower than AutoR's interactive
                         default because benchmark runs are wall-clock bound.
--max-auto-skips N       Stages that may be auto-skipped before aborting. Default: 3.
--intake                 Run the intake stage. Off by default: the benchmark instructions
                         are already a complete task specification.
--web-search {auto,gemini,native}
--no-synthesis           Skip the operator-backed report synthesis pass.
--export-only            Re-export the latest run without re-running the pipeline. Use this
                         to recover deliverables from an interrupted job.
--fake-operator          Smoke-test the adapter without touching a real backend.
```

### Layout inside the workspace

```
<workspace>/
├── INSTRUCTIONS.md        # written by the harness
├── data/                  # read-only input, never modified
├── related_work/          # read-only references, never modified
├── code/                  # exported
├── outputs/               # exported
├── report/
│   ├── report.md          # the scored deliverable
│   └── images/            # PNG figures
└── .autor/                # the full AutoR run tree, kept for inspection
    └── <run_id>/
```

Everything AutoR needs lives under `.autor/`, so a workspace stays self-contained and a run
can be inspected or resumed after the fact.

---

## How other agents score

[researchclawbench-landscape.md](researchclawbench-landscape.md) works through the public
leaderboard: where EvoScientist, ARIS Codex and MIRA actually land, which of their reported
numbers reproduce, and what the same-model baseline is that any AutoR result has to be
quoted against. Two findings worth knowing before you run:

- **Model choice dominates harness choice.** Most agents above any given harness on the
  board simply use a stronger model. Quote AutoR against the same-model baseline or the
  number says nothing.
- **A scaffold can be negative.** ARIS Codex, a large skill library over Codex CLI, loses to
  the plain Codex CLI it wraps on 31 of 40 tasks.

---

## Smoke test

```bash
cd /path/to/ResearchClawBench
python3 -c "
import sys; sys.path.insert(0, '.')
from evaluation.run_task import TaskRunner
r = TaskRunner('Astronomy_000', agent_cmd='true', agent_name='autor')
r.setup_workspace()
print(r.workspace.resolve())
"

cd workspaces/Astronomy_000_*
python3 /abs/path/to/AutoR/rcb_agent.py --fake-operator --no-synthesis --max-auto-skips 9
```

This exercises the whole path — unattended pipeline, auto-skip recovery, export — without
spending tokens. Expect exit code 0 and a `report/report.md` assembled by the fallback.
