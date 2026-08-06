# CLI Reference

Complete reference for AutoR's two entry points:

- `python main.py` — the terminal research workflow ([source](../main.py))
- `python studio.py` — the local browser workspace
  ([source](../src/backend/studio_http.py))

For a task-oriented introduction, read the [English Guide](tutorial_en.md)
instead. This page is the exhaustive list.

---

## `main.py`

```
python main.py [--goal GOAL] [--runs-dir DIR] [--fake-operator]
               [--model MODEL] [--operator {claude,codex}]
               [--codex-sandbox {read-only,workspace-write,danger-full-access}]
               [--approval-mode {manual,agent}] [--full-auto]
               [--review-operator {claude,codex}] [--review-model MODEL]
               [--venue VENUE] [--resume-run RUN_ID] [--redo-stage STAGE]
               [--rollback-stage STAGE] [--resources PATH [PATH ...]]
               [--skip-intake] [--research-diagram]
               [--project-root PATH] [--paper-corpus PATH]
               [--stage-timeout SECONDS]
```

### Goal and run location

| Flag | Default | Description |
| --- | --- | --- |
| `--goal GOAL` | prompted interactively | The research goal. If omitted, AutoR reads a multi-line goal from stdin and stops at the first empty line. An empty goal is an error. |
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
| `--full-auto` | off | Shortcut for `--approval-mode agent`. |
| `--review-operator {claude,codex}` | same as `--operator` | Backend used by the automated reviewer. Using a different backend than the executor gives the review some independence. |
| `--review-model MODEL` | backend default | Model for the reviewer. A stronger reviewer model than the executor model is a reasonable configuration. |

Manual review is still the recommended mode for research you intend to
publish. `agent` mode exists for unattended sweeps, overnight runs, and
automated dry runs.

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
