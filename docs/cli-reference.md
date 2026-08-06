# CLI Reference

Complete reference for AutoR's entry points:

- `python main.py` — the terminal research workflow ([source](../main.py))
- `python studio.py` — the local browser workspace
  ([source](../src/backend/studio_http.py))
- `python rcb_agent.py` — the unattended ResearchClawBench agent
  ([source](../rcb_agent.py))
- `python tools/web_search.py` — Gemini-backed web search
  ([source](../src/web_search.py))

For a task-oriented introduction, read the [English Guide](tutorial_en.md)
instead. This page is the exhaustive list.

---

## `main.py`

```
python main.py [--goal GOAL] [--goal-file PATH] [--runs-dir DIR] [--fake-operator]
               [--model MODEL] [--operator {claude,codex}]
               [--codex-sandbox {read-only,workspace-write,danger-full-access}]
               [--approval-mode {manual,agent}] [--full-auto]
               [--unattended] [--max-auto-skips N]
               [--review-operator {claude,codex}] [--review-model MODEL]
               [--web-search {auto,gemini,native}]
               [--venue VENUE] [--resume-run RUN_ID] [--redo-stage STAGE]
               [--rollback-stage STAGE] [--resources PATH [PATH ...]]
               [--skip-intake] [--research-diagram]
               [--project-root PATH] [--paper-corpus PATH]
               [--stage-timeout SECONDS]
```

### Goal and run location

| Flag | Default | Description |
| --- | --- | --- |
| `--goal GOAL` | prompted interactively | The research goal. If omitted, AutoR reads a multi-line goal from stdin and stops at the first empty line. An empty goal is an error. Unattended runs cannot be prompted, so one of `--goal` or `--goal-file` is required there. |
| `--goal-file PATH` | — | Read the goal from a file instead. Mutually exclusive with `--goal`. Use this when the goal is too long to pass as a shell argument. |
| `--runs-dir DIR` | `runs` | Where run directories are created. Resolved **relative to the repository root**, not the current working directory. Point this at a large disk for heavy experiments. |

### Execution backend

| Flag | Default | Description |
| --- | --- | --- |
| `--operator {claude,codex}` | `claude` | Which coding-agent CLI executes each stage. On resume, the existing run's backend is preserved unless you pass this flag. |
| `--model MODEL` | `sonnet` for Claude, `default` for Codex | Model alias or full model name for the execution backend. On resume, the run's recorded model is reused unless you pass this flag or switch backends. |
| `--codex-sandbox MODE` | `workspace-write` | Codex CLI sandbox mode. Only meaningful for `--operator codex`. See [the sandbox modes](#codex-sandbox-modes) below. Persisted in `run_config.json` and preserved on resume. |
| `--fake-operator` | off | Replace the real backend with a deterministic stub that fabricates a valid stage summary. Use this for smoke tests and for exercising the workflow without spending tokens. It does **not** produce real research artifacts. |
| `--stage-timeout SECONDS` | `14400` (4 hours) | Wall-clock ceiling for a single stage attempt. Raise it for long training runs; a stage that exceeds it is treated as a failed attempt. |

#### Codex sandbox modes

Defined in [`CODEX_SANDBOX_CHOICES`](../src/utils.py).

| Mode | Effect |
| --- | --- |
| `read-only` | Codex may read the workspace but not write. Rarely useful for a research run, which must produce artifacts. |
| `workspace-write` | **Default.** Codex may read and write inside the run workspace. This is the right setting for almost everything. |
| `danger-full-access` | No sandbox. Codex may execute arbitrary local commands, SSH to remote hosts, and reach external GPUs. Choose this only when a verified remote experiment genuinely needs it, and only for a goal you trust. See [SECURITY.md](../SECURITY.md). |

### Approval control

By default a human approves every stage boundary. `--full-auto` swaps that
gate for a strict reviewer agent; it does **not** change the stage pipeline.

| Flag | Default | Description |
| --- | --- | --- |
| `--approval-mode {manual,agent}` | `manual` | Who approves a stage. `manual` shows the six-option review menu. `agent` delegates to an automated reviewer. Preserved on resume. |
| `--full-auto` | off | Shortcut for `--approval-mode agent` plus `--unattended`. |
| `--review-operator {claude,codex}` | same as `--operator` | Backend used by the automated reviewer. Using a different backend than the executor gives the review some independence. |
| `--review-model MODEL` | backend default | Model for the reviewer. A stronger reviewer model than the executor model is a reasonable configuration. |

Manual review is still the recommended mode for research you intend to
publish. `agent` mode exists for unattended sweeps, overnight runs, and
automated dry runs.

### Unattended execution

Replacing the human approval gate is not by itself enough to make a run
unattended: a handful of prompts sit outside that gate. `--unattended` closes
them, and is implied by `--full-auto` and by `--approval-mode agent`.

| Flag | Default | Description |
| --- | --- | --- |
| `--unattended` | off (implied by `--full-auto`) | Never block on terminal input. The resource prompt is skipped even on a TTY, and any interactive prompt that is still reachable raises `UnattendedInputError` instead of waiting. |
| `--max-auto-skips N` | `3` | How many stages may be auto-skipped after exhausting their retry budget before the run aborts. Only applies unattended. |

Two behaviours change unattended:

- **The resource prompt is never shown.** Pass resources with `--resources`.
  Previously this prompt appeared whenever stdin was a TTY, even with
  `--full-auto` — which silently hung any harness that handed AutoR the
  launching terminal's stdin.
- **An exhausted stage is auto-skipped, not fatal.** Attended runs offer a
  skip/rollback/abort menu; unattended runs take the skip, promote an explicit
  skip summary so downstream stages know the work is missing, and continue
  until the `--max-auto-skips` budget runs out. Both outcomes are recorded in
  `logs.txt` as `unattended_auto_skip` and `unattended_abort`.

Prompts becoming hard errors is deliberate. It means a prompt added anywhere
in the codebase later fails on its first unattended run instead of hanging an
overnight job.

### Web search

| Flag | Default | Description |
| --- | --- | --- |
| `--web-search {auto,gemini,native}` | `auto` | Which search path the operators use. `gemini` routes searches through the Gemini API's Google Search grounding via `tools/web_search.py`; `native` leaves the backend's own tool in charge; `auto` picks Gemini when a Gemini API key is configured and falls back to native otherwise. |

Set `gemini` on deployments where the built-in `WebSearch` tool is disabled —
notably **Claude Code on Vertex AI** — otherwise Stage 01 has no way to search
and will either stall or fabricate citations. See
[ResearchClawBench → Web search](researchclawbench.md#web-search-on-deployments-where-websearch-is-disabled).

### Writing venue

| Flag | Default | Description |
| --- | --- | --- |
| `--venue VENUE` | `neurips_2025` | Target venue profile for Stage 07 writing. Accepts a registry key (`iclr_2026`), a display name (`ICLR 2026`), or a style package name (`iclr2026_conference`); matching ignores case, spaces, and punctuation. An unknown venue raises `Unknown venue: <value>`. Preserved on resume. |

The full list of venue keys and their metadata is in
[Configuration → Venue registry](configuration.md#venue-registry).

### Resuming, redoing, rolling back

| Flag | Default | Description |
| --- | --- | --- |
| `--resume-run RUN_ID` | — | Continue an existing run under `--runs-dir`. Pass `latest` to resume the most recent run directory (lexicographic order over the timestamped directory names). |
| `--redo-stage STAGE` | — | With `--resume-run`: re-run this stage in place, keeping everything downstream untouched. Use it when the stage output was weak but the direction is right. |
| `--rollback-stage STAGE` | — | With `--resume-run`: return to this stage and mark every downstream stage stale before continuing. Use it when a later stage proved an earlier decision wrong. |

`--redo-stage` and `--rollback-stage` are mutually exclusive; passing both
raises `--redo-stage and --rollback-stage are mutually exclusive.` Both accept
`03`, `3`, or `03_study_design`; an unrecognized value raises
`Unknown stage identifier: <value>`.

Neither flag does anything without `--resume-run`.

### Inputs and priming

| Flag | Default | Description |
| --- | --- | --- |
| `--resources PATH [PATH ...]` | — | Files or directories to ingest into the run before Stage 01: PDFs, code repositories, datasets, `.bib` files, notes. Each path is classified by type and copied into the matching workspace directory. Starting with resources is the single highest-leverage thing you can do for output quality. |
| `--skip-intake` | off | Skip Stage 00. **Also implied automatically when stdin is not a TTY**, which is why piped and CI invocations never block on the intake prompt. |
| `--project-root PATH` | — | Scan an existing project repository, infer how far it has already progressed, and recommend a re-entry stage. Use this instead of starting from zero on work you already have. |
| `--paper-corpus PATH` | — | Scan a directory of your own prior papers (PDF, LaTeX, BibTeX, notes) to build a researcher profile — topics, citation neighborhood, and writing style — that seeds downstream stages. |

### Optional enhancements

| Flag | Default | Description |
| --- | --- | --- |
| `--research-diagram` | off | After Stage 07, generate a method illustration with the Gemini API and inject it into the LaTeX paper. Requires `pip install google-genai pyyaml` and a Gemini API key. If the SDK or key is missing, the diagram step prints a failure line and the run continues unaffected. See [Configuration → Diagram generation](configuration.md#diagram-generation-optional). |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The workflow completed and the final stage was approved. |
| `1` | The workflow returned failure — aborted at a review menu, exhausted its attempts, or raised an exception (the message is printed to stderr as `Error: <detail>`). |
| `130` | Interrupted with Ctrl-C. Run state on disk stays valid; resume with `--resume-run latest`. |

### Interactive controls

Inside a run, the review menu takes `1`–`6` (see
[Stage Contract → Your Options](stage-contract.md#your-options)). Two extra
control commands are accepted where the UI offers a recovery prompt:

| Command | Effect |
| --- | --- |
| `/skip` | Skip the current stage and continue to the next one. |
| `/back <stage>` | Roll back to an earlier stage and mark downstream stages stale, e.g. `/back 01` or `/back 03_study_design`. |

Anything else is rejected with
`Unknown control command. Supported commands are '/skip' and '/back <stage>'.`

A stage gets at most `MAX_STAGE_ATTEMPTS` (5, in [`src/utils.py`](../src/utils.py))
attempts before AutoR stops and escalates to you.

### Examples

```bash
# First run, fully interactive
python main.py

# Explicit goal, primed with your own materials, targeting ICLR
python main.py \
  --goal "Does parameter-matched MoE-LoRA beat dense LoRA on instruction tuning?" \
  --resources ~/papers/moe_survey.pdf ~/refs.bib ~/data/alpaca_subset.jsonl \
  --venue iclr_2026

# Smoke test the whole pipeline with no backend and no tokens
python main.py --fake-operator --goal "Smoke test" --skip-intake

# Unattended overnight run with an independent reviewer
python main.py --full-auto \
  --operator codex --model default \
  --review-operator claude --review-model opus \
  --goal "..."

# A remote-GPU experiment that genuinely needs SSH
python main.py --operator codex --codex-sandbox danger-full-access --goal "..."

# Rework only the analysis stage of an existing run
python main.py --resume-run 20260329_210252 --redo-stage 06

# The study design was wrong; go back and invalidate everything after it
python main.py --resume-run 20260329_210252 --rollback-stage 03

# Continue where you left off, keeping every recorded setting
python main.py --resume-run latest

# Re-enter an existing project instead of starting over
python main.py --project-root ~/code/my-existing-project --goal "..."

# Long training runs: raise the per-attempt ceiling to 12 hours
python main.py --stage-timeout 43200 --goal "..."
```

---

## `studio.py`

Starts the local browser workspace over the same run directories.

```
python studio.py [--host HOST] [--port PORT] [--repo-root PATH]
                 [--runs-dir PATH] [--metadata-root PATH]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--host HOST` | `127.0.0.1` | Bind address. The server has no authentication; see the warning below before changing this. |
| `--port PORT` | `8000` | Bind port. |
| `--repo-root PATH` | `.` | Repository root. Used to locate `src/prompts/`, and to derive the defaults for the two paths below. |
| `--runs-dir PATH` | `<repo-root>/runs` | Run directory the Studio reads and writes. |
| `--metadata-root PATH` | `<repo-root>/.autor` | Where the Studio project index (`projects.json`) lives. Projects are Studio-only metadata; runs remain plain directories. |

```bash
python studio.py                                 # http://127.0.0.1:8000/studio/
python studio.py --port 8765
python studio.py --runs-dir /mnt/big-disk/runs
```

> **Binding beyond localhost.** `--host 0.0.0.0` exposes an unauthenticated
> API that can start agent runs and read every file under the runs directory.
> Only do this on a trusted network, and prefer an SSH tunnel
> (`ssh -L 8000:127.0.0.1:8000 host`) for remote access.

Studio pages, behaviour, and the full HTTP API are documented in
[studio.md](studio.md).

---

## `rcb_agent.py`

Runs AutoR unattended against a
[ResearchClawBench](https://github.com/InternScience/ResearchClawBench) workspace
and exports the benchmark's deliverables. Never reads stdin.

```
python rcb_agent.py [--workspace PATH] [--prompt TEXT | --prompt-file PATH]
                    [--operator {claude,codex}] [--model MODEL]
                    [--review-operator {claude,codex}] [--review-model MODEL]
                    [--codex-sandbox MODE] [--venue VENUE]
                    [--stage-timeout SECONDS] [--max-auto-skips N]
                    [--intake] [--web-search {auto,gemini,native}]
                    [--no-synthesis] [--export-only] [--fake-operator]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--workspace PATH` | `.` | Benchmark workspace. The harness runs the agent with this as its working directory, so the default is usually right. |
| `--prompt TEXT` | — | Benchmark instructions as a literal string. This is what the harness's `<PROMPT>` placeholder expands to. |
| `--prompt-file PATH` | `<workspace>/INSTRUCTIONS.md` | Read the instructions from a file instead. |
| `--stage-timeout SECONDS` | `3600` | Lower than `main.py`'s default, because benchmark runs are wall-clock bound. |
| `--intake` | off | Run Stage 00. Off by default: the benchmark instructions are already a complete task specification. |
| `--no-synthesis` | off | Skip the operator-backed report synthesis pass and use only the deterministic fallback. |
| `--export-only` | off | Re-export the most recent run in the workspace without re-running the pipeline. Use this to recover deliverables from an interrupted job. |

Every other flag mirrors its `main.py` counterpart.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | A report reached `<workspace>/report/report.md`. |
| `1` | No report was produced, or the adapter could not start. |

The exit code deliberately tracks the deliverable rather than pipeline
completion: ResearchClawBench scores the report, so a run that auto-skipped a
stage but still produced a substantive report is a success, and a "completed"
run with an empty report is not.

Full setup, the `agents.json` entry, and the output contract are in
[researchclawbench.md](researchclawbench.md).

---

## `tools/web_search.py`

Grounded web search backed by the Gemini API, for deployments where the coding
agent's built-in `WebSearch` tool is disabled.

```
python tools/web_search.py QUERY... [--json] [--model MODEL] [--max-results N]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--json` | off | Emit `{query, model, backend, answer, results[]}` instead of markdown. |
| `--model MODEL` | `gemini-2.5-flash` (API key) / `gemini-3.6-flash` (Vertex) | Overridable with `AUTOR_WEB_SEARCH_MODEL` or `GEMINI_MODEL`. |
| `--max-results N` | `10` | Maximum number of grounded sources to report. |
| `--no-resolve-urls` | off | Leave Vertex grounding redirects unresolved. Faster, but the source URLs are opaque stubs that cannot be cited. |

Two backends are supported and auto-detected:

- **Gemini Developer API** — key from `GOOGLE_API_KEY`, then `GEMINI_API_KEY`, then
  `configs/diagram_config.yaml`, the same order diagram generation uses.
- **Vertex AI** — Application Default Credentials plus a project from
  `AUTOR_VERTEX_PROJECT`, `GOOGLE_CLOUD_PROJECT`, or `ANTHROPIC_VERTEX_PROJECT_ID`, and a
  location from `AUTOR_VERTEX_LOCATION` or `GOOGLE_CLOUD_LOCATION` (default `global`).

An explicit API key wins; `AUTOR_WEB_SEARCH_BACKEND=vertex|api_key` forces the choice.
Exits `1` with the reason on stderr when a search cannot be performed.
