# CLI Reference

The commands AutoR is meant to be run with, each with a section below:

| Command | What it is |
| --- | --- |
| `python main.py` | The terminal research workflow. ([source](../main.py)) |
| `python studio.py` | The local browser workspace. ([source](../src/backend/studio_http.py)) |
| `python rcb_agent.py` | The unattended ResearchClawBench agent. ([source](../rcb_agent.py)) |
| `python fs_agent.py` | The unattended FrontierScience-Research agent. ([source](../fs_agent.py)) |
| `python tools/web_search.py` | Gemini-backed web search. ([source](../src/web_search.py)) |
| `python tools/score_rcb_run.py` | Scores a finished benchmark workspace. ([source](../tools/score_rcb_run.py)) |
| `python tools/score_fs_run.py` | Scores one FrontierScience answer against its rubric. ([source](../tools/score_fs_run.py)) |
| `python tools/fs_trial.py` | Runs and reports a paired FrontierScience trial. ([source](../tools/fs_trial.py)) |
| `python tools/archive_sample_complexity.py` | How many runs the archive needs before it can steer. ([source](../tools/archive_sample_complexity.py)) |

Two further modules are executable and are deliberately not listed as commands,
because nothing expects a person to type them:
[`src/mcp_web_search.py`](../src/mcp_web_search.py) is the MCP stdio server the
Claude operator launches for itself (see [How the agent reaches
it](#how-the-agent-reaches-it)), and `docs/ui-design/generate_progress_docx.py`
regenerates one design document and needs `python-docx`.

Every flag on those commands is named below: `main.py`'s 61, `studio.py`'s 5,
`tools/web_search.py`'s 4, `tools/score_rcb_run.py`'s 9, `fs_agent.py`'s 31 and
`tools/score_fs_run.py`'s 13 each get their own table row; `rcb_agent.py`'s 37
are covered as the six that are its own plus the 31 it shares with `main.py`,
every one of the 31 spelled out by name; and `tools/fs_trial.py` is four
subcommands, one of which is a child process the dry run launches for itself.
`tools/archive_sample_complexity.py` has none.

Two of the synopsis blocks are **subsets** — the common flags — and say so
underneath: `main.py`'s and `rcb_agent.py`'s. The others are not. `studio.py`,
`tools/web_search.py`, `tools/score_rcb_run.py`, `fs_agent.py` and
`tools/score_fs_run.py` show every flag their command declares, and
`tools/archive_sample_complexity.py` has nothing to omit. Either way the tables
are the surface.

For a task-oriented introduction, read the [English Guide](tutorial_en.md)
instead.

---

## `main.py`

```
python main.py [--goal GOAL | --goal-file PATH] [--runs-dir DIR]
               [--operator {claude,codex}] [--model MODEL]
               [--rigor {fast,standard,thorough,max}]
               [--approval-mode {manual,agent}] [--full-auto] [--unattended]
               [--resources PATH [PATH ...]] [--venue VENUE]
               [--output-format {markdown,md,latex,tex}]
               [--resume-run RUN_ID] [--redo-stage STAGE] [--rollback-stage STAGE]
               [--final-stage STAGE] [--stage-timeout SECONDS] [--max-attempts N]
               [--fake-operator]
```

**That synopsis is a subset, not the surface.** `parse_args` declares 61 flags;
the 19 shown above are the ones a first run usually needs. Every one of the 61
has a row in the tables that follow, grouped by what it does, and
`python main.py --help` prints the same set in declaration order.

Four of them — `--effort-tiers`, `--deliberation`, `--ideation-panel` and
`--review-panel` — are `argparse.BooleanOptionalAction` switches with
`default=None`, which does not mean "off". It means *nobody said*, and
[`--rigor`](#rigor) then decides; `--rigor` itself defaults to `standard`, which
turns effort tiers **on**. Passing either direction of the switch overrides the
level. `--evolve` and `--archive-steer` are the same kind of switch but are not
rigor-controlled: their unset values are filled in by `normalize_walk_settings`,
from `DEFAULT_EVOLVE_MEASURE` (on) and `DEFAULT_ARCHIVE_STEER` (off). The
switches that behave this way are the ones `main.py` declares with
`action=argparse.BooleanOptionalAction`, and every one of them is declared
`default=None`.

### Goal and run location

| Flag | Default | Description |
| --- | --- | --- |
| `--goal GOAL` | prompted interactively | The research goal. If omitted, AutoR reads a multi-line goal from stdin, skipping leading blank lines and stopping at the first blank line *after* some text. An empty goal is an error (`Research goal cannot be empty.`). Unattended runs cannot be prompted, so one of `--goal` or `--goal-file` is required there. |
| `--goal-file PATH` | — | Read the goal from a file instead. Mutually exclusive with `--goal`. Use this when the goal is too long to pass as a shell argument. |
| `--runs-dir DIR` | `runs` | Where run directories are created. Resolved **relative to the repository root**, not the current working directory. Point this at a large disk for heavy experiments. |

### Execution backend

| Flag | Default | Description |
| --- | --- | --- |
| `--operator {claude,codex}` | `claude` | Which coding-agent CLI executes each stage. On resume, the existing run's backend is preserved unless you pass this flag. |
| `--model MODEL` | `sonnet` for Claude, `default` for Codex | Model alias or full model name for the execution backend. On resume, the run's recorded model is reused unless you pass this flag or switch backends. |
| `--codex-sandbox MODE` | `workspace-write` | Codex CLI sandbox mode. Only meaningful for `--operator codex`. See [the sandbox modes](#codex-sandbox-modes) below. Persisted in `run_config.json` and preserved on resume. |
| `--fake-operator` | off | Replace the real backend with a deterministic stub that fabricates a valid stage summary and the placeholder artifacts each stage gate requires, so a fake run completes all eight stages. Use this for smoke tests and for exercising the workflow without spending tokens. It does **not** produce real research artifacts — every placeholder says so in its own contents. |
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
them.

`resolve_unattended` returns true for **four** things, not one:

- `--unattended`
- `--full-auto`
- `--approval-mode agent`
- `--review-panel`

The last one has a consequence worth stating on its own. `--rigor` is resolved
*before* `resolve_unattended` runs, and `--rigor max` is the level that turns the
review panel on — so **`--rigor max` silently makes a run unattended**, with no
`--unattended` anywhere on the command line. If you want the panel and a human at
the gate, you cannot have both: there is no one left to answer the prompts,
which is the reasoning the function's own docstring gives.

| Flag | Default | Description |
| --- | --- | --- |
| `--unattended` | off (implied by `--full-auto`, `--approval-mode agent`, `--review-panel`, and therefore by `--rigor max`) | Never block on terminal input. The resource prompt is skipped even on a TTY, and any interactive prompt that is still reachable raises `UnattendedInputError` instead of waiting. |
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
- **A backward move spends the same pool, so the graph keeps part of it back.**
  On `--stage-graph adaptive` a revisit re-runs a stage and a re-run stage can
  exhaust, so `StageGraph.moves` withdraws every backward edge once what is left
  is down to `DELIVERY_RESERVE` — the unit the run needs to reach a deliverable
  instead of aborting at it. Only unattended: attended runs never spend the pool,
  so the manager declares no budget at all.

  The consequence at the bottom of the flag's range is worth knowing before you
  set it. `--max-auto-skips 1` (or `0`) puts an unattended run at the reserve
  before its first routing decision, so every backward edge is withdrawn for the
  whole run and `adaptive` walks forward only — the flag silently selects the
  topology. The default of 3 keeps them open until the *second* auto-skip is
  spent. Withdrawals are on the record per visit in `evolution/stage_graph.json`
  as `blocked` kind `budget`, so a run that degraded this way says so rather than
  looking like one that was never offered the move.

Prompts becoming hard errors is deliberate. It means a prompt added anywhere
in the codebase later fails on its first unattended run instead of hanging an
overnight job.

### Web search

| Flag | Default | Description |
| --- | --- | --- |
| `--web-search {auto,gemini,native,off}` | `auto`, or the recorded mode when resuming | Which search path the operators use. `gemini` routes searches through the Gemini API's Google Search grounding via `tools/web_search.py`; `native` leaves the backend's own tool in charge; `auto` picks Gemini when it can actually run and falls back to native otherwise; `off` offers no search tool at all and denies `WebSearch` and `WebFetch` to the Claude CLI. |

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
approval. See [Stage Contract](stage-contract.md#2-the-artifact-gate).

### Review panel

| Flag | Default | Description |
| --- | --- | --- |
| `--review-panel` / `--no-review-panel` | off at `fast`, `standard` and `thorough`; **on at `--rigor max`** | Replace the single reviewer agent with a deliberating panel: independent round, cross-examination on disagreement, then a chair synthesis. Implies `--approval-mode agent` **and** unattended — see [Unattended execution](#unattended-execution). |
| `--panel-roles ROLE...` | the default panel — `pi`, `domain`, `method`, `repro`, `skeptic` | Seat only these roles, in this order. `resolve_roles` accepts six keys, not five: the default panel above plus `reader`, the **Area Chair**, which is in `OPTIONAL_ROLES` rather than `DEFAULT_PANEL` and is seated only when you name it here — it is the one seat that reads the artifact as a document. The first seat chairs unless `pi` is present, so `--panel-roles reader domain` puts the Area Chair in the chair. An unknown name raises `Unknown panel role: <value>. Known roles: domain, method, pi, reader, repro, skeptic.` (`main.py --help` lists only the default five; the error message is the complete set.) |
| `--panel-rounds N` | `2` | Maximum deliberation rounds. Round 1 is always independent; later rounds run only on disagreement. |
| `--panel-models ROLE=MODEL...` | — | Assign a model per seat, as `role=model` or `role=backend:model` (`pi=opus skeptic=codex:default`). Heterogeneity is the lever with the best evidence behind it. |
| `--persona PATH` | — | Markdown description of the researcher the panel stands in for, injected into every seat so they hold one consistent bar. |
| `--cross-review {auto,gemini,off}` | `auto` | Independent second opinion on each approval, from a different model family. It can veto an approval it cannot defend and can never override a refusal, so it only makes the gate stricter. `auto` enables it when a Gemini backend is configured. Refused behind `--fake-operator` — see below. |
| `--cross-review-model MODEL` | `gemini-3.1-pro-preview` | Model for the cross-model reviewer (`DEFAULT_CROSS_REVIEW_MODEL`, `src/cross_reviewer.py`). |

> **Two things the cross-review flags still do not do.** They are live on both
> entry points now — `main.py` seats the reviewer through `create_cross_reviewer`
> — but neither value is recorded anywhere: `initialize_run_config` has no such
> key and `main.py` never dumps its argv, so a **resumed run re-decides the mode
> from whatever credentials are in the environment that day** rather than from
> what was asked for. And `_collect_review_decision` returns before
> `_apply_cross_review` whenever no automated reviewer is seated, so **under a
> manual gate the reviewer is built and nothing consults it**. Behind
> `--fake-operator` it is refused outright, so the audit is only ever exercised
> against a stubbed verdict. Tracked in [Framework → What has not been
> established](framework.md#7-what-has-not-been-established) and in the README's
> Limits section.

A blocking objection from any member cannot be approved over — the chair's approval is
converted to a refinement in code. Each run also writes
`workspace/reviews/panel/panel_effect.json`, comparing the panel against its own single-pass
baseline so it can report that it did not earn its cost. Full description, including the
pre-registered evidence against multi-agent deliberation, in [Review Panel](review-panel.md).

### Rigor

| Flag | Default | Description |
| --- | --- | --- |
| `--rigor {fast,standard,thorough,max}` | `standard` | How much optional machinery to run. One dial in place of four switches. |

`fast` nothing · `standard` effort tiers · `thorough` + crux deliberation and the ideation
panel · `max` + the review panel. The levels nest (`_LEVEL_FEATURES`), and every individual
switch below still works as an override in both directions (`--no-ideation-panel`,
`--review-panel`). Full description in [Rigor](rigor.md).

`--rigor max` has one effect that is not on the list: because it turns the review panel on,
and the review panel is one of the things `resolve_unattended` reads, `--rigor max` also
makes the run unattended. `--rigor max --no-review-panel` does not.

### Effort tiers

| Flag | Default | Description |
| --- | --- | --- |
| `--routine-model MODEL` | - | Model for routine-tier stages, keeping the strong model for the few steps whose output the rest of the run inherits. Requires `--effort-tiers`. |
| `--effort-tiers` / `--no-effort-tiers` | **on** (from `--rigor standard`, the default) | Run each stage as `routine` or `deliberative` instead of treating them alike. Routine gets a lean prompt, a single reviewer, and no escalation offer. Each stage declares what the next needs; a routine stage that fails twice is promoted automatically. Turn it off with `--no-effort-tiers` or `--rigor fast`. |

Under tiering, polish rounds — the run's most expensive setting — are withheld from routine stages entirely, so the same rounds land only where something is still undecided. Off means exactly the previous behaviour. Both directions of mis-spending are recorded in
`workspace/reviews/effort.json`. Full description in [Effort Tiers](effort-tiers.md).

### Crux deliberation

| Flag | Default | Description |
| --- | --- | --- |
| `--deliberation` / `--no-deliberation` | off at `fast` and `standard`; **on at `--rigor thorough` and `max`** | Let a stage stop and pull in a panel when it hits a genuine crux. The agent names the question, finishes with its working answer, and the resolution reaches the next pass. |
| `--max-deliberations N` | `3` | Cruxes a run may escalate. Scarcity is what makes "think hard here" mean anything. |
| `--deliberation-voices VOICE...` | all four | `theorist`, `empiricist`, `critic`, `pragmatist`. |
| `--deliberation-models VOICE=MODEL...` | - | Assign a model per voice. |

The ledger records whether the panel changed the agent's answer or merely confirmed it. Full
description in [Raising a Crux](deliberation.md).

### Ideation panel

| Flag | Default | Description |
| --- | --- | --- |
| `--ideation-panel` / `--no-ideation-panel` | off at `fast` and `standard`; **on at `--rigor thorough` and `max`** | Widen Stage 02's hypotheses with proposers working from distinct lenses. Candidates are deduplicated, scored, and injected as material. It decides nothing. |
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

On by default. See [Recursive Self-Improvement](self-improvement.md) for the
mechanism and the reasoning behind each refusal.

| Flag | Default | Description |
| --- | --- | --- |
| `--stage-graph {linear,adaptive}` | `adaptive` | How the run moves between stages. `adaptive` is the eight stages as a directed graph with backward moves: an analysis that exposes a design flaw sends the run back to Stage 03 instead of writing up around it, and the move into Stage 07 stays closed until every hypothesis carries a verdict. `linear` restores the strict sequence — the same graph with the backward edges removed. Preserved on resume. |
| `--routing {off,auto,agent}` | `auto` | Who chooses the move out of a completed stage. `auto` asks the backend only where more than one move is live, so a linear run never pays for it. `agent` asks at every node; `off` always takes the graph's default edge. AutoR decides which moves are available by evaluating guards against artifacts on disk; the backend only chooses among those, and a choice outside the menu falls back to the forward edge. Preserved on resume. |
| `--graph-max-steps N` | `20` | Stage executions allowed in one walk. Only bites in adaptive mode; a linear walk cannot exceed eight. |
| `--graph-max-visits N` | `3` | Times one stage may be entered. A revisit is a productive move; the fourth entry into the same stage is a loop. |
| `--evolve` / `--no-evolve` | on | Score every valid draft against a rigour rubric read off disk and run the champion ratchet: the best-scoring draft is promoted, not the last one, and a self-initiated round that scores worse is reverted. Costs nothing — the rubric never calls a backend. `--no-evolve` restores the old behaviour, where whichever draft came last was promoted, and in `resolve_walk_settings` it also sets the rounds budget to zero — the rounds are steered by the score, so without a score there is nothing to steer them with. Passing `--evolve-rounds` above zero in the same command reverses both. Preserved on resume. |
| `--evolve-rounds N` | `2` | Improvement rounds per stage beyond the first draft. This is the half that costs backend calls. A stage whose rubric has no shortfall worth acting on spends none of them, and a `--fake-operator` run spends none at all. Budgeted separately from `--max-attempts`, which bounds a stage that is failing rather than one being improved. `0` measures without polishing. Preserved on resume. |
| `--evolve-stages STAGE [...]` | all | Restrict improvement rounds to these stage slugs or numbers, e.g. `06_analysis` or `5 6 7`. |
| `--archive PATH` | `~/.autor/archive` | Where the cross-run archive lives. Each finished run records its route and measured fitness, and each edge is compared against runs that reached the same node and did not take it. Recording only. |
| `--no-archive` | off | Do not record this run in the archive. |
| `--archive-steer` / `--no-archive-steer` | **off** | Let the archive choose the topology this run uses, rather than only recording what it did. A run silently using a different topology from the one asked for is not a surprise a research tool gets to spring on anyone; turn this on once `--archive-report` shows the archive has something to say. A learned prior only reorders which move is preferred — it can never open a guarded edge. Preserved on resume. |
| `--archive-report` | off | Print what the archive has learned, and exit. On a fresh install this is an empty table, and that is the honest state rather than a bug: no real run has ever been recorded into one. See [what has and has not been measured](self-improvement.md#what-has-and-has-not-been-measured). |
| `--trial ID` | — | Tag this run as one arm of a paired trial. Two runs of the **same goal** sharing a `--trial` ID, with the same `--capability` and different `--arm` labels, become a pair; the statistic is the within-pair difference, which cancels goal difficulty. Requires `--capability` and `--arm` — a partial tag is refused, because a run tagged with only some of them can never be paired. |
| `--capability NAME` | — | What the trial is testing, e.g. `effort_tiers`. Runs pair only within one capability. |
| `--arm LABEL` | — | Which side of the pair, e.g. `off` / `on`. `off`, `control`, `baseline` and `0` are recognised as the control when the report has to guess. |
| `--trial-report` | off | Print what the paired trials show, and exit: mean within-pair difference, a two-sided sign-flip p (enumerated exactly up to eighteen pairs, a seeded sample of sign assignments above that), the smallest p the estimator that ran could have produced, and the per-criterion decomposition. See [Recursive Self-Improvement](self-improvement.md#5-paired-trials--does-any-of-this-help). No trial has ever completed: the last attempt, on 2026-08-11, recorded zero runs against a quota wall. |
| `--max-rounds N` | `1` | How many times Stages 03-06 may run. A round ends when Stage 06 records `converged`, `refine_design`, `new_hypothesis` or `abandon`. The default keeps the single-pass behaviour: the decision is still recorded, so a one-round run says whether it converged or merely stopped, but a round that asks to go back is recorded with `acted_on: false` and the run continues. Raise it to let a refuted hypothesis lead to a second round. |

### Optional enhancements

| Flag | Default | Description |
| --- | --- | --- |
| `--research-diagram` | off | After Stage 07, generate a method illustration with the Gemini API and inject it into the report — `report.md` in markdown mode, `method.tex` in latex mode. Requires `pip install google-genai pyyaml` and a Gemini API key. If the SDK or key is missing, the diagram step prints a failure line and the run continues unaffected. See [Configuration → Diagram generation](configuration.md#diagram-generation-optional). |

### Reliability

The Gemini **search** call retries and times out (`SEARCH_TIMEOUT_MS`,
`SEARCH_RETRY_ATTEMPTS` and the two delay bounds in `src/web_search.py`). Stage
01 issues dozens of searches over hours, and the SDK's defaults are one attempt
and no timeout, so a single `429` killed a search outright and a hung connection
could burn the whole `--stage-timeout` (4 hours by default).

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

A stage gets at most `--max-attempts` attempts (default `MAX_STAGE_ATTEMPTS`, 5,
in [`src/utils.py`](../src/utils.py)) before AutoR stops and escalates to you.

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
python rcb_agent.py [--workspace PATH] [--prompt TEXT] [--prompt-file PATH]
                    [--operator {claude,codex}] [--model MODEL]
                    [--review-operator {claude,codex}] [--review-model MODEL]
                    [--codex-sandbox MODE] [--venue VENUE]
                    [--rigor {fast,standard,thorough,max}]
                    [--output-format {markdown,md,latex,tex}] [--final-stage STAGE]
                    [--stage-timeout SECONDS] [--max-attempts N] [--max-auto-skips N]
                    [--intake] [--web-search {auto,gemini,native,off}]
                    [--no-synthesis] [--export-only] [--fake-operator]
```

Again a subset: `rcb_agent.py`'s own `parse_args` declares 37 flags.

### The six flags that are its own

| Flag | Default | Description |
| --- | --- | --- |
| `--workspace PATH` | `.` | Benchmark workspace. The harness runs the agent with this as its working directory, so the default is usually right. Run directories are created under `<workspace>/.autor/`, which is why there is no `--runs-dir`. |
| `--prompt TEXT` | — | Benchmark instructions as a literal string. This is what the harness's `<PROMPT>` placeholder expands to. |
| `--prompt-file PATH` | `<workspace>/INSTRUCTIONS.md` | Read the instructions from a file. Not mutually exclusive with `--prompt`: `resolve_instructions` takes `--prompt` when it is non-empty, then the first of `--prompt-file` and `<workspace>/INSTRUCTIONS.md` that exists and is non-empty. A `--prompt-file` that does not exist therefore falls through to the workspace default rather than failing. With none of the three available it raises `No benchmark instructions found.` |
| `--intake` | off | Run Stage 00. Off by default: the benchmark instructions are already a complete task specification. This is the inverse of `main.py`'s `--skip-intake`, not a copy of it. |
| `--no-synthesis` | off | Skip the operator-backed report synthesis pass and use only the deterministic fallback. |
| `--export-only` | off | Re-export the most recent run in the workspace without re-running the pipeline. Use this to recover deliverables from an interrupted job. |

### The 31 it shares, and where they diverge

The remaining 31 have the same names as `main.py`'s and, unless noted below, the
same defaults and the same meaning. All 31, by name:

| Group | Shared flags |
| --- | --- |
| Backend | `--operator`, `--model`, `--codex-sandbox`, `--fake-operator`, `--stage-timeout`, `--max-attempts` |
| Reviewer | `--review-operator`, `--review-model` |
| Unattended | `--max-auto-skips` |
| Web search | `--web-search` |
| Output and stopping | `--output-format`, `--venue`, `--final-stage` |
| Rigor dial | `--rigor` |
| Effort tiers | `--effort-tiers` / `--no-effort-tiers`, `--routine-model` |
| Crux deliberation | `--deliberation` / `--no-deliberation`, `--max-deliberations`, `--deliberation-voices`, `--deliberation-models` |
| Ideation panel | `--ideation-panel` / `--no-ideation-panel`, `--ideation-lenses`, `--ideation-models`, `--ideas-per-proposer` |
| Review panel | `--review-panel` / `--no-review-panel`, `--panel-roles`, `--panel-rounds`, `--panel-models`, `--persona`, `--cross-review`, `--cross-review-model` |

Read the `main.py` tables above for what each one does. Three of them differ in
kind rather than in default, and the two parsers are mirror images about it —
each declares a flag the other one honours and it does not:

- **`--cross-review` and `--cross-review-model` are live on both entry points.**
  `rcb_agent.py` and `main.py` both call `resolve_cross_reviewer` and hand the
  result to `ResearchManager` as `cross_reviewer`, so the second opinion
  described in [Review panel](#review-panel) runs on either. Defaults are the
  same: `auto`, and `gemini-3.1-pro-preview` for the model.
- **`--routine-model` is inert here and live on `main.py`.** It parses, and its
  `--help` text promises a cheaper model for routine-tier stages, but
  `args.routine_model` is read nowhere in `rcb_agent.py`: under `--effort-tiers`
  the adapter builds `EffortPlan(enabled=True)` and never constructs the second
  operator that `main.py` builds for the routine tier. Tiering still applies —
  lean prompts, one reviewer, no escalation offer — but every stage runs on
  `--model`.

Every remaining divergence is a default or a validation. Diffing the two
parsers' actions turns up four, and the last row below is the one behavioural
consequence of the adapter being unattended by construction:

| Flag | `main.py` | `rcb_agent.py` | Why |
| --- | --- | --- | --- |
| `--max-attempts N` | `5` | `8` | An exhausted stage is auto-skipped, and a skipped stage costs real score, so the extra retries are worth their wall-clock. |
| `--final-stage STAGE` | run every stage | `07_writing` | The benchmark scores `report/report.md`, which Stage 07 writes. Stage 08 produces posters, slides and release notes the judge never opens. Pass `08_dissemination` for the full workflow. |
| `--operator`, `--venue`, `--output-format`, `--web-search` | declared unset, so a resumed run's recorded value can win | the literal default (`claude`, `neurips_2025`, `markdown`, `auto`) | Same effective value on a fresh run. There is no resume path here, so nothing has to be reconciled. |
| `--codex-sandbox MODE` | validated by argparse against `CODEX_SANDBOX_CHOICES`, declared unset | any string is accepted, defaulting to the literal `workspace-write` | The adapter declares no `choices`. An invalid mode is caught by `CodexOperator` as a runtime `ValueError` rather than as a usage error — and only if `--operator codex` is actually in play, since nothing else reads it. |
| `--review-panel`, `--rigor max` | make the run unattended | no additional effect | The run is unattended either way: `ResearchManager` is constructed with `unattended=True` unconditionally. |

`--stage-timeout` is `14400` on both. The benchmark harness imposes no timeout of
its own — neither the UI runner nor the batch CLI puts one on the agent
subprocess — so on this path it is the only thing that can cut a stage short.

### The 30 flags it does not have

`rcb_agent.py` is **not** a mirror of `main.py`. Of `main.py`'s 61 flags it
carries 31; the other 30 are not declared, and passing one is an argparse error
(`unrecognized arguments`), not a no-op:

| Group | Absent | Why |
| --- | --- | --- |
| Goal | `--goal`, `--goal-file` | The goal is built from the benchmark instructions by `build_benchmark_goal`. |
| Run location and resume | `--runs-dir`, `--resume-run`, `--redo-stage`, `--rollback-stage` | The run directory is derived from `--workspace`. There is no resume; `--export-only` is the only recovery path. |
| Interactive gate | `--approval-mode`, `--full-auto`, `--unattended` | Hardwired: the adapter constructs `ResearchManager` with `approval_mode="agent"` and `unattended=True`. There is nothing to switch. |
| Intake and priming | `--skip-intake`, `--resources`, `--project-root`, `--paper-corpus` | Intake is off unless `--intake` says otherwise, and the benchmark's own reference material is collected by `collect_reference_resources`. |
| Stage graph | `--stage-graph`, `--routing`, `--graph-max-steps`, `--graph-max-visits` | Not exposed. The manager's defaults still apply: adaptive graph, `auto` routing, and the step and visit ceilings. |
| Improvement loop | `--evolve`, `--evolve-rounds`, `--evolve-stages`, `--max-rounds` | Not exposed. The defaults still apply: the champion ratchet is on with 2 rounds, and Stages 03-06 run once. |
| Archive | `--archive`, `--no-archive`, `--archive-steer`, `--archive-report` | A benchmark run records nothing into the cross-run archive: `rcb_agent.py` never constructs an `Archive`. |
| Paired trials | `--trial`, `--capability`, `--arm`, `--trial-report` | Same reason — a trial arm is an archive row. |
| Report extras | `--research-diagram` | The benchmark judge scores the report's own figures. |

31 shared + 30 absent = `main.py`'s 61; 31 shared + 6 of its own = 37.

The shape of the difference is the point: what is missing is the **interactive**
surface (goal prompting, approval modes, resume and rollback) and the
**cross-run** surface (archive, trials, topology search). Neither has a meaning
inside a benchmark harness that launches one process per task, hands it a
workspace, and reads a report out of it.

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

## `fs_agent.py`

Answers **one** [FrontierScience-Research](frontierscience.md) question, in one of
two ways, and writes `answer.md` plus a `_meta.json` the exit code is computed
from. Never reads stdin. A set of questions is the trial driver's job.

```
python fs_agent.py [--task KEY] [--workspace PATH] [--dataset PATH]
                   [--profile {direct,ideate}]
                   [--answer-guidance {paper,minimal,coverage}]
                   [--operator {claude,codex}] [--model MODEL]
                   [--review-operator {claude,codex}] [--review-model MODEL]
                   [--codex-command BIN] [--codex-sandbox MODE]
                   [--answer-timeout SECONDS] [--stage-timeout SECONDS]
                   [--first-stage STAGE] [--final-stage STAGE]
                   [--max-attempts N] [--max-auto-skips N]
                   [--ideation-panel | --no-ideation-panel]
                   [--ideation-lenses LENS ...] [--ideation-models LENS=MODEL ...]
                   [--ideas-per-proposer N]
                   [--web-search {auto,gemini,native,off}]
                   [--disallowed-tools TOOL ...]
                   [--cross-review {auto,gemini,off}] [--cross-review-model MODEL]
                   [--runs-dir PATH] [--output-format {markdown,md,latex,tex}]
                   [--attempt-index N] [--print-goal] [--export-only]
                   [--fake-operator]
```

Not a subset: those are all 31 flags its `parse_args` declares.

### The question and where the run happens

| Flag | Default | Description |
| --- | --- | --- |
| `--task KEY` | read off the workspace directory name | Which question to answer, as a row index (`43`) or a key (`fs:043`). Addressed by row index and never by `task_group_id`, because two rows of the split are byte-identical. A workspace named `fs043_<anything>` carries the key, which is what the trial driver relies on; with neither, the run is **refused** rather than defaulted to row zero. |
| `--workspace PATH` | a fresh `<task>_<profile>_<timestamp>` directory under the current one | Where the run happens. The timestamp carries microseconds and the directory is created with `exist_ok=False`: two arms of one task launched inside the same second must not land in one directory, which on the sibling trial produced a paired difference of exactly zero. |
| `--dataset PATH` | `$FRONTIERSCIENCE_DATASET`, then `~/.cache/frontierscience/research_test.jsonl` | The split. Checked against two pinned digests on every load and refused if either disagrees. **Never downloaded.** |
| `--runs-dir PATH` | `<workspace>/.autor` | Where the AutoR run tree goes. Inside the workspace by default, so a trial can archive or delete one directory. |

### The two arms

| Flag | Default | Description |
| --- | --- | --- |
| `--profile {direct,ideate}` | `direct` | `direct` makes one operator call and keeps the reply — the paired control. `ideate` runs AutoR entered at Stage 02 and stopped there. |
| `--answer-guidance {paper,minimal,coverage}` | `minimal` | How much the agent is told about what an answer is. `paper` is the fenced problem and nothing else, the published setup. `minimal` adds the task instruction. `coverage` additionally describes the rubric's shape and is a **declared experimental intervention**: it must be applied to both arms or to neither, and the trial plan refuses at freeze time if the arms disagree. |
| `--first-stage STAGE` | `02_hypothesis_generation` | Where the `ideate` walk begins. Above Stage 01 on purpose: under a no-browsing protocol the literature survey's evidence ledger can only be satisfied by invented citations, and the rubric pays for named literature values, so a fabricated one displaces a real one. |
| `--final-stage STAGE` | `02_hypothesis_generation` | Where the walk stops. Nothing after it produces anything the examiner reads — and Stage 07's figure floor is never consulted, so no benchmark constant has to move. |
| `--attempt-index N` | `0` | Which repeat of this (task, arm) this run is, recorded in the metadata so between-attempt variance can be estimated instead of assumed. |

### Backend and reviewer

| Flag | Default | Description |
| --- | --- | --- |
| `--operator {claude,codex}` | `claude` | Execution backend. |
| `--model MODEL` | the backend default (`sonnet` for claude, `default` for codex) | Always pass it together with `--review-model`: an arm is the pair, and an arm that names one leaves the panels on whatever the backend defaults to. |
| `--review-operator {claude,codex}` | the execution backend | Backend for the reviewer agent. |
| `--review-model MODEL` | the backend default | Model for the reviewer that replaces the human approval gate. |
| `--codex-command BIN` | `codex` | Executable to invoke as the Codex CLI. Read only under `--operator codex`. |
| `--codex-sandbox MODE` | `workspace-write` | Codex CLI sandbox mode. Read only under `--operator codex`. |
| `--fake-operator` | off | Use the fake operator instead of a real backend, for smoke-testing the adapter. The answer it writes is marked in its first line **and** in `_meta.json`, because a smoke artifact clears every length and format check. |

### Budgets

| Flag | Default | Description |
| --- | --- | --- |
| `--answer-timeout SECONDS` | `1800` | Wall limit for the `direct` arm's single call. Not the stage timeout: there is no stage, and one number for two things is how a knob ends up tuned for the wrong one. |
| `--stage-timeout SECONDS` | `3600` | Per stage attempt in the `ideate` arm. Three times the interactive default, and load-bearing: the only per-stage duration ever measured here for a comparable configuration was 2,100 s, and a sibling trial at 1,800 s had 28 of 40 arms hit the ceiling. A timeout below the distribution converts an arm into a refusal rather than slowing it down. |
| `--max-attempts N` | `2` | Attempts per stage before it is auto-skipped. Bounded where `main.py` is not: the stuck detector fires only on three *identical* consecutive validation errors, and artifact errors carry filenames and counts. |
| `--max-auto-skips N` | `0` | How many stages may be auto-skipped. Zero, and this is the point of the adapter: an auto-skipped Stage 02 in a run whose only stage is Stage 02 is a run that produced nothing while reporting that it finished. |

### Ideation panel

| Flag | Default | Description |
| --- | --- | --- |
| `--ideation-panel` / `--no-ideation-panel` | **on** | Widen Stage 02's hypotheses with a panel of proposers. On by default here, unlike everywhere else in this repository: the coverage hypothesis this adapter exists to test is a hypothesis about the panel, so a run without it is the control arm with extra steps. |
| `--ideation-lenses LENS ...` | all five | Seat only these lenses. |
| `--ideation-models LENS=MODEL ...` | — | Assign a model per lens, as `lens=model` or `lens=backend:model`. |
| `--ideas-per-proposer N` | `2` | Candidate hypotheses each proposer may return. |

### Browsing, which the protocol forbids

| Flag | Default | Description |
| --- | --- | --- |
| `--web-search {auto,gemini,native,off}` | **`off`** | Default inverted relative to the rest of the repository. `off` offers no search tool *and* names the browsing tools to the Claude CLI as denied — for every seat the run builds: the executor, the reviewer and each ideation proposer. The codex backend has no denied-tool parameter, so a codex run records that it denied nothing rather than claiming it did. |
| `--disallowed-tools TOOL ...` | whatever `--web-search` implies | Tool names to deny, overriding that. Both arms must be given the same list. The metadata records three fields — what was asked for, what every seat actually carries (the intersection), and the per-seat breakdown — because a backend without the knob makes the first two differ. |
| `--cross-review {auto,gemini,off}` | **`off`** | Also inverted: a second model family auditing each approval is a second thing changing beside the thing being measured, and it is not part of either arm's description. |
| `--cross-review-model MODEL` | the cross reviewer's own default | Model for that auditor. |

### Reading and recovering

| Flag | Default | Description |
| --- | --- | --- |
| `--print-goal` | off | Print the goal the agent would be given and exit, creating nothing. The prompt is the instrument, so it has to be readable without spending a run — and a directory left behind by a `--print-goal` is a directory a trial sweep would later count as a run that was started. |
| `--export-only` | off | Skip the answer-producing step and re-export the most recent run in the workspace. `pipeline_completed` stays false, so the exit code is non-zero: a recovered workspace is evidence to look at, not a scored result. |
| `--output-format {markdown,md,latex,tex}` | `markdown` | Recorded on the run config. The examiner reads `answer.md` either way. |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All six `FS_EXIT_CLAUSES` hold: the answer file exists, its length is inside the band, it came from a model rather than from the deterministic fallback, the answer-producing procedure completed, no stage was auto-skipped, and the answer is an answer rather than a plan for one. `--print-goal` also exits `0`. |
| `1` | Any clause failed, or the adapter raised. The failing clause names are in `_meta.json` under `exit_clause_failures`, and the code is a pure function of that same dictionary, so it is re-derivable from the artifact by anyone holding it. |

The two profiles, the prompt contract and what each clause is defending against
are in [frontierscience.md](frontierscience.md).

---

## `tools/web_search.py`

Grounded web search backed by the Gemini API, for deployments where the coding
agent's built-in `WebSearch` tool is disabled.

```
python tools/web_search.py QUERY... [--json] [--model MODEL] [--max-results N]
                                    [--no-resolve-urls]
```

`QUERY...` is a required positional taking one or more words, joined with spaces.
Those four options are the whole flag surface.

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

Either backend needs `google-genai`, which is **not** a default dependency —
`pip install google-genai`. The Vertex probe uses `google.auth`, a different
distribution that can be present without it, so credentials alone are not enough
(see [What "can actually run" means](#what-can-actually-run-means)).

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

---

## `tools/score_rcb_run.py`

Scores a finished ResearchClawBench workspace. It drives the benchmark's own
`score_workspace`, so every number it prints is that scorer's rather than a
reimplementation; what it changes is the judge object and the helper that runs the
judge calls, which is where a failed call becomes a score of zero, and it refuses
to print a total while any call failed.

```
python tools/score_rcb_run.py --workspace PATH --bench PATH
                              [--judge {reference,vertex}] [--model MODEL]
                              [--draws N] [--key-file PATH] [--endpoint URL]
                              [--project-id ID] [--out PATH]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--workspace PATH` | **required** | The finished benchmark workspace to score. |
| `--bench PATH` | **required** | A checkout of ResearchClawBench. It is prepended to `sys.path` so `evaluation.score` can be imported; the scoring logic is the bench's, not this repo's. |
| `--judge {reference,vertex}` | `reference` | Which judge scores the run. See below — this is the single most consequential flag on the tool. |
| `--model MODEL` | `gpt-5.1` under `reference` (`REFERENCE_JUDGE_MODEL`), `claude-opus-4-5@20251101` under `vertex` (`FALLBACK_JUDGE_MODEL`) | Override the judge model id. Whatever it resolves to is printed twice — the `judge:` header line and the `TOTAL (judge …)` line — and recorded as `judge_model` in the `--out` JSON. The per-item lines carry no judge. |
| `--draws N` | `1` | Score the same artifacts N times and report the mean, the per-draw totals and the spread. The judge is stochastic — see below. At `1` the dispersion prints as **unmeasured**, never as `0.0`: a zero there would be a precision claim inferred from the one sample size that cannot support it, and it flatters, because a fabricated `±0.0` makes any delta look real. Costs one full pass per draw; `judge_calls` accumulates. |
| `--key-file PATH` | `~/api.txt` (`DEFAULT_KEY_FILE`) | File holding the reference judge's key. Outside any repository on purpose: a default inside the tree is one `git add -A` away from a leak. There is deliberately no flag that takes the key itself — it would land in the shell history and in the process table. The file may be a bare token, `KEY=token`, or a quoted value. |
| `--endpoint URL` | `REFERENCE_JUDGE_ENDPOINT` | The OpenAI-compatible base URL the reference judge is served from. Only read under `--judge reference`. |
| `--project-id ID` | `$ANTHROPIC_VERTEX_PROJECT_ID`, else empty | Vertex project for `--judge vertex`. Empty and unset exits `2` with `Set ANTHROPIC_VERTEX_PROJECT_ID or pass --project-id.` |
| `--out PATH` | — | Also write the full result, including `judge_model`, `judge_calls` and `judge_failures`, as JSON. |

### `--judge reference` is the default, and the only comparable one

`reference` means **gpt-5.1**, which is what ResearchClawBench itself scores with
(`evaluation/.env.example`). Use it unless you cannot.

The judge is part of the result, not a detail of how it was obtained. On
identical artifacts, Gemini 2.5 Flash scored 37.0 where Claude Opus scored 20.8 —
a spread of about sixteen points that is a property of the judge and not of the
run. A benchmark number quoted without its judge is therefore not comparable to
anything, which is why the tool leads with a `judge:` line, repeats the judge
inside the `TOTAL (judge …)` line so the number cannot be copied out without it,
and stores `judge_model` in the `--out` JSON. (The module docstring claims the
judge is on *every* line of output; it is not — the per-item rows, the
`workspace:` line and the `items judged:` line carry none.)

### `--draws` is the other half of the same caution

`--judge` is about *which* judge. `--draws` is about the same judge twice.

Eight draws of `gpt-5.1` over one artifact set held fixed — same workspace, same
`report.md`, same five figures, nothing changed between draws — scored 41.4, 42.8,
45.5, 47.1, 49.1, 49.6, 49.8 and 49.9: **spread 8.5**, sd 3.4, around a mean of
46.9. The variance is worst where it costs most; the item weighted 0.5 spanned 32
to 55, which is 11.5 points of the total by itself.

So a single-draw total on a single task carries roughly ±4 points of pure sampling
noise, and **a one-task A/B below about eight points is uninterpretable** — including
a before-and-after on the same task, which is the shape a harness change most tempts
you into. One such comparison read 46.0 against 42.8 and looked like a small
regression; 46.0 sits at the 3/8 percentile of the unchanged artifact's own
distribution.

The full table is in
[ResearchClawBench → How wide the judge's sampling range actually is](researchclawbench.md#how-wide-the-judges-sampling-range-actually-is).
Note that 8.5 holds the artifacts fixed: AutoR's own run-to-run variance is
additional and still unmeasured, so the floor for a real A/B is higher than that,
not equal to it.
`--judge vertex` exists for when no reference key is available;
its numbers are internally consistent and are **not** comparable to a published
figure.

### The default only works on one kind of box

`REFERENCE_JUDGE_ENDPOINT` is a site-specific Azure AI OpenAI-compatible URL, and
the key is read from `~/api.txt`. Out of the box the tool therefore only runs
where both of those hold: that tenancy plus a key file at that path. Elsewhere,
either point `--endpoint` and `--key-file` at your own OpenAI-compatible
deployment of the reference model, or fall back to `--judge vertex` and quote the
number with its judge attached. The endpoint is in source deliberately — an
endpoint is not a secret, the key that opens it is, and keeping the two visibly
different is what stops the second from being pasted next to the first.

### The stock defaults this tool does not inherit

Each of the failure modes below records as
`{"score": 0, "reasoning": "Failed to parse scoring response."}`, which is
indistinguishable in the output from a criterion the report genuinely missed.

None of them is fixed by raising a stock number. `score` replaces the bench's
judge object outright (`scorer.LLMAgent = lambda **_: judge`) and its concurrency
helper with a serial loop (`scorer.multi_thread = serial`), so the stock settings
below are discarded rather than tuned, and what applies instead is whatever the
tool's own judge class sends on the call.

| Stock setting | Why it fails | What applies instead |
| --- | --- | --- |
| `max_tokens=500` | a reasoning judge spends the budget thinking and returns an empty body | `VertexJudge.__call__` sends `max_tokens=JUDGE_MAX_TOKENS` (4096). `ReferenceJudge.__call__` — the default judge — sends no token cap at all, so the bound there is the `openai` client's, not one this tool sets. |
| `time_limit=120` | too short for a multimodal call carrying a target image plus five agent images | Neither judge class passes a timeout, so each call is bounded by whatever its client defaults to. `JUDGE_TIME_LIMIT` states the intended bound but is not passed to either judge. |
| `multi_thread(max_workers=min(len(checklist), 16))` | concurrent multimodal calls were the actual cause of most failures | The `serial` replacement calls the judge once per checklist item, in order. It accepts a `max_workers` argument and ignores it; `JUDGE_WORKERS` records the intent, the serial loop is what enforces it. |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Every item was judged. The total is printed with the judge's name beside it. |
| `1` | `score_workspace` returned an error, **or** at least one judge call failed — in which case the tool prints each reason and refuses to quote a total at all. |
| `2` | `--judge vertex` with no project id. |

Requires the `openai` package for `reference`, `anthropic` for `vertex`, plus the
bench's `structai` — `evaluation.score` imports it at module load, before the
judge is swapped in. The two client imports sit inside the judge classes, so
importing this module needs neither of them; the AutoR package itself still has
no third-party runtime dependency.

The same tool is described from the benchmark's side, with the worked example, in
[researchclawbench.md](researchclawbench.md#scoring-a-run-locally).

---

## `tools/score_fs_run.py`

Scores one FrontierScience answer against that task's own rubric, using the
paper's Appendix B judge prompt verbatim. Standard library only — one endpoint,
one JSON body, one JSON response, all of which `urllib.request` already does —
so unlike `tools/score_rcb_run.py` it runs on a bare interpreter and its
end-to-end test drives the real request path against a real `http.server` stub.

```
python tools/score_fs_run.py --task KEY --answer PATH --out PATH
                             [--answer-meta PATH] [--dataset PATH]
                             [--model MODEL] [--endpoint URL] [--key-file PATH]
                             [--reasoning-effort {low,medium,high}]
                             [--judge-max-tokens N] [--judge-timeout SECONDS]
                             [--draws N] [--raw-dir PATH]
```

| Flag | Default | Description |
| --- | --- | --- |
| `--task KEY` | **required** | The task to grade against, as `fs:043` or `43`. Row index, never `task_group_id`: rows 6 and 11 of the split are byte-identical, so the group id addresses fifty-nine of the sixty rows. |
| `--answer PATH` | **required** | The file holding the answer. Read as UTF-8 and sent verbatim. |
| `--out PATH` | **required** | Where the `fs_score/1` result goes. **Nothing is written when the total is refused**, so a driver inherits the refusal from the file's absence. |
| `--answer-meta PATH` | `_meta.json` beside the answer, when it exists | JSON merged into the result's `answer` block, for the facts only the producer knows — which arm wrote it, whether the pipeline completed, whether a stage was auto-skipped. Never fatal: an unreadable file yields nothing rather than an invention. |
| `--dataset PATH` | `$FRONTIERSCIENCE_DATASET`, then `~/.cache/frontierscience/research_test.jsonl` | The split, digest-pinned and refused on a mismatch. |
| `--model MODEL` | `gpt-5.1` (`FS_JUDGE_MODEL`) | The judge. What the paper grades with is GPT-5, which returns 404 on this endpoint, as does `gpt-5.2`. The tool prints that on the first two lines of every run: **no total it produces is comparable to the paper's table.** |
| `--endpoint URL` | `FS_JUDGE_ENDPOINT` | OpenAI-compatible base URL, without `/responses`. |
| `--key-file PATH` | `~/api.txt` (`DEFAULT_KEY_FILE`) | File holding the judge's key, outside any repository on purpose. **There is deliberately no flag that takes the key itself** — an argument lands in the shell history and in the process table — and every exception is passed through `redact` before it is printed. A bare token, `KEY=token` and a quoted value all read the same. |
| `--reasoning-effort {low,medium,high}` | `high` | What the paper grades at. Anything else is a different instrument, not a saving: the reasoning is where this judge does the per-item work that produces a decimal total. |
| `--judge-max-tokens N` | `32000` | The output budget, which is charged for the **thinking** rather than for the answer. At 4,096 and again at 2,048 the judge spent the whole budget on reasoning and returned no visible characters and no verdict; the largest total output observed was 20,004 tokens, 15,202 of them reasoning. |
| `--judge-timeout SECONDS` | `600` | Wall limit for one call. The 29 judge calls observed here averaged 72.9 s and the longest took 322.3 s. |
| `--draws N` | `1` | Grade the same answer N times and report the mean. Every draw runs even after one has failed — the remaining draws are what say whether it was one flaky call or the whole judge. At `1` the dispersion prints as **unmeasured**, never `0.0`, and carries the measured noise band with it. |
| `--raw-dir PATH` | not saved | Where to save each raw judge response, for regression and audit. **Point it outside this repository**: the judge quotes rubric items verbatim while it reasons, and the dataset card asks that this text stay out of crawlable corpora. |

There is no concurrency and no flag to add any. Concurrent judge calls were the
measured cause of most scoring failures on ResearchClawBench; 34 of 34 serial
calls here succeeded with zero retries.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Every requested draw was a measurement. The total is printed with the judge's name beside it and written to `--out`. |
| `1` | The dataset was refused, **or** the total is not a measurement — a draw failed, no draw was recorded, or fewer were recorded than requested. Each reason is printed and **nothing is written to `--out`**. A failed draw is never a zero: a deliberately bad answer scores exactly 0.000 here, so recording a failure as 0 would make the two indistinguishable. |
| `2` | `--draws` below 1, or no file at `--answer`. |

---

## `tools/fs_trial.py`

Runs a paired FrontierScience trial — several answers at a time, one judge call
at a time — and survives being killed. Four subcommands:

```
python tools/fs_trial.py plan   --plan PATH      # freeze it, print the digest
python tools/fs_trial.py run    --plan PATH      # launch, watch, grade, report
python tools/fs_trial.py report --plan PATH      # rebuild from the state dir alone
python tools/fs_trial.py fake-run --workspace PATH --task KEY --arm LABEL [...]
```

`plan`, `run` and `report` take one flag, `--plan PATH`, and it is **required**:
there is no default plan, because a default would be a trial nobody chose the
parameters of. Everything else about the trial lives in that file —
`configs/fs_trial_001.json` is the shipped one — and its digest is written into
the state directory at freeze time and checked on every later command, because
an apparatus that can be edited while it runs is an apparatus that can be
stopped when the sign looks good.

`fake-run` is not something a person types. It is the child process the dry run
launches for itself, and it declares 15 flags of its own: `--workspace`,
`--task` and `--arm` (all required), `--kind`, `--model`, `--review-model`,
`--profile`, `--answer-guidance`, `--dataset-sha256`, `--disallowed-tools`,
`--attempt-index`, `--quality`, and the three fault injectors `--no-transcript`,
`--browse N` and `--truncate`. The fault injectors exist so that the admission
clauses which refuse a run are reachable **end to end** rather than only from a
unit test holding a hand-written dictionary — a clause exercised only against a
dictionary somebody wrote to make it fire is a clause tested against its own
statement. `--no-transcript` is the sharpest of the three: it produces a run
with a perfectly ordinary `_meta.json` and no witness behind it, which is the
state a `browsing_tool_calls == 0` clause would admit if the metadata recorded
zero instead of null.

A dry run is a plan with `"operator": "fake"` and `"judge_kind": "fake"`. It
exercises the real lock, the real children, the real state machine, the real
metadata builder, the real transcript witness, the real admission gate, the real
scorer's pure half and the real report; it fabricates the two things that cost
money. **Every number it prints is a property of the fake operator**, and it
still sets each child's working directory to the arm's `worktree`, so that path
has to exist on disk.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The command finished. For `run` that means every planned `(task, arm)` reached a terminal state and the report was written to `<state_dir>/report.md` and printed. |
| `1` | An unhandled failure, including a plan the freeze-time refusals rejected. |
| `2` | `run` found somebody else's AutoR already running on this box, and refused to start. Two trials is the concurrency that exhausts the quota that then kills both. |

The arms, the ten admission clauses, the publication ceiling and what the report
refuses to print are in
[frontierscience.md](frontierscience.md#the-paired-trial).

---

## `tools/archive_sample_complexity.py`

```
python tools/archive_sample_complexity.py
```

**No flags.** It takes no arguments and reads nothing off disk; the sweep
constants (`POLICIES`, `SAMPLE_SIZES`, `REPLICATES`) are edited in the file.

It answers one question: how many runs the cross-run archive needs before
`--archive-steer` would be deciding on signal rather than on noise. It walks the
real `StageGraph.adaptive()` under synthetic routing policies, feeds the
resulting records to the real `edge_payoffs`, and counts how many edges satisfy
the real `EdgePayoff.believable`. Nothing in it reimplements the payoff
arithmetic, so every number it prints is a property of `src/archive.py` and
`src/stage_graph.py` as they stand.

It prints three things and exits: a believable-edge count per policy and sample
size, a per-edge table at the most generous policy, and a precision sweep — how
often the edge `propose_variant` would pick turns out to be one with no true
effect at all. Standard library only. It is not instant. `len(POLICIES) ×
len(SAMPLE_SIZES) × REPLICATES` is 9,600 replicate *cells*, and each cell of the
main sweep builds `n` records rather than one, so the work is
`len(POLICIES) × REPLICATES × sum(SAMPLE_SIZES)` = 6 × 200 × 1,890 = 2,268,000
simulated runs, plus 1,000 for the per-edge pass and 685,000 for the precision
sweep. It is single-threaded; a full run measured 3m38s of CPU here. Run it once
and read the tables, rather than in a loop.

The reading of its output, and what it implies for `--archive-steer`, is in
[Recursive Self-Improvement](self-improvement.md).
