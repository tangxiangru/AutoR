# AutoR Studio

Studio is a local browser workspace over the same run-based workflow as the
terminal. Same run directories, same stage contract, same artifacts — a
different way to watch and approve them.

It is not a hosted product. It is a stdlib `http.server` bound to localhost by
default, reading and writing the run directories already on your disk.

---

## Running it

```bash
python studio.py
# → http://127.0.0.1:8000/studio/
```

| Flag | Default | Purpose |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Bind port |
| `--repo-root` | `.` | Repository root; also the base for the two paths below |
| `--runs-dir` | `<repo-root>/runs` | Run directory to read and write |
| `--metadata-root` | `<repo-root>/.autor` | Where the project index lives |

```bash
python studio.py --port 8765
python studio.py --runs-dir /mnt/big-disk/runs
```

### Requirements

Studio runs are **Claude-backed only** — there is no Codex path through the
browser UI. The `claude` CLI must be on `PATH`.

The check happens when you **start a run**, not at server startup: the server
comes up fine without `claude` installed, and you can browse existing runs,
read stage documents, and view papers. Starting a run without it fails with
`Claude CLI not available on PATH.`

### Exposing it beyond localhost

> **The API has no authentication.** It can start agent runs and read any file
> under the runs directory. `--host 0.0.0.0` publishes all of that to your
> network.
>
> For remote access, prefer an SSH tunnel:
> `ssh -L 8000:127.0.0.1:8000 you@host`, then browse to
> `http://127.0.0.1:8000/studio/` locally.

---

## What you can do

### Projects hub

Create a project with a title and a thesis, and a real Claude-backed run
starts immediately. A **project** is Studio-only metadata that groups runs
together — it lives in `.autor/projects.json`, never inside a run. Deleting it
loses the grouping; the runs are untouched.

### Overview

The live view of a run: the stage strip with the current stage pulsing, and a
session trace streaming the agent's real tool calls as they are parsed out of
`logs_raw.jsonl`.

### Review

The human gate. A "You are reviewing" card with a TL;DR pulled from the stage
markdown, a **Files Produced** pill list, and
`✅ Approve → Advance to <next stage>`.

### Feedback and re-run

Feedback is woven into the **first attempt's prompt** of the next run rather
than spent on an intermediate call. It works on stages in `human_review` and
on `failed` stages, which is what makes a failed stage recoverable from the
browser.

### Paper

The compiled PDF, the LaTeX sources, and the build log, side by side.

### Versions

The full checkpoint and attempt timeline for every stage, reconstructed from
the run manifest and the stage files.

### Notebook

A Claude conversation scoped to one run, with the run's thesis, status, and
stage list as context. Transcript and session ID persist under
`<run>/notebook/`, so the conversation survives a restart.

### Resume across restarts

Stop the server, come back later, click Approve or Feedback: the Studio
lazy-resumes the on-disk run without re-running stages that already have a
draft. There is no in-memory state to lose, because there is no in-memory
state.

---

## HTTP API

Everything below is served by
[`src/backend/studio_http.py`](../src/backend/studio_http.py). Responses are
JSON unless noted. Errors are `{"error": "<detail>"}` with the status codes in
[the table at the end](#error-responses).

Path parameters: `{run_id}` is a run directory name, `{project_id}` a Studio
project ID, `{slug}` a stage slug such as `03_study_design`.

### Health and static assets

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/healthz` | `{"status": "ok"}` |
| `GET` | `/`, `/studio`, `/studio/` | the single-page app |
| `GET` | `/studio/<asset>` | static assets from `src/frontend/static/` |
| `GET` | `/studio/ext/<asset>` | modules from `src/frontend/` |

Both static handlers reject paths that escape their root with `400`.

### Projects

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/projects` | All project records. |
| `GET` | `/api/projects/overview` | All projects with their run summaries resolved. |
| `GET` | `/api/projects/{project_id}` | One project summary. |
| `POST` | `/api/projects` | Create a project. `201`. |
| `POST` | `/api/projects/{project_id}/runs` | Attach an existing run to a project. |
| `POST` | `/api/projects/{project_id}/runs/start` | Start a new Claude-backed run. `201`. |

`POST /api/projects`

```json
{ "title": "MoE-LoRA study", "thesis": "...", "default_mode": null, "tags": ["nlp"] }
```

`participation_model` is always `human_in_loop`.

`POST /api/projects/{project_id}/runs`

```json
{ "run_id": "20260330_101222", "make_active": true }
```

`POST /api/projects/{project_id}/runs/start`

```json
{ "goal": "optional; defaults to the project thesis" }
```

→ `{"run_id": "...", "project_id": "..."}`. Requires `claude` on `PATH`.

### Runs

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/runs` | `{"run_ids": [...]}` |
| `GET` | `/api/runs/{run_id}` | Run summary: status, current stage, per-stage entries. |
| `GET` | `/api/runs/{run_id}/history` | Version records and trace events. |
| `GET` | `/api/runs/{run_id}/artifacts` | The run's `artifact_index.json`, or `{}`. |
| `GET` | `/api/runs/{run_id}/sessions` | Session summary across stages. |

### Stages

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/runs/{run_id}/stages/{slug}` | `{"run_id", "stage_slug", "markdown"}` |
| `GET` | `/api/runs/{run_id}/stages/{slug}/session` | Trace events for that stage. |
| `POST` | `/api/runs/{run_id}/stages/{slug}/approve` | Approve and advance. |
| `POST` | `/api/runs/{run_id}/stages/{slug}/feedback` | Re-run with feedback. |

`POST .../feedback`

```json
{ "feedback": "The baselines are missing. Add dense LoRA at matched parameter count." }
```

→ `{"run_id", "stage_slug", "action": "feedback_submitted"}`

### Paper

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/runs/{run_id}/paper` | Preview: `tex_relative_path`, `tex_content`, `section_paths`, `pdf_relative_path`, `pdf_available`, `build_log_relative_path`, `build_log_content`. |
| `GET` | `/api/runs/{run_id}/paper/pdf` | The compiled PDF as `application/pdf`. |

### Files

| Method | Path | Query | Description |
| --- | --- | --- | --- |
| `GET` | `/api/runs/{run_id}/files/tree` | `root` (default `workspace`), `depth` | File tree under the run. |
| `GET` | `/api/runs/{run_id}/files/content` | `path` | Contents of one file, relative to the run root. |

### Iteration planning

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/runs/{run_id}/iterations/plan` | Compute — but do not execute — the effect of an iteration. |

```json
{
  "base_stage_slug": "05_experimentation",
  "scope_type": "stage",
  "scope_value": "",
  "mode": "continue",
  "freeze_upstream": true,
  "invalidate_downstream": true,
  "user_feedback": ""
}
```

`scope_type` ∈ `stage` · `file` · `subtree` · `manuscript`
`mode` ∈ `continue` · `redo` · `branch`

The response reports `preserved_stages`, `affected_stages`, `stale_stages`,
`branch_run_id`, `reuses_current_run`, a human-readable `summary`, an
`operator_brief`, and `reviewer_actions`. This is a dry run: nothing on disk
changes.

### Notebook

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/notebook/transcript?run_id=...` | `{"run_id", "events", "session_id"}` |
| `POST` | `/api/notebook/stream` | Stream a reply as Server-Sent Events. |
| `POST` | `/api/notebook/reset` | Clear the notebook session and transcript. |

`POST /api/notebook/stream` takes `{"run_id": "...", "message": "..."}` and
responds with `text/event-stream`. Each event is a `data:` line containing a
JSON object; the stream ends with `{"type": "done"}`. A missing `claude` CLI
arrives as `{"type": "error", "detail": "..."}` followed by `done`, rather than
as an HTTP error — the stream has already started by then.

Both `run_id` and `message` are required; either missing gives `400`.

### Error responses

| Status | Raised for |
| --- | --- |
| `400` | Bad request — bad parameters, or a static path escaping its root. |
| `404` | Unknown route, unknown run or project, or a missing file. |
| `409` | Conflicting state — e.g. approving a stage that is not awaiting review. |
| `500` | Unhandled error; the detail is included. |

---

## Scripting the API

The API is plain HTTP with no auth, which makes it convenient to script
locally.

```bash
# What runs exist?
curl -s localhost:8000/api/runs | python -m json.tool

# Where is the newest run?
curl -s localhost:8000/api/runs/20260330_101222 | python -m json.tool

# Read a stage summary
curl -s localhost:8000/api/runs/20260330_101222/stages/05_experimentation \
  | python -c 'import json,sys; print(json.load(sys.stdin)["markdown"])'

# Approve it
curl -s -X POST \
  localhost:8000/api/runs/20260330_101222/stages/05_experimentation/approve

# Send feedback instead
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"feedback":"Add the dense LoRA baseline at matched parameter count."}' \
  localhost:8000/api/runs/20260330_101222/stages/05_experimentation/feedback

# Fetch the compiled PDF
curl -s -o paper.pdf localhost:8000/api/runs/20260330_101222/paper/pdf
```

Scripting `approve` is scripting away the human gate. That is a legitimate
thing to do for a dry run or a sweep; it is not the mode to use for research
you intend to publish.

---

## Design documents

The Studio's design record lives in [ui-design/](ui-design/): information
architecture, screen specs, system architecture, development plan, and
reference screenshots. Those are design documents and may describe intent
ahead of what is implemented; this page describes what is implemented.
