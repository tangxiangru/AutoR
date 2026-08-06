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

Stage 07 runs in **markdown mode** by default (`--output-format markdown`), so the report
the benchmark scores is the pipeline's own gate-checked deliverable rather than a
translation of one. AutoR writes it to `workspace/report/report.md` in the run tree; the
adapter copies it to the benchmark path. In `--output-format latex` Stage 07 produces the
submission-oriented paper package instead and the report is synthesized afterwards.

After the pipeline finishes — **whether or not it succeeded** — the adapter exports:

| Benchmark path | Source |
|:---|:---|
| `report/report.md` | see below |
| `report/images/*.png` | `workspace/report/images` first, then `figures`, `writing`, `results`, `artifacts` (PNG only, capped — see below) |
| `code/` | `workspace/code` |
| `outputs/` | `workspace/results` and `workspace/notes`, **images excluded** |

Run-tree figures under `report/images/` keep their filenames, because those are the names
`report.md` references. A same-named figure swept up from elsewhere is the one that gets
qualified.

#### The five image slots

This is where most of the score is. Across the 40 shipped tasks, 91 of 154 checklist items
are `type: image` and they carry **60.6% of total weight** (median 62%; images are the
majority of weight in 25 of 40 tasks). The scorer shows the judge at most five agent images
per item:

```python
for search_dir in [workspace / "outputs", workspace / "report"]:   # outputs first
    for ext in IMAGE_EXTENSIONS:
        images.extend(search_dir.rglob(f"*{ext}"))                 # filesystem order
...
for img in generated_images[:5]:
```

Two consequences drive the export:

1. **`outputs/` is drained before `report/`.** A diagnostic plot left in `workspace/results`
   would take a slot from a figure the report argues with, so images are excluded from the
   `outputs/` mirror entirely. The machine-readable results still go across.
2. **`rglob` order is filesystem order, not alphabetical.** Naming cannot influence which
   five survive. The only lever is publishing no more than five — so `collect_figures`
   enforces `MAX_REPORT_FIGURES`, picks by the report's own reference order, and prunes
   anything else already at the benchmark path. A figure the report references is never
   pruned; Stage 07's gate is what keeps a run from arriving over budget.

A sixth figure does not add a sixth chance to match. It randomises which five are seen.

#### Reference papers

Every task ships curated PDFs in `related_work/`. They are registered as run resources, so
they land in `workspace/literature/` where Stage 01 reads them, and each one is named
individually in the goal contract. Without this the literature survey searches the web and
cannot cite the very work it is reproducing.

#### Where the run stops

`--final-stage` defaults to `07_writing`. Stage 08 produces posters, slides, release notes
and readiness checklists that the judge never opens; the wall-clock is better spent on
analysis. Pass `--final-stage 08_dissemination` for the full workflow.

The report comes from the first of four paths that yields real content:

1. **`agent`** — something wrote `report/report.md` at the benchmark path directly. The goal
   contract injected into every stage prompt names the exact path.
2. **`stage`** — Stage 07 ran in markdown mode, so its gate-checked report already exists in
   the run tree and is promoted verbatim. **This is the normal case.**
3. **`synthesized`** — one extra operator call converts the approved artifacts into the
   benchmark's markdown format. This is what a `latex` run uses.
4. **`fallback`** — pure-Python assembly from the approved stage summaries, with any
   auto-skipped stages named explicitly. AutoR's own control-loop headings
   (`Your Options`, `Decision Ledger`, `Previously Approved Stage Summaries`) are stripped:
   a judge told to be skeptical reads them as an agent's run log, not as research.

A partial report scores better than no report, so a crashed or incomplete pipeline still
exports everything it produced. The exit code tracks whether a report reached the harness,
not whether every stage was approved.

#### What markdown mode changes inside the pipeline

| | `markdown` (default) | `latex` |
|:---|:---|:---|
| Stage 07 prompt | `src/prompts/07_writing_markdown.md` | `src/prompts/07_writing.md` |
| Deliverable | `workspace/report/report.md` | `main.tex` + `sections/*.tex` + compiled PDF |
| Figures | `workspace/report/images/*.png`, referenced as `images/<name>.png` | `workspace/figures`, `\includegraphics` |
| Triage artifact | `artifacts/report_review.json` | `artifacts/layout_review.json` |
| Also required | `citation_verification.json`, `self_review.json` | same, plus `build_log.txt` and a `.bib` |
| Figure budget | at most 5, all referenced | none |
| Post-approval | — | `writing/paper_package/` bundle |

The markdown gates are not "a file exists". Stage 07 fails and retries if `report.md` is
shorter than 1,200 characters, references no figures, still holds placeholder text, or
carries a figure reference that is absolute, remote, unrenderable, or points at a file that
is not there, or publishes more than five figures. A broken figure link is the expensive
defect here: the judge reads the prose promising a figure and is shown nothing.

### 3. Streams progress

`rcb_agent.py` writes JSON lines to stdout, which the harness captures into
`_agent_output.jsonl`. The first line carries the model name so the run browser can display
it.

---

## Web search on deployments where `WebSearch` is disabled

Stage 01 (Literature Survey) needs real search. Some Claude Code deployments — notably
**Claude Code on Vertex AI** — ship with the built-in `WebSearch` tool disabled, which
quietly guts that stage: the agent cannot search, so it either stalls or invents citations.

AutoR ships a replacement backed by Gemini's Google Search grounding. It reaches Gemini
two ways, and picks whichever is configured:

```bash
# Vertex AI (no API key needed) — the natural fit if you already run Claude Code on Vertex
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project        # or AUTOR_VERTEX_PROJECT

# or the Gemini Developer API
export GEMINI_API_KEY=...                       # or GOOGLE_API_KEY, or configs/diagram_config.yaml

python3 tools/web_search.py "black hole superradiance constraints"
python3 tools/web_search.py "diffusion model scaling laws" --json --max-results 8
```

| | Vertex AI | Gemini Developer API |
|:---|:---|:---|
| Auth | Application Default Credentials | API key |
| Project | `AUTOR_VERTEX_PROJECT`, `GOOGLE_CLOUD_PROJECT`, or `ANTHROPIC_VERTEX_PROJECT_ID` | — |
| Location | `AUTOR_VERTEX_LOCATION`, `GOOGLE_CLOUD_LOCATION`, default `global` | — |
| Default model | `gemini-3.6-flash` | `gemini-2.5-flash` |

An explicit API key wins over Vertex, because setting one is deliberate whereas the Vertex
project is often inherited from the host's Claude Code configuration. Force the choice with
`AUTOR_WEB_SEARCH_BACKEND=vertex|api_key`.

`ANTHROPIC_VERTEX_PROJECT_ID` is consulted last and on purpose: a box already running Claude
Code on Vertex has it set, and that is exactly the deployment where the built-in `WebSearch`
tool is disabled and this module is needed. On such a box `--web-search auto` just works
with no extra configuration.

**Grounding redirects.** Vertex returns citations as opaque
`vertexaisearch.cloud.google.com/...` stubs rather than source URLs. The tool follows each
one to its canonical URL (`https://arxiv.org/abs/2606.07591`) before reporting it, and
de-duplicates afterwards, since two stubs routinely resolve to the same page. A stub that
cannot be resolved is kept but labelled **unresolved redirect, not citable**, and the prompt
tells operators to treat it as a lead rather than a reference. `--no-resolve-urls` skips the
resolution step.

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
--output-format {markdown,md,latex,tex}
                         Stage 07's deliverable. Default: markdown, which writes
                         report/report.md directly. Use latex to produce the paper package
                         and leave the report to the synthesis step.
--final-stage STAGE      Stop after this stage. Default: 07_writing, because Stage 08
                         produces nothing the judge reads.
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
