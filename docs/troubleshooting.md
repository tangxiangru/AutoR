# Troubleshooting

Symptom-to-fix for the errors AutoR actually produces. If your problem is
"the output is not good enough" rather than "something broke", the
[user guide](tutorial_en.md#9-the-most-important-usage-principle-first-pass-output-is-often-toy-level)
is the right page.

---

## Where to look first

In this order:

1. **`runs/<run_id>/logs.txt`** — the workflow log. Stage starts, attempts,
   validation failures, approvals, aborts. Nine times out of ten the answer is
   here.
2. **`runs/<run_id>/run_manifest.json`** — where the run actually is. Stage
   statuses, attempt counts, `last_error`, stale flags.
3. **`runs/<run_id>/logs_raw.jsonl`** — every tool call the agent made. This is
   the ground truth for "what did it actually do".
4. **`runs/<run_id>/prompt_cache/<slug>_attempt_NN.prompt.md`** — exactly what
   the agent was asked. If behaviour is baffling, read the prompt.
5. **`runs/<run_id>/operator_state/<slug>.attempt_NN.json`** — the literal
   command line used, so you can rerun the backend by hand.

---

## Startup and configuration

### `claude CLI not found: claude` / `codex CLI not found: codex`

The backend is not on `PATH`. Install it
([Claude Code](https://docs.claude.com/en/docs/claude-code) ·
[Codex CLI](https://developers.openai.com/codex/cli)), or run with
`--fake-operator` to exercise the workflow without a backend.

Check with `which claude` in the same shell you run AutoR from — a CLI
installed under a version manager may not be on `PATH` for non-login shells.

### `Unknown venue: <value>`

Not a registry key, display name, or style package. See the
[venue table](configuration.md#venue-registry). Matching ignores case and
punctuation, so the value is genuinely absent rather than misspelled in
formatting.

### `Unknown stage identifier: <value>`

`--redo-stage` / `--rollback-stage` accept `03`, `3`, or `03_study_design`.
Anything else — including `stage03` and `3_study_design` — is rejected.

### `AutoR is running unattended and cannot answer an interactive prompt: ...`

An unattended run (`--full-auto`, `--unattended`, `--approval-mode agent`, or
`rcb_agent.py`) reached a prompt that needs a person. The message names the
prompt.

This is deliberate: unattended AutoR refuses to read stdin at all, so a prompt
fails immediately instead of hanging for hours. If you hit it, either supply
the answer as a flag — `--goal`/`--goal-file` for the goal, `--resources` for
input files — or run without `--unattended`.

### `Unattended runs cannot prompt for a research goal. Pass --goal or --goal-file.`

`--full-auto` implies `--unattended`, and there is no one to type a goal. Use
`--goal "..."`, or `--goal-file path.txt` when the goal is too long for a shell
argument.

### `<Stage> exhausted its retries and the unattended auto-skip budget (N) is already spent. Aborting.`

More stages failed than `--max-auto-skips` allows. Raise the budget to push
through a run you only need partially, or read `logs.txt` for the
`unattended_auto_skip` entries — each one records the validation errors that
killed the stage, which is usually the real problem.

### `--redo-stage and --rollback-stage are mutually exclusive.`

Pick one. Redo re-runs a single stage; rollback returns to a stage and marks
everything after it stale. See
[Architecture → Rollback and staleness](architecture.md#rollback-and-staleness).

### `Research goal cannot be empty.`

The interactive goal prompt got nothing. Type the goal, then press Enter on an
empty line to finish. Or pass `--goal "..."`.

### `No runs found in <dir>`

`--resume-run latest` with an empty runs directory. Check `--runs-dir` — it is
resolved **relative to the repository root**, not your current directory, so
running from a subdirectory does not change where AutoR looks.

### `Run not found: <path>`

The `run_id` does not exist under `--runs-dir`. List them with
`ls runs/`. A `run_id` is a `YYYYMMDD_HHMMSS` timestamp.

### `Missing user_input.txt in run: <path>` / `Missing memory.md in run: <path>`

Both are required to resume. If they were deleted, the run cannot be resumed —
the goal and the approved memory are the two things AutoR cannot reconstruct.
The workspace artifacts are still there and still usable.

### `Project root not found` / `Paper corpus path not found`

The `--project-root` or `--paper-corpus` path does not exist. Both are
expanded (`~`) and resolved, so a relative path is interpreted from your
current directory.

---

## During a run

### A stage keeps failing validation

Read the validation errors — they name the exact requirement. The
[Stage Contract](stage-contract.md) explains each one. The usual causes:

| Error | Cause |
| --- | --- |
| `Section 'Files Produced' references missing file(s)` | The summary claimed files that were not written. Usually the agent described intended work rather than completed work. |
| `Missing required section: Decision Ledger` | An older prompt or a truncated response. The repair pass normally fixes this. |
| `... requires machine-readable data artifacts under workspace/data` | Only markdown notes were produced. Push the stage to write real `.json`/`.csv` files. |
| `... requires <artifact> produced or updated during the current stage execution` | The artifact exists but is stale — left over from a previous attempt. The stage must genuinely regenerate it. |
| `claims.json entry N references unknown source_ids` | A claim cites a source that is not in `sources.json`. |
| `... requires a supported conference or journal manuscript` | `main.tex` does not match the run's venue. Add `% AutoR venue: <key>` near the top, or use the venue's style package. |

### `Stage X failed after 5 attempts. Escalating to user.`

`MAX_STAGE_ATTEMPTS` is exhausted. You are offered skip, roll back, or abort.

Repeated failure at the same stage usually means the goal is too broad for the
stage to complete, or a dependency is missing (no dataset, no GPU, no LaTeX).
Read the last attempt's prompt and the raw log before choosing. Rolling back
to an earlier stage and narrowing the scope is often more effective than
retrying.

### The run appears to hang

Most likely it is working. A real Stage 05 can run for hours; the per-attempt
ceiling is `--stage-timeout`, default 4 hours.

To check: watch `logs_raw.jsonl` grow (`tail -f`), or look at the
`operator_state/<slug>.attempt_NN.json` timestamps.

If it is genuinely stuck, Ctrl-C exits with code 130 leaving the run
resumable, and `--resume-run latest` picks it back up.

### A long training run keeps timing out

Raise the ceiling: `--stage-timeout 43200` for 12 hours.

### `Failed to capture <backend> output stream.`

The backend process produced no readable stream. Usually a crashed or
misconfigured CLI. Verify the backend works standalone:

```bash
claude --version
claude -p "say hi"
```

### Resume produced a fresh session instead of continuing

Expected behaviour, not a bug. If the backend reports that a session ID no
longer exists, AutoR detects it and starts a fresh session rather than failing
the stage. Backend session stores expire; the run continues with the approved
memory intact.

### Terminal rendering is broken or full of escape codes

`TERM=dumb python main.py ...` disables color. Useful when piping to a file or
running under a CI log collector.

Wide characters and long lines are handled, but a terminal narrower than
~40 columns will wrap awkwardly.

### The intake prompt never appears

Stage 00 is skipped automatically when stdin is not a TTY. Piped input, `nohup`,
and most CI runners all trigger this. Pass `--goal` explicitly for those, and
know that intake will not run.

---

## Stage 07 writing

### The PDF never compiles

Stage 07 needs a working LaTeX toolchain. Check:

```bash
which pdflatex latexmk
```

Read `workspace/artifacts/build_log.txt` for the actual LaTeX error. A missing
style package is the most common cause — AutoR stores venue *metadata* and
does not vendor official style files, so the stage has to obtain them.

### `... requires build_log.txt under workspace/artifacts`

The build never ran, or ran somewhere else. The build log is required
evidence that compilation was attempted, and at Stage 07 it must be fresh.

### `citation_verification.json` / `layout_review.json` validation fails

The file exists but does not match the schema. The exact missing field is in
the error. Schemas are in
[Run Artifacts → Validated JSON files](run-artifacts.md#validated-json-files).

---

## Diagram generation

### `Diagram generation failed: No module named 'google'`

`pip install google-genai pyyaml`. The SDK is not a default dependency. The
run continues without the diagram either way.

### `Gemini API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY ...`

Export one of those, or fill in `configs/diagram_config.yaml` (copy from
`configs/diagram_config.template.yaml`). See
[Configuration → Diagram generation](configuration.md#diagram-generation-optional).

---

## Studio

### `Claude CLI not available on PATH.` when starting a run

Studio runs are Claude-backed only. Install the Claude CLI. The server starts
without it — you can browse existing runs, read stage documents, and view
papers — but starting a run needs it.

### `Unknown route: <path>`

The path is not in the API. The full surface is in
[the Studio API reference](studio.md#http-api).

### `Address already in use`

Another process holds the port. Use `--port 8765`, or find the holder with
`lsof -i :8000`.

### The Studio shows no runs

Check `--runs-dir`. It defaults to `<repo-root>/runs`, and the Studio only
sees runs under whichever directory it was given.

### A `409 Conflict` on approve

The stage is not awaiting review — it may already be approved, or still
running. Refresh the run summary
(`GET /api/runs/{run_id}`) to see its actual status.

### Notebook replies with an error event instead of text

The stream had already started when the failure occurred, so errors arrive as
`{"type": "error", "detail": "..."}` inside the SSE stream rather than as an
HTTP status. A missing `claude` CLI is the usual detail.

---

## Recovering a run

| Situation | Do this |
| --- | --- |
| Stage output was weak, direction is right | `--resume-run <id> --redo-stage <n>` |
| A later stage proved an earlier decision wrong | `--resume-run <id> --rollback-stage <n>` |
| Process died or was interrupted | `--resume-run latest` |
| A stage is unfixable and you want to move past it | `/skip` at the recovery prompt |
| You want to jump back mid-run | `/back <stage>` at the recovery prompt |
| The run is beyond saving | Start fresh with a narrower goal. The old run stays on disk. |

Rolling back rebuilds `memory.md` from the surviving approved stages and marks
downstream stages stale. Nothing is deleted, so a rollback is recoverable by
re-running forward.

---

## Still stuck

Open an issue with:

- The command you ran.
- The relevant lines from `logs.txt`.
- The stage's entry from `run_manifest.json`.
- Your Python version and OS, and which backend CLI you used.

Redact anything sensitive — prompts and logs may contain your research goal,
file paths, and data. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the issue
templates.
