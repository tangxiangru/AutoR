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
               [--stage-timeout SECONDS] [--max-attempts N]
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
| `--fake-operator` | off | Replace the real backend with a deterministic stub that fabricates a valid stage summary and the placeholder artifacts each stage gate requires, so a fake run completes all nine stages. Use this for smoke tests and for exercising the workflow without spending tokens. It does **not** produce real research artifacts — every placeholder says so in its own contents. |
| `--stage-timeout SECONDS` | `14400` (4 hours) | Wall-clock ceiling for a single stage attempt. Raise it for long training runs; a stage that exceeds it is treated as a failed attempt. |
| `--max-attempts N` | `5` | Attempts allowed per stage before AutoR escalates or auto-skips. Each retry re-runs the stage with the previous attempt's validation errors attached, so raising this trades wall-clock for a better chance of clearing the gates. |

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
| `--web-search {auto,gemini,native}` | `auto`, or the recorded mode when resuming | Which search path the operators use. `gemini` routes searches through the Gemini API's Google Search grounding via `tools/web_search.py`; `native` leaves the backend's own tool in charge; `auto` picks Gemini when it can actually run and falls back to native otherwise. |

Set `gemini` on deployments where the built-in `WebSearch` tool is disabled —
notably **Claude Code on Vertex AI** — otherwise Stage 01 has no way to search
and will either stall or fabricate citations. See
[ResearchClawBench → Web search](researchclawbench.md#web-search-on-deployments-where-websearch-is-disabled).

The mode is persisted in `run_config.json` and reconciled on resume, like every other
backend selection. The **mode** is stored, never the resolved backend: `auto` is a
question about the current environment, and freezing today's answer would make a
resumed run assert something about the deployment that may no longer be true. A run
recorded before this field existed reads as `auto`.

#### How the agent reaches it

With `--operator claude`, search is handed over as a **real MCP tool**,
`mcp__autor-search__web_search`, not as a prompt paragraph asking the agent to
remember to run a script. AutoR adds `--mcp-config` pointing at a config it writes
to `operator_state/mcp_config.json` inside the run, so the run records what tools
its agent was given, not only what it was told.

Two things follow from it being a tool rather than an instruction:

- **The model reaches for it.** A tool in the tool list competes far better than a
  paragraph in a long prompt.
- **Every search is legible in the trace.** `logs_raw.jsonl` shows a named call with
  structured arguments, instead of an opaque shell command indistinguishable from
  the hundreds of others a stage runs.

A failed or ungrounded search comes back as an MCP tool *error* rather than a
protocol error, so the model can read the reason and retry instead of the call
simply ending.

`--strict-mcp-config` is deliberately **not** passed: that would also drop whatever
MCP servers you have configured for your own environment.

`--operator codex` gets the shell command instead, which remains the documented
fallback and is what `tools/web_search.py` is for.

#### What "can actually run" means

Injecting the search block tells every stage prompt that the built-in `WebSearch`
tool is disabled and `tools/web_search.py` is the replacement. That is a promise,
and credentials alone do not keep it. Three things are checked:

| Precondition | Why credentials are not enough |
| --- | --- |
| A Gemini backend | An API key, or Vertex ADC plus a project. |
| `google-genai` importable | Not a default dependency. The Vertex probe uses `google.auth`, a **different distribution** that can be installed without it. |
| The sandbox permits egress | `--operator codex` with `read-only` or `workspace-write` (the default) restricts outbound network access, so the search subprocess cannot reach Gemini. |

`auto` falls back to native search if any of them fails, and says which one at
startup. `--web-search gemini` **refuses to start** when the backend or the SDK
is missing — you asked for a tool that provably cannot work, and continuing means
Stage 01 burns its retry budget on a dead command before falling back to memory.
The sandbox case only warns, because it is inferred from the requested mode rather
than observed.

The advertised command names AutoR's own interpreter (`sys.executable`), not a
bare `python3` — otherwise the interpreter checked for `google-genai` and the one
that runs the script need not be the same.

### Output format

| Flag | Default | Description |
| --- | --- | --- |
| `--output-format {markdown,md,latex,tex}` | `markdown` | Stage 07's deliverable. `markdown` writes `workspace/report/report.md` plus PNG figures under `workspace/report/images/`, which is the artifact automated research benchmarks score. `latex` keeps the submission-oriented paper package: `main.tex`, `sections/*.tex`, a bibliography, and a compiled PDF. Persisted in `run_config.json` and preserved on resume. |

The two modes differ in which Stage 07 prompt is loaded, which artifacts the
stage gate requires, and whether a `paper_package/` bundle is produced after
approval. See [Stage Contract](stage-contract.md#artifact-requirements).

### Review panel

| Flag | Default | Description |
| --- | --- | --- |
| `--review-panel` | off | Replace the single reviewer agent with a deliberating panel: independent round, cross-examination on disagreement, then a chair synthesis. Implies `--approval-mode agent`. |
| `--panel-roles ROLE...` | all five | Seat only these roles, in this order: `pi`, `domain`, `method`, `repro`, `skeptic`. The first seat chairs unless `pi` is present. An unknown name is an error. |
| `--panel-rounds N` | `2` | Maximum deliberation rounds. Round 1 is always independent; later rounds run only on disagreement. |
| `--panel-models ROLE=MODEL...` | — | Assign a model per seat, as `role=model` or `role=backend:model` (`pi=opus skeptic=codex:default`). Heterogeneity is the lever with the best evidence behind it. |
| `--persona PATH` | — | Markdown description of the researcher the panel stands in for, injected into every seat so they hold one consistent bar. |

A blocking objection from any member cannot be approved over — the chair's approval is
converted to a refinement in code. Each run also writes
`workspace/reviews/panel/panel_effect.json`, comparing the panel against its own single-pass
baseline so it can report that it did not earn its cost. Full description, including the
pre-registered evidence against multi-agent deliberation, in [Review Panel](review-panel.md).

### Ideation panel

| Flag | Default | Description |
| --- | --- | --- |
| `--ideation-panel` | off | Widen Stage 02's hypotheses with proposers working from distinct lenses. Candidates are deduplicated, scored, and injected as material. It decides nothing. |
| `--ideation-lenses LENS...` | all five | Seat only these lenses: `mechanism`, `contrarian`, `adjacent`, `null`, `regime`. |
| `--ideation-models LENS=MODEL...` | - | Assign a model per lens, as `lens=model` or `lens=backend:model`. |
| `--ideas-per-proposer N` | `2` | Candidates each proposer may return. |

The pool records how much the proposers beyond the first actually added, so a run can report
that it widened nothing. Full description in [Ideation Panel](ideation-panel.md).

### Stopping early

| Flag | Default | Description |
| --- | --- | --- |
| `--final-stage STAGE` | run every stage | Stop after this stage slug or number (`07_writing`, `7`). Useful when only the report or manuscript is wanted and the dissemination package is not. `rcb_agent.py` defaults this to `07_writing`. |

Combining it with `--redo-stage`/`--rollback-stage` that start *after* it is an error rather
than a silently empty run.

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

### Stage graph and self-improvement

All of these are off by default. See [Recursive Self-Improvement](self-improvement.md)
for the mechanism and the reasoning behind each refusal.

| Flag | Default | Description |
| --- | --- | --- |
| `--stage-graph {linear,adaptive}` | `linear` | How the run moves between stages. `linear` is one edge out of each node, which is the sequence AutoR has always run. `adaptive` adds ten backward moves, so an analysis that exposes a design flaw can send the run to Stage 03 instead of writing up around it. The move into Stage 07 is guarded on every hypothesis having a verdict. Preserved on resume. |
| `--routing {off,auto,agent}` | `off` | Who chooses the move out of a completed stage. `off` always takes the graph's default edge. `auto` asks the backend wherever more than one move is live — on a linear graph that is never, so it costs nothing there. `agent` asks at every node. AutoR decides which moves are available by evaluating guards against artifacts on disk; the backend only chooses among those, and a choice outside the menu falls back to the forward edge. Preserved on resume. |
| `--graph-max-steps N` | `20` | Stage executions allowed in one walk. Only bites in adaptive mode; a linear walk cannot exceed eight. |
| `--graph-max-visits N` | `3` | Times one stage may be entered. A revisit is a productive move; the fourth entry into the same stage is a loop. |
| `--evolve` | off | Score each valid stage draft against a rigour rubric read off disk, then spend further rounds targeting the criteria that lost points. The best-scoring draft is promoted; a round that scores worse is reverted. A round that changes a hypothesis verdict is rejected outright. A revision a human asked for always stands. |
| `--evolve-rounds N` | `3` with `--evolve` | Self-improvement rounds per stage. Implies `--evolve` when above zero. Budgeted separately from `--max-attempts`, which bounds a stage that is *failing* rather than one being improved. Rounds also stop after two consecutive rounds with no gain. Preserved on resume. |
| `--evolve-stages STAGE [STAGE ...]` | all | Restrict self-improvement to these stage slugs or numbers, e.g. `06_analysis` or `5 6 7`. |
| `--archive PATH` | — | Directory holding the cross-run topology archive. AutoR records this run's route and measured fitness there, compares each edge against runs that reached the same node and did not take it, and samples the topology it runs from what the archive has learned. Requires `--evolve`, which is what produces the fitness. A learned prior only reorders which move is preferred; it can never open a guarded edge. |
| `--archive-report` | off | Print what the archive at `--archive` has learned, and exit. |

### Optional enhancements

| Flag | Default | Description |
| --- | --- | --- |
| `--research-diagram` | off | After Stage 07, generate a method illustration with the Gemini API and inject it into the report — `report.md` in markdown mode, `method.tex` in latex mode. Requires `pip install google-genai pyyaml` and a Gemini API key. If the SDK or key is missing, the diagram step prints a failure line and the run continues unaffected. See [Configuration → Diagram generation](configuration.md#diagram-generation-optional). |

### Reliability

The Gemini call retries and times out. Stage 01 issues dozens of searches over
hours, and the SDK's defaults are one attempt and no timeout, so a single `429`
killed a search outright and a hung connection could burn the whole
`--stage-timeout` (4 hours by default).

| | Value |
| --- | --- |
| Request timeout | 120 s |
| Attempts | 5, exponential backoff from 2 s to 60 s, covering 408 / 429 / 5xx |

Both come from the SDK's own `HttpOptions`; they were simply never switched on.
An SDK too old to accept them degrades to a single attempt rather than failing.

The optional `configs/diagram_config.yaml` is read defensively: it sits on the
startup path of every run, `pyyaml` is optional, and the file is hand-edited. A
missing package, an unreadable file, or malformed YAML prints a warning to
stderr and reports no key, rather than raising out of `main()` before the banner.
An API key in the environment short-circuits the file entirely.

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

A stage gets at most `--max-attempts` attempts (default `MAX_STAGE_ATTEMPTS`, 5, in
[`src/utils.py`](../src/utils.py))
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
                    [--stage-timeout SECONDS] [--max-attempts N]
                    [--max-auto-skips N]
                    [--intake] [--web-search {auto,gemini,native}]
                    [--no-synthesis] [--export-only] [--fake-operator]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--workspace PATH` | `.` | Benchmark workspace. The harness runs the agent with this as its working directory, so the default is usually right. |
| `--prompt TEXT` | — | Benchmark instructions as a literal string. This is what the harness's `<PROMPT>` placeholder expands to. |
| `--prompt-file PATH` | `<workspace>/INSTRUCTIONS.md` | Read the instructions from a file instead. |
| `--stage-timeout SECONDS` | `14400` | The benchmark harness imposes no timeout of its own — neither the UI runner nor the batch CLI puts one on the agent subprocess — so this is the only thing that can cut a stage short. |
| `--max-attempts N` | `8` | Higher than `main.py`'s default. An exhausted stage is auto-skipped, and a skipped stage costs real score, so the extra retries are worth their wall-clock. |
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
| `--json` | off | Emit `{query, model, backend, answer, grounded, citable_source_count, results[]}` instead of markdown, each result being `{title, url, citable, supported_claims[]}`. |
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

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The search returned at least one citable source. |
| `2` | The search completed but nothing citable came back — an answer with no resolvable source behind it. Retry with a different query; do not cite the answer. |
| `1` | The search could not be performed at all. The reason is on stderr. |

`2` is distinct from `1` on purpose: an ungrounded answer is not a broken tool, but
exiting `0` for it would make it indistinguishable from a real result to anything
reading only `$?`. The same signal is the `grounded` field in `--json`.

### `supported_claims` is not page text

Each result carries `supported_claims`: sentences from **Gemini's own answer** that the
source was cited in support of. Grounding asserts that a source supports a claim; it
never asserts that the page contains that sentence. The markdown renders them as a
labelled bullet list rather than a blockquote for exactly this reason — a blockquote
under a source link reads as a quotation, which is how a real paper acquires a sentence
it never contained.

To quote a source, fetch it and quote what it says.
