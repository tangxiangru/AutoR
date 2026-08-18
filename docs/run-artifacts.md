# Run Artifacts

Everything a run produces lives inside one directory, `runs/<run_id>/`, where
`run_id` is a `YYYYMMDD_HHMMSS` timestamp. Nothing is stored in a database,
nothing is stored globally, and a run directory can be copied, archived, or
handed to someone else and remain complete.

This page documents every file **AutoR itself writes** into that directory, and
the schema of every machine-readable one. It is not a listing of everything you
will find there: `workspace/` is the agent's own working directory, and a stage
may put any file it likes under `code/`, `data/`, `results/` or `notes/`. Those
are inventoried by `artifact_index.json` rather than enumerated here.

---

## Directory layout

```text
runs/<run_id>/
├── .claude/skills/             # agent skills, installed from src/skills/ (this is the operator's cwd)
├── user_input.txt              # the original research goal, verbatim
├── memory.md                   # settled stage summaries: the free-text cross-stage memory
├── run_config.json             # backend, model, venue, approval mode, sandbox, stage graph
├── run_manifest.json           # stage lifecycle state — the machine-readable source of truth
├── artifact_index.json         # index over workspace/{data,results,figures} and report/images
├── intake_context.json         # Stage 00 Q&A, ingested resources, refined goal
├── obligations.json            # what a reviewer said a later stage still owes (agent gate only)
├── review_policy.json          # standing rules learned from this run's refusals and rollbacks
├── report_plan_stamp.json      # AutoR's copy of the report plan's date and digest
├── preregistration_stamp.json  # AutoR's copy of the frozen hypothesis set
├── validity_review_stamp.json  # AutoR's copy of what each adversarial pass raised
├── stage_cost_ledger.json      # what each stage visit spent, and why each attempt failed
├── supervisor_ledger.jsonl     # one line per run-supervisor ruling
├── review_custody.jsonl        # one line per reviewer episode: what the run root did while it ran
├── logs.txt                    # human-readable workflow log
├── logs_raw.jsonl              # raw backend stream-json events
├── prompt_cache/               # the exact prompt sent for every attempt
├── operator_state/             # per-stage session IDs, attempt state, start markers, MCP config
├── handoff/                    # compressed per-stage handoff summaries
├── evolution/                  # stage graph route, rubric scores, champions, candidates
├── stages/                     # stage summaries: <slug>.tmp.md draft, <slug>.md approved
├── notebook/                   # Studio Notebook session and transcript (Studio runs only)
├── sessions/                   # Studio trace events per stage (Studio runs only)
└── workspace/                  # the research payload
    ├── literature/             # reading notes, survey tables, sources.json, claims.json
    ├── code/                   # runnable code, scripts, configs
    ├── data/                   # machine-readable datasets and manifests
    ├── results/                # metrics, predictions, ablations, experiment_manifest.json
    ├── report/                 # markdown deliverable: report.md + images/ (markdown mode)
    ├── writing/                # LaTeX sources, sections/, bibliography, tables (latex mode)
    ├── figures/                # plots and paper figures
    ├── artifacts/              # compiled PDFs, build_log.txt, review JSON, deliverables
    ├── notes/                  # supporting notes, report_plan.json, hypothesis_manifest.json, preregistration.json
    ├── reviews/                # readiness, critique, dissemination material
    ├── bootstrap/              # --project-root scan output
    └── profile/                # --paper-corpus scan output: derived researcher profile
```

The directory shape is created by `ensure_run_layout` and the paths are
defined once, in `build_run_paths` ([`src/utils.py`](../src/utils.py)). If you
need a path in code, take it from `RunPaths` rather than joining strings.

Eight files sit at the run root rather than under `workspace/` on purpose:
`obligations.json`, `review_policy.json`, `report_plan_stamp.json`,
`preregistration_stamp.json`, `validity_review_stamp.json`,
`stage_cost_ledger.json`, `supervisor_ledger.jsonl` and `review_custody.jsonl`
are records *about* the run rather than part of its answer, and every stage
prompt directs the agent at `workspace/` paths. Same reason `evolution/` is out
here — and, like `evolution/`, it also keeps them out of a benchmark export that
packages the workspace.

The last two are also out here because of *who* they are about. A supervisor
ruling and a reviewer custody line are records of the harness watching an agent,
and an agent that could edit them could edit the record of being caught.

`review_custody.jsonl` holds one JSON object per reviewer subprocess — the solo
gate, its verdict-only re-ask, every panel seat, the chair, and the adversarial
validity pass — written whether or not anything moved, because only-on-breach
would make "the census never ran" and "the census found nothing" the same
record. Each line carries `stage`, `label`, `mutated`, the `added` / `changed` /
`deleted` / `type_changed` path lists, `touched` (rewritten to the same bytes —
a reviewer re-deriving an artifact, which is not a breach), `entries`, `took_ms`
and `scan_errors`. Written by `record_episode`
([`src/review_custody.py`](../src/review_custody.py)); see
[`--review-custody`](cli-reference.md#reviewer-custody).

---

## Top-level files

### `user_input.txt`

The research goal exactly as given, before any intake refinement. Required for
resume; a run without it cannot be resumed.

### `memory.md`

The only *free-text* context shared across stages, and the largest one. A stage
does not see another stage's conversation — it sees this file. It is not the
only channel, though: `build_handoff_context` sends the last few stages' trimmed
summaries, `build_decision_ledger_context` broadcasts every prior `Decision
Ledger` section separately, and the typed channels in `information_flow.py`
carry the machine-readable artifacts. What crosses a stage boundary is
enumerable from `build_prompt` and `CHANNELS`; the sections below cover each
carrier in turn.

Each **settled** stage contributes one entry containing its `Objective`,
`What I Did`, `Key Results`, and `Files Produced` sections. Settled, not
approved: `_skip_stage` appends a skipped stage's summary here too, and
`rebuild_memory_from_manifest` iterates on each entry's `settled` flag rather
than its `approved` flag when it reconstructs the file after a rollback. That
is deliberate — a later stage has to know the gap exists — but it means this
file is not a record of accepted work, and "approval" does not gate what the
rest of the run sees. Read `approved` in `run_manifest.json` when you want to
know what was actually accepted. A `--project-root` bootstrap adds entries for
the stages it declares already done, without any of them being run or reviewed.

Required for resume. Rebuilt from `run_manifest.json` after a rollback.

### `run_config.json`

The settings the run was started with, so a resume reproduces them.

```json
{
  "model": "sonnet",
  "operator": "claude",
  "venue": "neurips_2025",
  "output_format": "markdown",
  "approval_mode": "manual",
  "review_operator": "claude",
  "review_model": "sonnet",
  "codex_sandbox": "workspace-write",
  "stage_graph": "adaptive",
  "routing_mode": "auto",
  "evolve_rounds": 2,
  "evolve_measure": true,
  "archive_steer": false,
  "web_search": "auto",
  "min_report_figures": 1,
  "created_at": "2026-03-30T10:12:22"
}
```

| Field | Values |
| --- | --- |
| `model` | Model alias or full name for the execution backend. `"unknown"` if never recorded. |
| `operator` | `claude` or `codex`. |
| `venue` | A key from the [venue registry](configuration.md#venue-registry). |
| `output_format` | `markdown` (default) or `latex`. Selects Stage 07's deliverable and gates. An unrecognized value falls back to `markdown` rather than failing the run. |
| `approval_mode` | `manual` or `agent`. |
| `review_operator` | `claude` or `codex`; defaults to `operator`. |
| `review_model` | Reviewer model; defaults to `sonnet` (Claude) or `default` (Codex). |
| `codex_sandbox` | `read-only`, `workspace-write`, or `danger-full-access`. |
| `stage_graph` | `adaptive` (default) or `linear`. See [Recursive Self-Improvement](self-improvement.md). |
| `routing_mode` | `auto` (default), `agent`, or `off`. Who chooses the move out of a completed stage. |
| `evolve_measure` | Whether every valid draft is scored and the champion ratchet runs. `true` by default; costs no backend call. |
| `evolve_rounds` | Improvement rounds per stage; `2` by default, `0` measures without polishing. |
| `archive_steer` | Whether the cross-run archive may choose this run's topology, as opposed to only recording what it did. `false` by default. |
| `web_search` | `auto`, `gemini`, `native`, or `off`. The mode, not the resolved backend. Absent in runs created before it existed, and read as `auto`. |
| `min_report_figures` | Distinct rendered figures `workspace/report/images/` must hold before Stage 07 can be approved in `markdown` mode. `MIN_REPORT_FIGURES` = 1 for an ordinary run; `rcb_agent.py` sets `BENCHMARK_MIN_REPORT_FIGURES` = 3. `resolve_min_report_figures` clamps whatever it reads into `[1, MAX_REPORT_FIGURES]`, so a value of `0`, `99` or `"three"` becomes 1, 5 and 1 respectively rather than failing the run. Read as a hard gate by `validate_markdown_report`. |
| `created_at` | ISO-8601 to the second. Preserved across rewrites. |

A missing or corrupt file falls back to defaults rather than failing the run.
See [Configuration](configuration.md#run_configjson) for which CLI flags
override which fields on resume.

### `run_manifest.json`

The machine-readable lifecycle state of the run — what the Studio reads, and
what rollback rewrites. Written by [`src/manifest.py`](../src/manifest.py).

```json
{
  "run_id": "20260330_101222",
  "created_at": "2026-03-30T10:12:22",
  "updated_at": "2026-03-30T18:40:07",
  "run_status": "human_review",
  "last_event": "stage.human_review",
  "current_stage_slug": "05_experimentation",
  "last_error": null,
  "completed_at": null,
  "stages": [
    {
      "number": 1,
      "slug": "01_literature_survey",
      "title": "Stage 01: Literature Survey",
      "status": "approved",
      "approved": true,
      "skipped": false,
      "skip_kind": null,
      "skip_reason": null,
      "settled": true,
      "dirty": false,
      "stale": false,
      "attempt_count": 2,
      "session_id": "a1b2c3d4-...",
      "final_stage_path": "stages/01_literature_survey.md",
      "draft_stage_path": "stages/01_literature_survey.tmp.md",
      "artifact_paths": ["workspace/literature/sources.json"],
      "last_error": null,
      "invalidated_reason": null,
      "invalidated_by_stage": null,
      "updated_at": "2026-03-30T11:02:15",
      "approved_at": "2026-03-30T11:02:15"
    }
  ]
}
```

**`run_status`** — unchanged when a walk reaches the terminal with gaps: the walk did
complete, and what a skipped stage or an open obligation changes is the `run_complete`
log entry and the closing line, which `ResearchManager._completion_sentence` derives from
the manifest's `skipped` flags and the obligation ledger rather than asserting. A clean
run still reads *"All stages approved."*; a run that auto-skipped its writing stage now
names it instead. One of `pending`, `running`, `human_review`, `completed`,
`failed`, `cancelled`, `halted`, `abandoned`.

The last two are the ones worth knowing about, because both are stops that are
*not* failures and are *not* completions. `halted` means a budget ran out
(`--graph-max-steps`, `--graph-max-visits`, or no admissible move) with stages
still unsettled — a run reported as `completed` there would read as a success
holding four stages that never ran. `abandoned` means a research round
concluded `abandon`: the run decided the question could not be answered with
the resources available, which is a real conclusion and is recorded as one.
`--final-stage` stopping a run is neither; that is the caller getting what they
asked for, and it completes.

**Stage `status`** — one of `pending`, `running`, `human_review`, `approved`,
`skipped`, `failed`, `stale`. `stale` is written by a rollback to every stage
*after* the one rolled back to; the stage rolled back to returns to `pending`.

**Stage flags:**

| Flag | Meaning |
| --- | --- |
| `approved` | You (or the reviewer agent) accepted this stage's work. |
| `skipped` | The stage was promoted without its work being done. `skip_kind` is `human` (you ran `/skip`, or chose to skip after retries ran out) or `auto` (an unattended run exhausted the retry budget with nobody in the loop). `skip_reason` says which. A skipped stage is **never** `approved`. |
| `settled` | Derived: `approved or skipped`. This is the resume cursor — the run moves past a settled stage. Read this, not `approved`, when you want "is AutoR done with this stage". Read `approved` when you want "was this work actually accepted". |
| `dirty` | The stage has an unpromoted draft. |
| `stale` | An earlier stage was rolled back, so this stage's conclusions may no longer hold. `invalidated_reason` and `invalidated_by_stage` say why. |

A skipped stage still writes a stage summary and still feeds downstream
prompts, because later stages need to know the gap exists. The summary says the
work was not done; treat its content as a placeholder, not evidence.

`session_id` is the backend conversation for that stage, which is what makes
refinement continue a conversation instead of restarting one.

### `.claude/skills/`

The agent skill pack, copied from `src/skills/` when the run is created and
again on resume. The operator invokes its agent CLI with `cwd=run_root`, and
Claude Code discovers project skills at `<cwd>/.claude/skills/<name>/SKILL.md`
— so this directory, not the AutoR checkout's, is what the operator can reach.

Each skill is loaded only when the model judges it relevant to what it is
doing, which is why long-form craft guidance lives here rather than in the
stage prompts. `logs.txt` records which skills were installed.

Safe to delete: it is rebuilt on the next resume.

### `artifact_index.json`

An index over `workspace/data/`, `workspace/results/`, `workspace/figures/`
and — also under the `figures` category — `workspace/report/images/`,
regenerated whenever artifacts change and fed into later stages' prompts so a
stage can find data without guessing filenames. `report/images/` is included
because in markdown mode the report's own figures live beside it rather than in
`workspace/figures/`, and leaving them out would show Stage 07 an empty figure
inventory for the figures it had just made. Written by
[`src/artifact_index.py`](../src/artifact_index.py).

```json
{
  "generated_at": "2026-03-30T18:31:44",
  "artifact_count": 12,
  "counts_by_category": { "data": 3, "results": 6, "figures": 3 },
  "artifacts": [
    {
      "category": "results",
      "rel_path": "results/actor_main.json",
      "filename": "actor_main.json",
      "suffix": ".json",
      "size_bytes": 4211,
      "updated_at": "2026-03-30T18:22:03",
      "schema": {
        "source": "inferred",
        "kind": "object",
        "keys": ["accuracy", "seed", "std"]
      }
    }
  ]
}
```

Any `*.schema.json` sidecar is excluded, and so is every path in
`RECORD_ARTIFACTS`: `results/experiment_manifest.json`,
`results/hypothesis_outcomes.json`, `notes/hypothesis_manifest.json`,
`notes/preregistration.json`, `notes/experimental_protocol.json`,
`notes/report_plan.json`, `notes/research_rounds.json` and
`notes/round_decision.json`. (Only the two under `results/` are ever in the
index's scan range; the `notes/` entries do their work in
`experiment_manifest.json`, which shares the same list.)

These are records *about* the science rather than experimental output. The
manifest is a view of the index, not an entry in it, and counting the
preregistration would make a stage that declared its hypotheses look like a
stage that produced results — measurably: the manifest is rewritten on the way
*into* every stage from 05 on, so counted as output, a Stage 05 that produced
literally nothing scored a third of `artifact_breadth`, as the criterion was
denominated then, off a file whose own body
reads `result_artifact_count: 0`. `is_autor_own_record` is the single rule, read
by both this module and the rubric, so the two cannot drift.

#### Schema metadata

Each artifact carries a `schema` block, from one of two sources:

**Declared** — write a sidecar next to the file, named
`<filename>.schema.json`, and it is used verbatim:

```json
{
  "source": "declared",
  "sidecar_path": "results/actor_main.json.schema.json",
  "definition": { "...": "your schema" }
}
```

Declaring a schema is the cheapest way to make a result file legible to later
stages. Invalid JSON in a sidecar is recorded as `"error": "invalid_json"`
rather than crashing the index.

**Inferred** — otherwise AutoR reads the file and infers a shape:

| Suffix | Inferred `kind` |
| --- | --- |
| `.json` | `object` with up to 20 sorted `keys`, or `array` with `item_count` and `item_keys` |
| `.jsonl` | `jsonl` with `row_count` and the union of keys across rows |
| `.csv`, `.tsv` | `table` with `columns` (the header row, stripped) and `row_count` |
| `.yaml`, `.yml` | `yaml_document` |
| `.parquet` | `parquet_table` |
| `.npz` / `.npy` | `numpy_archive` / `numpy_array` |
| figures | `figure`, plus `format` |
| anything else | `file` |

### `intake_context.json`

Stage 00 output: the original goal, the refined goal, the clarification Q&A
transcript, the ingested resources, and free-form notes.

```json
{
  "goal": "refined goal after clarification",
  "original_goal": "what the user first typed",
  "resources": [
    {
      "source_path": "/home/me/papers/moe.pdf",
      "resource_type": "pdf",
      "dest_dir": "literature",
      "dest_relative": "literature/moe.pdf",
      "description": ""
    }
  ],
  "qa_transcript": [
    { "question": "Which base model?", "answer": "Llama-3-8B" }
  ],
  "notes": ""
}
```

`resource_type` is one of `pdf`, `bib`, `code`, `dataset`, `notes`, `tex`,
`other`, assigned by `classify_resource` from the file suffix (a directory
holding `.py` or `.ipynb` files is `code`, any other directory is `other`).
`dest_dir` is the workspace subdirectory the resource was copied into:
`literature`, `code`, `data`, `notes`, `writing` or `artifacts`.

### `obligations.json`

The obligation ledger: what an *approving* reviewer said a later stage still
owes. Written by [`src/obligations.py`](../src/obligations.py).

Most stages are approved, and an approval used to discard everything the
reviewer noticed. A real reviewer approving a literature survey says "fine, but
you owe me a power analysis at design time" — and then checks. Each obligation
is injected into the prompts of the stages it targets *and* into the review of
those stages, so the reviewer that inherits one is asked whether it was met.

```json
{
  "version": 1,
  "obligations": [
    {
      "obligation_id": "O001",
      "text": "State a power analysis justifying the sample size before running the comparison.",
      "origin_stage": "01_literature_survey",
      "target_stage": "03_study_design",
      "status": "open",
      "deferrals": 0,
      "discharged_by": null,
      "discharge_note": ""
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `obligation_id` | `O001`-style, referenced by the reviewer that discharges it. |
| `text` | The reviewer's condition, verbatim and whitespace-collapsed. Shorter than `MIN_OBLIGATION_CHARS` (20) is dropped: "do better" is not checkable. |
| `origin_stage` | The stage whose approval attached it. |
| `target_stage` | The stage on the hook, or `null`. `normalize_stage_slug` accepts `05`, `5`, `05_experimentation` and the display name, because models reach for the display name and silently degrading that to "any later stage" loses the targeting the reviewer intended. A `null` target applies to **every** stage after `origin_stage`. |
| `status` | `open` or `discharged`. |
| `deferrals` | How many times a stage it applied to was approved without discharging it. Counted on approval only — a refused stage gets another attempt and has not deferred anything. |
| `discharged_by` / `discharge_note` | Which stage's review closed it, and why. |

**Only a reviewer discharges an obligation.** The stage that owes it can do the
work and say so; it cannot mark its own homework. Deferral is allowed and never
silent: the count is shown to every later reviewer. The set is deduplicated on
normalized text and capped at `MAX_OBLIGATIONS` (30), so a reviewer restating
one point cannot inflate the ledger.

Absent unless the run uses the **automated** approval gate — `record_obligations`
and `discharge_obligations` are reached only from the automated reviewer's
decision, so a manual human gate never writes this file.

Both automated gates are shown the ledger, through one renderer:
`AutomatedReviewer._build_review_prompt` calls `format_for_review_prompt` for the
solo reviewer, and `ReviewPanel._context_block` calls the same function for every
seat and for the chair. A panel also *writes* to this file — any seat's
`carry_forward` entries are carried whatever the room decides — but only the
chair's last word discharges anything, and nothing is discharged while a blocking
objection stands. See [the panel's own doc](review-panel.md) for that asymmetry.

### `review_policy.json`

The standing rules the run has learned about its own work. Written by
[`src/review_policy.py`](../src/review_policy.py) whenever a correction is
demanded or an already-given approval is undone, and injected into every
subsequent review prompt. As with obligations, one renderer serves both gates:
`format_policy_for_prompt` is called by `AutomatedReviewer._standing_rules_block`
for the solo reviewer and by `ReviewPanel._standing_rules_block` for every seat
and the chair. Both pass `stage`, which withholds the rules the stage under
review produced in its own earlier attempts — a review that demands anything
records one, so injecting them would raise the bar by a requirement per attempt
and the retry loop could not converge.

```json
{
  "version": 1,
  "rules": [
    {
      "rule_id": "R001",
      "text": "The design lacks a stated power analysis and the sample size is unjustified.",
      "origin_stage": "03_study_design",
      "origin_attempt": 2,
      "source": "refinement"
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `rule_id` | Stable identifier, referenced in the review prompt and the run log. |
| `text` | The correction verbatim, as the reviewer worded it — or, for a rollback, the sentence AutoR writes naming the two stages and the reason. Whitespace-collapsed; shorter than `MIN_RULE_CHARS` (25) is dropped. |
| `origin_stage` / `origin_attempt` | Which review produced the rule. This is what makes the mechanism auditable rather than assertable. A rollback has no attempt to point at and records `0`. |
| `source` | `refinement` for a demanded correction, `rollback` for an approval that later proved wrong. Rollbacks are rendered first in the prompt. |

Absent until the first correction is recorded. Unlike `obligations.json`, this
is **not** an automated-reviewer-only file. Two of `record_correction`'s callers
need a reviewer: `_record_review_correction`, which turns a refusal into a
`refinement` rule, and the cross-model audit, which records a vetoed approval.
The rest do not. `_rollback_and_jump` is reached from the operator typing
`/back <stage>` into the manual gate's feedback prompt, and from choice `2`
("Roll back to an earlier stage") on the recovery menu an attended run on a tty
gets when a stage exhausts its retries; the router records one of its own when a
graph `revisit` re-enters an earlier stage. All three write `source: rollback`
with text well over `MIN_RULE_CHARS`, so a run on the manual gate with no
reviewer at all can carry this file. What is never recorded is an approval that
stood: approvals teach nothing.

Rules are deduplicated on normalized text (casing, punctuation
and stage numbers collapse) and capped at `MAX_RULES` (40), so a reviewer
restating one complaint cannot inflate it. A corrupt file is treated as an empty
policy: the gate falls back to baseline strictness rather than taking the run
down.

### `report_plan_stamp.json`

AutoR's own copy of the three fields in
[`workspace/notes/report_plan.json`](#workspacenotesreport_planjson) that the
agent must not be trusted to write. Written by `stamp_report_plan` in
[`src/report_plan.py`](../src/report_plan.py).

```json
{
  "declared_at": "2026-03-30T13:05:41",
  "digest": "9c1f0b7e...",
  "amendments": [
    {
      "recorded_at": "2026-03-30T18:44:02",
      "reason": "round 1: tune both arms on a held-out development split and re-run",
      "previous_digest": "3ab5c9d1...",
      "new_digest": "9c1f0b7e..."
    }
  ]
}
```

The plan itself has to stay in `workspace/notes/`: the agent writes it, amends
it, and is shown it. But that means the agent also has write access to the
fields that are supposed to prove *when* it was written, and a stamp kept only
there is a receipt the payer prints. `recorded_report_plan_stamp` therefore
reads the previous digest from here, never from the plan file — and the failure
this catches is the ordinary one, not the hostile one. A stage that regenerates
the whole plan from its own template, obeying "do not write `declared_at`,
`digest` or `amendments`", leaves a plan with no header at all. Read from the
file that is indistinguishable from a first declaration, and `declared_at`
silently becomes a post-results timestamp with an empty amendment ledger. Read
from the stamp, it is an amendment, and the plan file is repaired on the spot.

Written when Stage 03 is approved, and again from Stage 06 on for runs that
reach there without passing a Stage 03 approval (`--resume-run`,
`--redo-stage`, a `--project-root` bootstrap). Stamping is **idempotent by
content**: a round that left the plan alone adds no amendment and leaves the
plan file's bytes alone, so carrying a correct plan through a second round does
not manufacture a spurious record of having changed it. Absent until a
`report_plan.json` exists.

### `preregistration_stamp.json`

AutoR's own copy of the frozen hypothesis set. Written by
`_write_preregistration_stamp` in
[`src/preregistration.py`](../src/preregistration.py) at the same moment as
[`workspace/notes/preregistration.json`](#workspacenotespreregistrationjson),
and carrying the same object — `frozen_at`, `frozen_before_stage`,
`source_digest`, `digest`, `hypotheses`, `amendments` — plus one field the
workspace copy does not have:

```json
{
  "repairs": [
    {
      "repaired_at": "2026-03-30T19:11:07",
      "found": "preregistration.json states digest 3bf263f5..., but AutoR stamped 9c1f0b7e..."
    }
  ]
}
```

Every time AutoR had to write its copy back over a workspace file that
disagreed, and what disagreed. The list is kept because the repair is what
destroys the evidence it was needed for: once the stamped record is written over
the workspace copy the two agree again, and the run's own artifacts would
otherwise say the frozen set was never touched. `recorded_preregistration_stamp`
reads this file, never `preregistration.json`, and treats a stamp with no digest
or no hypotheses as absent rather than as an empty freeze.

Absent until a run freezes, which is Stage 04's approval at the earliest.
Deleting it *and* `preregistration.json` reproduces the pre-stamp reset, which
is why `validate_preregistration` also reads the append-only freeze witness in
`logs.txt` — see #203 and `FREEZE_WITNESS_HEADING`.

### `validity_review_stamp.json`

AutoR's own copy of what each adversarial pass raised. Written by
`ValidityReviewer._write_review` in
[`src/validity_review.py`](../src/validity_review.py), at the same moment as the
workspace copy and never separately — a pass that reached
[`workspace/reviews/validity_review_<stage>.json`](#workspacereviewsvalidity_review_stagejson-and-validity_response_stagejson)
and not the run root would be a review nothing can hold anyone to.

```json
{
  "stamped_at": "2026-08-13T11:50:07",
  "reviews": {
    "05_experimentation": {
      "stamped_at": "2026-08-13T11:50:07",
      "reviewed_stage": "05_experimentation",
      "completion": "completed",
      "note": "fake-operator mode",
      "findings": [
        {
          "id": "V1",
          "category": "insufficient_replication",
          "severity": "critical",
          "finding": "The reported comparison rests on a single run of a two-row synthetic split.",
          "why_it_matters": "A single run cannot separate the effect from variance.",
          "what_would_settle_it": "Repeat across at least five seeds and report the spread."
        }
      ]
    }
  }
}
```

One file, one entry per reviewed stage, so Stage 07's obligations do not
overwrite Stage 06's. `completion` is one of `completed`, `crashed` or
`unreadable`: an empty `findings` list under `completed` is a reviewer that
attacked the stage and found nothing, and the same list under the other two is
a pass that never happened, which is the distinction the workspace copy's
`reviewer_failed` flag also carries.

`load_findings` reads this file wherever there is one, so the gate, the prompt
that lists the objections and fake mode's answerer all count the same
population. `validity_review_tamper` compares the *finding records* against the
workspace copy — not the bytes, which never converge, because a restored file
carries a fresh `generated_at` — and reports a dropped id and a rewritten one
apart, since an equal-length rewrite is the cheaper edit and the one a reader of
`logs.txt` is most likely to misread. `validate_validity_response` refuses while
the two disagree, and the next attempt's prompt writes AutoR's record back after
logging what disagreed under `validity_review_restored`.

Absent until a validity review has run, which is Stage 05 at the earliest. A
run resumed from an AutoR that predates this file has no stamp, and
`stamped_review` returning `None` is that state rather than a clean comparison:
there is nothing to compare against, so the workspace copy is authoritative
again, exactly as it was before.

### `stage_cost_ledger.json`

One row per **stage visit** — not per stage, because a backward edge re-runs one
and the second run is a separate purchase against the same budget. Written by
[`src/stage_cost.py`](../src/stage_cost.py): `ResearchManager._run_stage` opens a
`StageCostMeter` on the way in and `append_stage_cost_row` closes it on every way
out, including the way out where the visit raised.

```json
{
  "version": 2,
  "rows": [
    {
      "stage": "05_experimentation",
      "stage_number": 5,
      "visit": 1,
      "started_at": "2026-08-16T09:14:02",
      "wall_seconds": 4471.2,
      "attempts": 3,
      "polish_rounds": 0,
      "operator_invocations": 3,
      "review_invocations": 3,
      "auto_skipped": true,
      "outcome": "auto_skipped",
      "exhausted": true,
      "attempts_with_a_recorded_cause": 3,
      "failure_census": { "reviewer_refused": 3 },
      "distinct_failures": 1,
      "max_repeat": 3,
      "max_consecutive_repeat": 3,
      "repeated_failure": true,
      "dominant_failure": "reviewer_refused",
      "failures": [
        {
          "digest": "732e18576fdc",
          "kind": "reviewer_refused",
          "count": 3,
          "first_attempt": 1,
          "last_attempt": 3,
          "example": "The manifest states no falsifiable decision rule."
        }
      ],
      "attempt_digests": [
        { "attempt": 1, "kind": "reviewer_refused", "digest": "732e18576fdc" },
        { "attempt": 2, "kind": "reviewer_refused", "digest": "732e18576fdc" },
        { "attempt": 3, "kind": "reviewer_refused", "digest": "732e18576fdc" }
      ],
      "note": "auto-skip budget spent",
      "call_cost": {
        "result_events": 6,
        "priced_events": 6,
        "input_tokens": 412,
        "cache_creation_input_tokens": 1904331,
        "cache_read_input_tokens": 44712008,
        "output_tokens": 228104,
        "total_cost_usd": 41.87
      }
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `version` | `STAGE_COST_LEDGER_VERSION`. Bumped when a row grows or loses a field, so a reader that predates the change says so instead of reading a missing key as a zero. |
| `visit` | `1` the first time the run entered this stage, `2` for the visit a backward edge produced. Assigned by `append_stage_cost_row` from the rows already on disk, never by the meter, so it is right across a resume and across two visits separated by half a run. |
| `wall_seconds` | Monotonic clock across the visit. |
| `attempts` | Iterations of the attempt loop. **Not the `--max-attempts` spend** — a polish round is an iteration the ceiling does not charge for, so the spend is `attempts - polish_rounds`. |
| `polish_rounds` | Improvement rounds, each of them one of `attempts`. |
| `operator_invocations` · `review_invocations` | Backend launches the manager itself dispatched, to do the work and to judge it. A reviewer's internal verdict re-ask and a panel's fan-out to its seats happen below that boundary and are deliberately not counted. |
| `outcome` | One of `OUTCOMES`: `approved`, `auto_skipped`, `human_skipped`, `routed_to_deliverable`, `rolled_back`, `aborted`, `bypassed`, `raised`, `unknown`. `unknown` is kept rather than defaulted to `approved`, so a new exit path shows up as an unnamed one instead of as a success. |
| `auto_skipped` | Whether this visit spent a slot from the run's `--max-auto-skips` pool. Set by the skip and never cleared by the route that refines it into `routed_to_deliverable`, because the slot was still spent. |
| `attempts_with_a_recorded_cause` | How many of `attempts` produced a census entry. A visit that settled reads one below `attempts` — the iteration that settled it did not fail; a wider gap is a path that consumed budget and recorded nothing. |
| `failure_census` | Counts per kind, in `FAILURE_KINDS` order. |
| `max_repeat` · `max_consecutive_repeat` | The most times one failure occurred anywhere, and the longest unbroken run of it. Both, because "the same objection eight times running" and "two objections alternating" are different situations and only the second number tells them apart. |
| `failures` | One entry per distinct failure, most frequent first, ties broken on first appearance. `example` is the first `FAILURE_EXAMPLE_CHARS` of the reason. |
| `attempt_digests` | Every recorded cause in the order it happened. `failures` loses the ordering, and a rule about a failure repeating *consecutively* cannot be evaluated without it. |
| `call_cost` | What the backend charged for this visit. `src/call_cost.py` declares the fields; the two counters say how much of the visit the numbers cover, and every measured field is `null` rather than `0` when nothing reported it. |

**`failure_census` keys** are the `FAILURE_KINDS`: `reviewer_refused`,
`cross_review_vetoed`, `human_refused`, `validators_refused`, `backend_crashed`,
`backend_unreadable`, `backend_unsupported`, `crux_raised`, `polish_round` and
`unclassified_refusal`. The last exists so an attempt whose kind this module does
not recognise is counted rather than dropped — a census that silently omits what
it cannot name is the defect the ledger was written to remove, one level up. The
three `backend_*` kinds mirror `AutomatedReviewer.is_degraded_verdict`, and
`classify_refusal` imports its reason prefixes from `src/approval_agent.py`
rather than re-spelling them, so the two readers cannot drift.

**Stages the run never entered get a row too** (`outcome: bypassed`, zeroes
everywhere a measurement would go): `_route_to_deliverable` steps over them into
the run's not-completed list, and a ledger holding only the stages the run paid
for is flatter than the run.

**The tokens and the dollars**, wired rather than scraped. This section used to
say the row carried neither, and the reason it gave was a missing path: the
backend emits a `{"type": "result"}` event carrying `total_cost_usd` and a
`usage` block, `logs_raw.jsonl` keeps every one, and nothing carried it to the
manager. That path now exists — `ClaudeOperator._run_streaming_command` prices
the stream, `OperatorResult.call_cost`, `ReviewDecision.call_cost` and
`ValidityReviewOutcome.call_cost` carry it, and `StageCostMeter.note_call_cost`
charges it to the open visit. Nothing reads the raw log a second time, which
matters because there are two traps in it and a second reader is a second chance
to hit either.

*`total_cost_usd` is per call and the values sum.* It is not monotone within a
session id, so no cumulative reading survives.
`tools/log_cost_census.py` prints both readings side by side.

*`input_tokens` is the uncached remainder only.* All four usage fields are
recorded separately and any single total is printed beside the names of the
fields it sums, because reading `input_tokens` as "tokens used" understates a
cached run by five orders of magnitude.

*Absent is not zero.* A backend that reports nothing leaves every measured field
`null` and the terminal report prints `not measured`. The fake operator makes no
call at all and must not publish `$0.00`; a stage the run stepped over
(`outcome: bypassed`) is unmeasured for the same reason, and `$0.00` there would
be a derived claim rather than an observation.

*And nothing decides on it.* The fields may appear in this record, in
`summarize_stage_cost` and in `format_run_cost_report`, and in no condition
anywhere under `src/` — no comparison, no boolean operator, no `if`, no
comprehension filter, no `sorted` key, no `max`.
`tests/test_cost_is_recorded_and_unread.py` asserts that over the syntax of
every module, and asserts it twice for the run supervisor: once over its syntax
and once by replaying its rulings against two ledgers that differ only in what
they cost.

Nothing here is a gate: the ledger refuses nothing. It is at the run root rather
than under `workspace/` for the same reason the stamps are — the operator runs
with `cwd=run_root` and every stage prompt directs it at `workspace/`, so a run's
account of what it spent must not sit where the party whose spending it records
is being sent to write. A copy also goes into `logs.txt` under the
`stage_cost_ledger` heading, one line per visit and then the totals, on both the
way out of a completed run and the abort branch. That copy carries the attempts,
the wall clock and the failure census and **not** the money: the tokens and the
dollars go to the terminal once, from `ResearchManager._report_run_cost`, and to
no file at all. `workspace/report/` and the PDF do not change.

Absent until the first stage visit closes. A corrupt or unwritable ledger is
never fatal: `read_stage_cost_ledger` returns `[]` and `append_stage_cost_row`
returns `False`, because a stage that produced good work must not be lost
because the account of it could not be written.

### `logs.txt` and `logs_raw.jsonl`

`logs.txt` is the human-readable workflow log: stage starts, attempts,
validation failures, approvals, rollbacks, aborts. Read this first when
something went wrong.

`logs_raw.jsonl` is one JSON object per line, the raw `stream-json` event
stream from the backend — every tool call the agent made, in order. This is
the ground truth for "what did it actually do", and it is what the Studio
session trace renders.

---

## Directories

### `stages/`

- `<slug>.tmp.md` — the current draft, rewritten on each attempt.
- `<slug>.md` — the approved summary. Only appears after you approve.
- `<slug>.skip_stub.md` — only when an auto-skipped stage's last draft was
  *rescued*. A stage that burns its attempt budget unattended is normally
  replaced by a short stub saying the work was not done; when the final draft
  passes the same markdown and artifact gates an approval requires, that draft
  is promoted instead and the stub is kept here rather than thrown away. It is
  still not an approval — the manifest keeps saying `skipped` — and the skip
  reason records that a validated draft was preserved and nobody reviewed it.

The required shape of `<slug>.tmp.md` and `<slug>.md` is the
[stage contract](stage-contract.md).

### `prompt_cache/`

The exact prompt text sent to the backend, one file per attempt:

| Filename | Written by |
| --- | --- |
| `<slug>_attempt_NN.prompt.md` | a normal stage attempt |
| `<slug>_attempt_NN_repair.prompt.md` | a repair pass after a malformed summary |
| `<slug>_route.prompt.md` | the [router](self-improvement.md) asking the agent which move to take |
| `<slug>_validity_review.prompt.md` | the adversarial reviewer after Stage 05 and Stage 06 |
| `09_benchmark_report.prompt.md` | the ResearchClawBench report synthesiser (`rcb_agent.py` only) |

Every *reviewer-style* call — the solo gate, every panel seat, every crux voice,
every ideation proposer — goes through `AutomatedReviewer.run_prompt` and lands
as `<slug>_<label>_attempt_NN.prompt.md`, so the table above is not the whole
set. Every `label` the code passes, and nothing else:

| `label` | Written by |
| --- | --- |
| `review` | the solo automated gate |
| `panel_<seat>_r<N>` · `panel_chair` | each seat of a [review panel](review-panel.md), per round, and the chair's synthesis |
| `crux_<voice>` · `crux_brief` · `crux_resolve` | a [crux deliberation](deliberation.md) |
| `ideate_<lens>` · `ideate_score` | the [ideation panel](ideation-panel.md)'s proposers, one per lens, and its pool scorer |
| `review_verdict` · `panel_<seat>_verdict` · `panel_chair_verdict` | `parse_with_retry`'s single re-ask, present only when that reviewer's first answer could not be parsed |

The same labels name the per-call records in `operator_state/`. The three
`*_verdict` files are the useful tell: their presence means a verdict came back
unreadable and was asked for again.

One prompt is missing from this directory, and it is one that can change what a
stage did: the cross-model audit's. `CrossReviewer.build_prompt` builds its text
and hands it straight to the model API, and nothing in
[`src/cross_reviewer.py`](../src/cross_reviewer.py) writes to `prompt_cache/`,
`operator_state/` or `logs_raw.jsonl`. When that audit vetoes an approval and
sends the stage back for another attempt, `logs.txt` records the verdict and
`review_policy.json` records the rule it produced — but the text that produced
both is not kept anywhere.

Every prompt that *is* here is the exact text the backend was given, and the run
reads it from disk rather than from memory. How it reaches the CLI differs by
backend, which matters if you are
reproducing a call by hand: the Claude operator passes the path by reference
(`_build_cli_command` emits `-p @<prompt_path>`), while the Codex operator reads
the file, rewrites every occurrence of the run root to the temp-directory
symlink it invokes under (`_rewrite_prompt_for_alias`), and pipes the result on
stdin against a bare `-`. Under `--operator codex` the prompt file's path is
never handed to the CLI, and what is on disk is the pre-rewrite text.

### `operator_state/`

| File | Contents |
| --- | --- |
| `<slug>.session_id.txt` | the backend session ID for that stage |
| `<slug>.session.json` | `session_id`, plus `broken` / `broken_reason` / `updated_at` when a resume was refused — so the next attempt starts a fresh conversation instead of retrying a dead one |
| `<slug>.attempt_NN.json` | per-attempt state: `status`, `mode` (`start`/`resume`), session ID, prompt path, the literal `command` argv, `exit_code`, stdout/stderr excerpts, stream metadata, timestamps |
| `<slug>.<label>_attempt_NN.json` | the same record for a reviewer-style call, under the same labels as the prompt files above |
| `<slug>.started_at.txt` | the freshness cutoff used by the [artifact gate](stage-contract.md#freshness-checks) |
| `<slug>.attempt_count.txt` · `<slug>.polish_count.txt` | attempts and improvement rounds this stage has spent, persisted because a stage can be entered more than once (a resume, a rollback, a graph revisit) and the attempt number keeps counting up across all of them |
| `<slug>.pending_feedback.txt` | opt-in revision feedback injected into the **first** attempt's prompt rather than waiting for attempt 2. Written by the Studio's feedback action, or by any caller that drops one there; absent on a plain CLI run, where behaviour is unchanged |
| `mcp_config.json` | the `--mcp-config` payload handing the agent an `mcp__autor-search__web_search` tool, written whenever the [MCP search server](configuration.md#web-search-optional) is active. Kept in the run rather than a temp file so a run can say what tools its agent was given, not only what it was told. Claude operator only — the Codex adapter takes no MCP config |

`<slug>.attempt_NN.json` records the literal argv used, which is most of what
you need to reproduce a failed attempt by hand. On the Codex backend it is not
all of it: the argv ends in a bare `-` and the prompt arrives on stdin, so
replaying that command means feeding it the prompt file yourself.

### `handoff/`

One `<slug>.md` per completed stage: a compressed view carrying only
`Objective`, `Key Results`, `Files Produced`, and the `Decision Ledger`.

At most the four most recent handoffs before the current stage are injected
into a prompt, which is what keeps long runs from growing their prompts without
bound. The `Decision Ledger` section is stripped from *that* injection because
it travels separately: `build_decision_ledger_context` collects the ledger
sections from **every** prior handoff into their own channel, broadcast to every
stage from 02 on. A locked decision binds every stage after it, so trimming it
to the last four would be the wrong four.

### `evolution/`

Present on a default run. The champion ratchet is on unless you pass
`--no-evolve` (`evolve_measure` defaults to `true`; it costs no backend call),
and `stage_graph.json` is written on every run including `--stage-graph linear`,
because the walk is driven by a graph either way.

Outside `workspace/` on purpose: this records *how* the run reached its answer,
not part of the answer, and a benchmark export that swept it up would ship the
losing drafts alongside the report.

| Path | Contents |
| --- | --- |
| `stage_graph.json` | The walk. Top level: `path`, `route` (the visited slugs joined by `->`), `max_steps`, `max_visits`, `halted_because` and `halted_kind` — the last being what tells `--final-stage` (`pruned`, a completion) apart from a spent budget (`steps`/`visits`, a halt). Each visit in `path`: the stage, when it was entered and left, the move chosen out of it, its kind, the stated reason, what AutoR would have chosen, whether the agent chose it, the rubric total at the time, **the targets that were live at the moment of choosing (`offered`) and why the rest were not (`blocked`, target → `guard`/`visits`/`steps`/`pruned`/`concluded`/`budget`)**, whether the move bypassed the router entirely (`bypassed` — a `/back`, a rollback, or a research-round decision; these are counted but never enter the archive's edge observations, because nothing chose between anything), **which party ended the decision before the agent was asked (`preempted_by`, `supervisor` or empty)**, and the research round this visit closed (`closed_round`). The choice set cannot be reconstructed afterwards: re-evaluating a guard needs the workspace as it was at that moment. |
| `improvement_ledger.jsonl` | One row per measured round: stage, attempt, per-criterion scores, delta against the champion, the verdict (`first`, `promoted`, `frontier`, `regressed`, `directed`, `verdict_drift`), whether the draft was reverted, and the verdict digest. |
| `routing_refusals.jsonl` | Every agent routing choice AutoR refused, why, and which edge it fell back to. |
| `summary.json` | The settled champion score per stage. This is what the cross-run archive reads. |
| `<stage_slug>/champion.md` · `champion.json` | The best-scoring draft of that stage and its score. |
| `<stage_slug>/frontier.json` | Non-dominated candidates, kept for merge rounds. |
| `<stage_slug>/candidates/attempt_NN.md` · `.json` | Every candidate measured, **including the ones that lost**. A discarded draft is the only evidence that the ratchet discarded anything. |

See [Recursive Self-Improvement](self-improvement.md).

### `workspace/`

| Directory | Holds | Gated at |
| --- | --- | --- |
| `literature/` | reading notes, survey tables, `sources.json`, `claims.json` | Stage 01 |
| `code/` | runnable scripts, configs, method implementations | — |
| `data/` | machine-readable datasets, manifests, splits, loaders | Stage 03+ |
| `results/` | metrics, predictions, ablations, `experiment_manifest.json` | Stage 05+ |
| `figures/` | plots, diagrams, paper figures | Stage 06+ |
| `report/` | `report.md` and `images/*.png` | Stage 07+ (markdown mode) |
| `writing/` | `main.tex`, `sections/*.tex`, `.bib`, tables | Stage 07+ (latex mode) |
| `artifacts/` | compiled PDF, `build_log.txt`, `self_review.json`, `citation_verification.json`, `claim_provenance.json`, `deliverables_coverage.json`, the format's review JSON, packaged deliverables | Stage 07+ |
| `reviews/` | readiness checklists, threats to validity, critique notes, the feature ledgers (`scorecard.*`, `effort.json`, `deliberations.json`, `comment_ledger.json`, `panel/`), `validity_review_*.json` / `validity_response_*.json` | Stage 08+ |
| `notes/` | supporting notes, `report_plan.json`, `hypothesis_manifest.json`, `preregistration.json`, `experimental_protocol.json`, `research_rounds.json` | no directory gate; the individual files are gated from Stage 03 on |
| `bootstrap/` | the `--project-root` scan, all of it: `project_state.json`, `experiment_inventory.json`, `writing_state.json`, `stage_assessments.json`, `scan_metadata.json`, `bootstrap_summary.md` | — |
| `profile/` | the `--paper-corpus` scan — derived researcher profile and style notes: `research_profile.json`, `citation_neighborhood.json`, `style_profile.json`, `corpus_manifest.json`, `style_notes.md`, `bootstrap_summary.md` | — |

The two scans do not share a directory. `--project-root` is the only scan that
writes `bootstrap/`: `save_project_bootstrap` emits all six files there in one
call, before the bootstrap stage runs. It is not the last writer, though.
`src/prompts/project_bootstrap.md` points the bootstrap agent at
`{{WORKSPACE_BOOTSTRAP_DIR}}` and asks it for four of those six —
`stage_assessments.json`, `experiment_inventory.json`, `writing_state.json` and
`bootstrap_summary.md` — so from that stage's approval on, four of the six hold
whatever the agent wrote. AutoR relies on exactly that for one of them:
`_run_project_bootstrap` re-reads `load_stage_assessments` after approval and
prefers it to the scan's own list. The consequence worth knowing is for the
other: `format_project_context_for_prompt` puts `bootstrap_summary.md` above its
assessment list, and the template asks for 300-500 words of prose there, so the
per-stage readings in that section are not guaranteed to survive the bootstrap
stage — which is why the list under it is never narrowed. The split is pinned by
`test_the_template_hands_the_agent_four_of_the_six_files_the_scan_wrote`: the two
the template leaves alone are `project_state.json` and `scan_metadata.json`, and
the second of those is where the re-entry stage lives.

`--paper-corpus` writes nothing to
`bootstrap/`; its whole output set goes to `profile/`, and it gets there a
different way — `src/prompts/bootstrap.md` points the agent at
`{{WORKSPACE_PROFILE_DIR}}` and asks it for `research_profile.json`,
`citation_neighborhood.json`, `style_profile.json`, `style_notes.md` and
`bootstrap_summary.md`, and `missing_bootstrap_profile_artifacts` then refuses
to approve the bootstrap stage while any entry of `_REQUIRED_PROFILE_FILENAMES`
is missing from `workspace/profile/`. Those two sets are not the same set:
`_REQUIRED_PROFILE_FILENAMES` also holds `corpus_manifest.json`, which the
prompt never mentions and which no live code path writes — `save_bootstrap_result`
is its only writer and nothing outside the tests calls it. The gate is therefore
holding the bootstrap stage on a file neither the prompt nor AutoR produces; when
it refuses, it names the file in the refinement feedback, and that feedback is
the only place the agent is ever asked for it. `bootstrap_summary.md` is the one
filename both scans produce, each in its own directory.

The "gated at" column says from which stage `validate_stage_artifacts` starts
refusing a stage over that directory. Do not read it as one mechanism: only four
of the rows are directory-level counts, and the rest check named files.

- **Counted.** `data/` from Stage 03, `results/` from 05 and `figures/` from 06
  fail when `count_in` finds no file carrying one of that category's suffixes
  (`.json .jsonl .csv .tsv .parquet .yaml .yml` for data, plus `.npz`/`.npy` and
  minus the YAML pair for results, `.png .pdf .svg .jpg .jpeg` for figures).
  `reviews/` from 08 fails when the directory holds no file at all, of any
  kind. Stages 03, 06 and 08 additionally require that at least one such file
  was written during the current stage execution — the count alone would pass on
  a file an earlier stage left behind.
- **Named files, not a count.** `literature/` at Stage 01 is
  `validate_literature_evidence` over `sources.json` and `claims.json`. A
  directory holding fifty reading notes and neither of those two fails it, and
  its errors are about IDs and cross-references, not about how much is there.
- **Per-file existence, then freshness.** `report/`, `writing/` and `artifacts/`
  at Stage 07+ are checked file by file rather than counted, and which files
  depends on the output format: `report.md` and `report_review.json` in markdown
  mode; `main.tex`, `sections/*.tex`, a bibliography, a compiled PDF,
  `build_log.txt` and `layout_review.json` in latex mode;
  `citation_verification.json` and `self_review.json` in both. Do not read that
  as the whole set — further per-file gates hang off the same Stage 07 branches
  (`claim_provenance.json` and `deliverables_coverage.json` in both formats), and
  the `stage.number >= 7` branches of `validate_stage_artifacts`
  are where the current list lives. Freshness is narrower still: at Stage 07
  itself the files named in that branch's `stage7_required_files`, plus the PDF
  and the section sources in latex mode, must be newer than the stage's start
  marker. The bibliography is not among them, so one an earlier stage wrote
  satisfies Stage 07.

`results/` is the one row where both apply: the count, and `experiment_manifest.json`
by name. Individual files inside a directory carry their own content gates on
top of all this; those are the section below.

A few more AutoR-written things live under `workspace/` and are not gates:

- `writing/manifest.json`, rebuilt from the artifact index every time the
  Stage 07 prompt is composed.
- The `paper_package/` and `release_package/` bundles that Stage 07 (latex mode)
  and Stage 08 emit into `writing/`, `artifacts/` and `reviews/`.
- Under `--research-diagram`, a generated method illustration:
  `report/images/method_overview.png` with a reference injected into `report.md`
  in markdown mode, or `figures/method_overview.jpg` in latex mode. Skipped with
  a log line rather than failing when the method section is too short to work
  from.
- Under `--fake-operator`, a set of stand-in files (`data/fake_dataset.json`,
  `notes/autor_intro.md`, `reviews/readiness_review.json` and similar) that
  exist only to exercise the gates locally. They are not part of a real run.

---

## Validated JSON files

Most of these AutoR parses and rejects rather than merely counting, and where a
section names a validator, the schema below is what that validator actually
requires. **A file's gate is not always a function named after it**, so do not
read "no validator of its own" as "unchecked": `hypothesis_manifest.json` is
refused from Stage 05 on by `validate_preregistration`, through the frozen
preregistration derived from it. Where a file really is unchecked, its own
section says so — `self_review.json` is gated on existence
alone, and `deliberation_request.json` is read leniently and never refuses a
stage. The feature ledgers — `scorecard.json` and
`scorecard.md`, `effort.json`, `deliberations.json`, `comment_ledger.json`,
`idea_pool.json` and everything under `panel/` — are written by AutoR and read
back by AutoR, and have no validator at all; the field tables below describe
what is written, not a contract anything enforces.

### `workspace/literature/sources.json`

```json
{
  "sources": [
    { "source_id": "S1", "title": "Attention Is All You Need", "path": "literature/vaswani2017.pdf" }
  ]
}
```

Required per entry: a unique non-empty `source_id`, a non-empty `title`. A
bare top-level array is also accepted.

### `workspace/literature/claims.json`

```json
{
  "claims": [
    {
      "claim_id": "CL1",
      "statement": "Attention sinks emerge within the first 2k training steps.",
      "source_ids": ["S1", "S4"]
    }
  ]
}
```

Required per entry: a non-empty `claim_id`; claim text under `statement` **or**
`claim`; at least one `source_ids` entry, and **every referenced ID must exist
in `sources.json`**.

Validated by `validate_literature_evidence` in
[`src/evidence_ledger.py`](../src/evidence_ledger.py).

### `workspace/results/experiment_manifest.json`

Generated by AutoR from the artifact index — you do not normally hand-write
it, but Stage 05+ fails if it is missing or malformed.

```json
{
  "generated_at": "2026-03-30T18:31:44",
  "ready_for_analysis": true,
  "result_artifacts": [
    { "rel_path": "results/actor_main.json", "schema": { "source": "inferred", "...": "..." } }
  ],
  "code_artifacts": ["code/train.py", "code/eval.py"],
  "note_artifacts": ["notes/setup.md"],
  "summary": {
    "result_artifact_count": 6,
    "code_artifact_count": 2,
    "note_artifact_count": 1
  }
}
```

Required: non-empty `generated_at`; boolean `ready_for_analysis`; all three
`summary.*_count` keys; and every `result_artifacts` entry must have a
non-empty `rel_path` and a `schema` object. Non-integer values you add under
`summary` are preserved across regeneration rather than dropped.

Validated by `validate_experiment_manifest` in
[`src/experiment_manifest.py`](../src/experiment_manifest.py).

### `workspace/notes/hypothesis_manifest.json`

Parsed out of the Stage 02 summary's typed subsections.

```json
{
  "generated_at": "2026-03-30T12:40:11",
  "theoretical_propositions": [
    {
      "id": "T1",
      "type": "theoretical_proposition",
      "statement": "...",
      "derived_from": "",
      "depends_on": "",
      "verification_needed": "",
      "decision_rule": "",
      "status": ""
    }
  ],
  "empirical_hypotheses": [],
  "paper_claims": []
}
```

Every empirical hypothesis must carry a `decision_rule` — what result would count
as support, and what would count as refutation — stated before any experiment
runs. A hypothesis with no decision rule cannot come out negative, which makes
"falsifiable" a word rather than a property, and Stage 05 refuses the run.

The gate is `validate_preregistration`, which runs from Stage 05 on and reaches
this file three ways: it refuses a run that has no `hypothesis_manifest.json` at
all, it refuses a frozen empirical hypothesis carrying no decision rule, and it
compares `hypothesis_manifest_digest` of this file against the digest the
[preregistration](#workspacenotespreregistrationjson) froze.

### `workspace/notes/research_rounds.json`

Stages 03-06 form a **research round**: design, implement, experiment, analyse.
Stage 06 closes it with a decision, and the ledger accumulates one entry per
round.

```json
{
  "updated_at": "2026-03-30T18:52:10",
  "rounds": [
    {
      "round": 1,
      "decision": "refine_design",
      "rationale": "The comparison was confounded by tuning on the reporting split.",
      "what_we_learned": "The gap disappears once tuning and reporting use different splits.",
      "what_changes_next": "Tune both arms on a held-out development split and re-run.",
      "negative_result": false,
      "hypothesis_verdicts": {"H1": "refuted"},
      "recorded_at": "2026-03-30T18:52:10",
      "acted_on": true,
      "budget_note": "",
      "reopens_round": 0
    }
  ]
}
```

| decision | what happens |
| --- | --- |
| `converged` | continue to Stage 07 |
| `refine_design` | same hypotheses, next round restarts at Stage 03 |
| `new_hypothesis` | next round restarts at Stage 02; the preregistration records an amendment |
| `abandon` | the run stops, and Stage 07 refuses to write up a question the run declared unanswerable |

An abandonment is not permanent, but overruling it has to be said out loud: a
later round sets `reopens_round: <N>` naming the abandoned round it overrules,
and until something does, `validate_round_decision` refuses every stage past 06.

There is no `continue`: a round that wants another one has to say what would
change, because repeating a design without changing what it got wrong produces
the same result at full cost.

**`converged` is refused when no preregistered hypothesis came out supported**,
unless the round sets `negative_result: true`. A run whose contribution is the
refutation is a real result and should say so plainly; a run that quietly
proceeds to write a paper about nothing is the default failure without this
rule.

`acted_on: false` with a `budget_note` means the round wanted to iterate and
`--max-rounds` was spent. The run continues to writing, but the record says it
stopped rather than converged — a distinction the ledger would otherwise lose.

Iteration is off by default (`--max-rounds 1`) because rounds multiply the cost
of an unattended run. The decision is recorded either way.

Stage 06's pending declaration lives at `workspace/notes/round_decision.json`
and is consumed when the round closes, so a later round cannot inherit an
earlier one's conclusion.

Validated by `validate_round_decision` in
[`src/research_rounds.py`](../src/research_rounds.py).

### `workspace/notes/preregistration.json`

The hypothesis set, frozen. Written when Stage 04 is approved — design settled,
code written, nothing measured — and again lazily on the way into any stage from
05 on, for runs that arrive by resume, `--redo-stage`, or a `--project-root`
bootstrap. `freeze_preregistration` never overwrites, so the second call on a
run that already froze is a no-op.

```json
{
  "frozen_at": "2026-03-30T14:02:55",
  "frozen_before_stage": "05_experimentation",
  "source_digest": "b897fe8c...",
  "digest": "3bf263f5...",
  "hypotheses": [
    {"id": "H1", "type": "empirical", "statement": "...", "decision_rule": "...", "verification": "..."}
  ],
  "amendments": []
}
```

`source_digest` hashes the id, type, statement and decision rule of every entry
in `hypothesis_manifest.json`, deliberately ignoring the timestamp and the
self-declared `status` — rewriting Stage 02 without changing a statement is not
tampering. From Stage 05 on — the same gate that requires the
frozen file to exist at all — a manifest whose digest no longer matches, a
hypothesis edited after results existed, fails validation unless an amendment is
on record.

Hypotheses may be revised. A rollback to Stage 02 is a legitimate reason, and
re-running Stage 02 appends an `amendments` entry carrying the reason and the
superseded digest. What is refused is a revision with no record of having
happened, because that is indistinguishable from a hypothesis written to fit
the result.

Validated by `validate_preregistration` in
[`src/preregistration.py`](../src/preregistration.py).

### `workspace/notes/experimental_protocol.json`

What would count as having shown the hypothesis. Declared in Stage 03, before
any experiment runs, and enforced from Stage 05.

```json
{
  "declared_at": "2026-03-30T13:20:04",
  "primary_metric": "held-out accuracy",
  "planned_seeds": 5,
  "baselines": [
    {
      "name": "long-context prompting",
      "why_competent": "the standard approach the method has to beat to matter",
      "tuning_budget": "same prompt-search budget as the method: 20 configurations"
    }
  ]
}
```

- The **primary metric** is named in advance. Choosing the metric after seeing
  the results is the same defect as choosing the hypothesis after seeing them.
- Every baseline needs `why_competent` and a `tuning_budget` matching the
  method's. Beating a baseline nobody tried to make strong measures the effort
  split, not the method — and that asymmetry is invisible in the final number.
- `planned_seeds` is how many independent runs the comparison uses.

Validated by `validate_experimental_protocol` in
[`src/experimental_protocol.py`](../src/experimental_protocol.py).

### `workspace/notes/report_plan.json`

Which figures the report will carry, and which claim each one settles — chosen
at Stage 03, before any result exists. The same discipline as the
preregistration, applied to what the reader is shown: a figure set assembled at
the end out of whatever the run happened to produce is evidence chosen after
seeing it, one level up.

```json
{
  "declared_at": "2026-03-30T13:05:41",
  "digest": "9c1f0b7e...",
  "no_figures_because": "",
  "task_outputs": [
    {"stated": "upper limits on the self-interaction coupling", "covered_by": "figure:1", "why_not": ""},
    {"stated": "a mass exclusion band", "covered_by": "number:0", "why_not": ""}
  ],
  "amendments": [],
  "figures": [
    {
      "slot": 1,
      "filename": "coupling_limits.png",
      "supports": ["H1"],
      "shows": "95% CL coupling limit (GeV^-1) against ULB mass (eV), log-log, with the prior bound overlaid",
      "if_supported": "our band sits below the prior bound across the whole mass range",
      "if_refuted": "the two bands overlap and no improvement is visible",
      "source_artifact": "results/coupling_scan.json",
      "dropped_because": ""
    }
  ],
  "headline_numbers": [
    {"quantity": "best-fit coupling upper limit", "unit": "GeV^-1", "source_artifact": "results/coupling_scan.json"}
  ]
}
```

**AutoR owns the header, the agent owns the body.** `declared_at`, `digest` and
`amendments` are written by `stamp_report_plan` and mirrored to
[`report_plan_stamp.json`](#report_plan_stampjson); the validators ignore all
three, because asking a language model for a sha256 is a wish rather than a
gate. The agent writes `figures`, `headline_numbers`, `task_outputs` and
`no_figures_because`.

Three gates hang off it, deliberately at three different stages:

| From | What it checks | Function |
| --- | --- | --- |
| Stage 03 | Shape — held at the stage that writes it, so a plan-less design is refused while the design can still change | `validate_report_plan` |
| Stage 06 | Every live slot's and headline number's `source_artifact` resolves to a non-empty file, checked while a stage that could still compute it exists | `validate_report_plan_sources` |
| Stage 07 (markdown only) | Every planned slot was published under `report/images/` **and** referenced from `report.md`, or dropped on the record | `validate_report_plan_coverage` |

What the shape gate holds, and why each rule is shaped the way it is:

- **Slots are a ranking.** They must be unique and contiguous from 1, so the
  weakest figure is identifiable now rather than at export. `filename` is a bare
  filename (it is the join key against the published report) and, in markdown
  mode, must be `.png`.
- **Every figure names a claim no other figure carries.** Cite an id from
  `hypothesis_manifest.json`, or `exploratory:<slug>` for a question the run did
  not preregister. This is the one rule that pushes the figure count *down*: a
  run that cannot name a distinct claim for slot 5 has no slot 5. Nothing here
  ever asks for *more* figures — the only count refusal is "more than
  `MAX_REPORT_FIGURES`", and only in markdown mode, because that is a ceiling
  and a gate that restated it as a goal would have turned it into a quota.
- **`if_supported` must differ from `if_refuted`.** A figure whose two branches
  are one sentence cannot come out either way, so it carries no claim. Trivially
  defeated by inserting "not", and that is fine: the guard's job is to make the
  empty move cost a written sentence and put it where a reviewer reads it.
- **`source_artifact` is a workspace-relative path under `results/`, `data/` or
  `outputs/`.** `notes/` is deliberately excluded — a figure computed from a
  note is a figure computed from prose.
- **The length floors** (40 characters on `shows`, 20 on each branch and on
  `dropped_because`) are floors under *a sentence was written*, nothing more.
  Whether a figure is a good figure is the reviewer's judgement; a gate that
  tried to measure it would only be measuring length.
- **A plan with no figures is unusual, not wrong** — three of the forty
  ResearchClawBench tasks have no image criterion at all. Set
  `no_figures_because` to the reason instead, in at least 40 characters.
- **`dropped_because` records a slot abandoned once the results were in.** A
  slot dropped in the same plan that declares it is refused: five slots with
  four born dropped reads as a five-slot plan and commits to one.
- **`headline_numbers` is required and capped at `MAX_HEADLINE_NUMBERS` (8).**
  Each needs a `quantity`, a `unit` (`dimensionless` and `count` are units; an
  empty string is not) and a `source_artifact`. A result the prose never puts a
  number on is a result the reader has to take on trust; a list of everything
  measured is not a set of headline numbers.
- **`task_outputs`** answers the task description item by item — `covered_by` is
  `figure:<slot>`, `number:<index>` (zero-based into `headline_numbers`),
  `prose`, or `not_attempted` with a `why_not` of at least 20 characters. A
  deliverable the task named and the report never mentions is the cheapest score
  there is to lose. An empty `task_outputs` is refused outright.

The Stage 07 gate also flags a lead figure the report first references beyond
10,000 characters: the benchmark's scorer passes only `report_text[:10000]` when
grading an image criterion, so the argument for the report's own highest-ranked
figure would land outside what is read. Only the first slot is held to it.

Written by [`src/report_plan.py`](../src/report_plan.py).

### `workspace/results/hypothesis_outcomes.json`

Stage 06's verdict on every preregistered hypothesis.

```json
{
  "generated_at": "2026-03-30T18:11:02",
  "preregistration_digest": "3bf263f5...",
  "outcomes": [
    {
      "id": "H1",
      "verdict": "refuted",
      "rationale": "the gap was 2 points, below the rule's 8",
      "evidence": ["results/main_metrics.json"],
      "statistics": {"n_seeds": 5, "dispersion": 0.012, "dispersion_type": "std"}
    }
  ],
  "exploratory_findings": [{"statement": "...", "evidence": ["results/..."]}]
}
```

- Every preregistered empirical hypothesis needs exactly one entry. A hypothesis
  the experiments never reached is `not_tested`; omitting it is refused, because
  silence about an inconvenient hypothesis is the cheapest way to hide a
  refutation.
- `supported` and `refuted` must cite at least one evidence path that exists.
- `refuted` is a complete, successful analysis. Nothing in the pipeline pushes
  toward a positive result.
- Findings the data suggested but the run did not predict belong in
  `exploratory_findings`, never in `outcomes`.

- A `supported` or `refuted` verdict needs a `statistics` block naming how many
  runs it rests on and how the spread was measured. `dispersion_type` is one of
  `std`, `stderr`, `ci95`, `iqr`, `range`, `none` — an interval whose meaning is
  unstated cannot be read. A verdict from a single run is refused unless
  `single_run_justification` says why one run settles it.
- `inconclusive` and `not_tested` are exempt: they are the honest verdicts when
  the evidence is thin, and requiring statistics for them would push a run
  toward claiming more than it measured.

Validated by `validate_hypothesis_outcomes` and `validate_outcome_statistics`.

### `workspace/reviews/validity_review_<stage>.json` and `validity_response_<stage>.json`

The adversarial pass. After Stage 05 and Stage 06 are approved, a reviewer with
the opposite instruction from the approval gate — *explain why this result is
wrong* — reads the run and files specific, checkable objections.

```json
{
  "generated_at": "2026-03-30T19:04:18",
  "reviewed_stage": "05_experimentation",
  "reviewer_failed": false,
  "note": "",
  "findings": [
    {
      "id": "V1",
      "category": "confound",
      "severity": "critical",
      "finding": "Both conditions were tuned on the split that reports the headline number.",
      "why_it_matters": "The gap may be selection, not the intervention.",
      "what_would_settle_it": "Re-tune on a development split and re-report."
    }
  ]
}
```

The reviewer cannot approve, reject or edit anything. What it produces is owed
an answer: Stage 06 must write `validity_response_05_experimentation.json`, and
Stage 07 must answer Stage 06's review.

```json
{"responses": [{"id": "V1", "status": "addressed | rebutted | accepted_limitation",
  "explanation": "what changed, or why the objection does not hold",
  "evidence": "the artifact or change (required when addressed)"}]}
```

Dismissing an objection is legitimate and deliberately cheap — `rebutted` with
an argument is a complete answer, and so is `accepted_limitation`. There is no
`noted`. What is refused is silence, because a finding nobody responded to is
indistinguishable in the run directory from one nobody raised.

**The findings the gate counts are AutoR's, not this file's.** The same pass is
stamped to `runs/<id>/validity_review_stamp.json`, outside `workspace/`, for the
reason `report_plan_stamp.json` and `preregistration_stamp.json` are: this file
sits in a directory the answering stage can write, so the record of what it owes
an answer to was in the hands of the party that owes it. `load_findings` reads
the stamp wherever there is one, and `validate_validity_response` refuses a
workspace copy that disagrees with it; the next attempt's prompt writes AutoR's
record back and logs what disagreed first, because the repair is what destroys
the evidence it was needed for. The boundary is the same one the other two
stamps have — everything under the run root is writable by the party the gate
constrains, so this narrows the escape rather than closing it.

`category` is one of ten named failure modes — `confound`, `weak_baseline`,
`insufficient_replication`, `leakage`, `metric_cherry_picking`,
`effect_within_noise`, `overclaim`, `unsupported_generalization`,
`missing_ablation`, `irreproducible_procedure`. Naming them beats asking for
"any problems": an open-ended critique reliably returns prose quality, which is
not what is dangerous here. `severity` is `critical`, `major` or `minor`.

A reviewer that crashed records `completion: "crashed"`, an answer with no
findings object records `"unreadable"`, and `note` carries what went wrong.
`reviewer_failed` is still derived from `completion` for readers of this schema.
An empty finding list from a failed critique would read as "nothing wrong", so
the manager re-asks once and then names the stage in the run's closing line; see
[Limits](../README.md#limits) for what that disclosure does and does not do.

**When a review panel left concerns standing**, those concerns *become* the
findings and no second critic runs: `ValidityReviewer.review` calls
`findings_from_panel` first and adopts its result whenever it is non-empty,
because the panel's own Methodologist and Reviewer 2 already cover these
categories and re-asking would pay for the same questions twice. Only the final
round counts — a concern a member withdrew during deliberation was answered
inside the panel and is not re-raised. The switch is the concerns, not the
seating: a panel that finished unanimous with nothing on the record yields an
empty list, and the separate adversarial critic then runs as it would with no
panel at all, at the cost of one more backend call. What this adds on top of the
panel is the part the panel does not have — an obligation on the **next** stage,
in its own artifacts, rather than a decision at this one's gate.

Validated by `validate_validity_response` in
[`src/validity_review.py`](../src/validity_review.py).

### `workspace/artifacts/claim_provenance.json`

Stage 07's map from each claim in the manuscript to what established it.

```json
{
  "claims": [
    {
      "claim": "the sentence as it appears in the manuscript",
      "status": "confirmatory",
      "hypothesis_id": "H1",
      "evidence": ["results/main_metrics.json"]
    }
  ]
}
```

`status` is `confirmatory` or `exploratory`, and there is no third value. A
`confirmatory` claim requires a `hypothesis_id` that was preregistered **and**
whose verdict is `supported` — the run predicted it in advance and the evidence
bore it out. Everything else is `exploratory`: permitted, often the most
interesting part of a run, but it has to say so. A post-hoc finding presented as
a confirmed prediction is the exact failure preregistration exists to prevent.

Every claim, whichever status, must cite at least one `evidence` path that
resolves to a file in the run. The whole check is skipped when there is no
frozen preregistration to compare against.

Written by Stage 07. Validated by `validate_claim_provenance` in
[`src/preregistration.py`](../src/preregistration.py).

### `workspace/artifacts/citation_verification.json`

```json
{
  "overall_status": "verified",
  "total_citations": 41,
  "claim_coverage": [
    {
      "claim": "AGSNv2 improves Actor accuracy over the dense baseline.",
      "citation_keys": ["vaswani2017"],
      "source_ids": ["S1"]
    }
  ]
}
```

Required: non-empty `overall_status`; non-negative integer `total_citations`;
non-empty `claim_coverage` list, where each entry has a non-empty `claim` and
at least one of `citation_keys` or `source_ids`.

Validated by `validate_citation_verification` in
[`src/evidence_ledger.py`](../src/evidence_ledger.py).

### `workspace/report/report.md`

The markdown deliverable, and the only Stage 07 output an automated research
benchmark reads. Required at Stage 07+ in `markdown` mode, and required to be
*fresh* — written during the Stage 07 execution that is asking for approval.

Content requirements are enforced, not just existence: at least
`MIN_REPORT_CHARS` (1,200) characters, no placeholder text, and at least one
figure reference where every reference is report-relative, resolves to a real
file under `workspace/report/`, and uses a format the report viewer can render
(`.png .jpg .jpeg .gif .webp`). A reference that climbs out of `report/` is
refused even when it resolves on this machine: only `report/` travels to a
benchmark workspace, so `../figures/x.png` is a link that works here and is
broken everywhere the report is actually read.

Figures live in `workspace/report/images/` and are referenced as
`images/<name>.png`. The count of rendered files in that directory — not the
count of references — is held between two bounds:

- **at least `min_report_figures`**, the [run config](#run_configjson) field.
  1 for an ordinary run, 3 under `rcb_agent.py`. One figure cannot answer more
  than one question, and a report that under-illustrates forfeits the criteria
  it never addresses.
- **at most `MAX_REPORT_FIGURES` (5)**, because a benchmark judge is shown only
  the first five it finds, in filesystem order. Filesystem order is not
  alphabetical, so a sixth figure does not dilute the score, it randomises it —
  the only way to choose the five is to publish no more than five.

Validated by `validate_markdown_report` in [`src/utils.py`](../src/utils.py).

### `workspace/artifacts/report_review.json`

The markdown-mode counterpart to `layout_review.json`, generated by AutoR after
each Stage 07 attempt and fed back into the next attempt's prompt.

```json
{
  "generated_at": "2026-08-06T02:14:03",
  "overall_status": "needs_attention",
  "report_available": true,
  "report_relative_path": "workspace/report/report.md",
  "report_char_count": 8412,
  "referenced_image_count": 4,
  "available_image_count": 5,
  "figure_budget": 5,
  "issue_counts": {
    "broken_image_links": 1,
    "non_relative_image_links": 0,
    "unrenderable_images": 0,
    "non_png_images": 0,
    "unreferenced_images": 1,
    "unplanned_images": 0,
    "figures_over_budget": 0,
    "total": 2
  },
  "issues": [
    {
      "category": "broken_image_link",
      "severity": "critical",
      "summary": "1 figure reference(s) point at files that do not exist under report/.",
      "evidence": ["images/ablation.png"]
    }
  ],
  "priority_fixes": ["Repair figure references that point at files missing from report/images/."]
}
```

Required: non-empty string `overall_status`; boolean `report_available`;
integer `referenced_image_count`; object `issue_counts`; list `issues`; and
`priority_fixes` as a list of non-empty strings. AutoR writes `overall_status`
as `clean` or `needs_attention`.

`unplanned_images` counts figures under `report/images/` that are not slots in
`report_plan.json` — advisory rather than a refusal, because the plan is
amendable and a late figure that earns its slot is a legitimate move. Only
checked once a plan exists.

Validated by `validate_report_review` in
[`src/writing_manifest.py`](../src/writing_manifest.py).

### `workspace/artifacts/layout_review.json`

The `latex`-mode triage artifact, generated after each Stage 07 attempt by
parsing the LaTeX build log.

```json
{
  "generated_at": "2026-08-06T02:14:03",
  "overall_status": "needs_attention",
  "pdf_available": true,
  "pdf_relative_path": "workspace/writing/main.pdf",
  "estimated_page_count": 9,
  "build_log_checked": true,
  "build_log_relative_path": "workspace/artifacts/build_log.txt",
  "issue_counts": {
    "overfull_hboxes": 3,
    "underfull_hboxes": 0,
    "undefined_references": 0,
    "undefined_citations": 1,
    "missing_file_warnings": 0,
    "total": 4
  },
  "issues": [],
  "priority_fixes": ["Trim Section 4 to fit the 9-page limit."]
}
```

Required: non-empty string `overall_status`; booleans `pdf_available` and
`build_log_checked`; object `issue_counts`; list `issues`; and
`priority_fixes` as a list of non-empty strings. AutoR writes `overall_status`
as `clean` or `needs_attention`.

Validated by `validate_layout_review` in
[`src/writing_manifest.py`](../src/writing_manifest.py).

### `workspace/reviews/scorecard.json` and `scorecard.md`

Written at the end of every **completed** run — not a halted or abandoned one,
which stop before the completion path. Reads every other ledger and says which
features earned their cost — `keep`, `drop`, or `unproven` — plus the total extra
model calls they spent. A run with no optional feature enabled still gets the
files; every feature just reads `not enabled`, and the terminal says nothing.

`unproven` means the measurement could not run, and is deliberately not merged with `drop`. A
ledger that exists but cannot be parsed is reported as unreadable rather than as a null result.

See [Scorecard](scorecard.md).

### `workspace/reviews/effort.json`

Written when effort tiering is on — which is the **default**, since `--rigor`
defaults to `standard` and `standard` turns `effort_tiers` on. `--rigor fast` or
an explicit `--no-effort-tiers` is what leaves this file absent.

Which tier each stage ran in, who chose it, why, and both
directions of mis-spending: `promoted_after_failing` (ran cheap and should not have) and
`deliberative_but_uncontested` (paid for ceremony nobody used).

See [Effort Tiers](effort-tiers.md).

### `workspace/notes/deliberation_request.json`

Where an executing stage raises a crux. Not written by AutoR — the *agent*
writes it mid-stage, when it hits a question whose answer is genuinely unclear
and getting it wrong would invalidate work downstream.

```json
{
  "question": "the specific question, answerable and decidable",
  "why_it_matters": "what breaks downstream if this is wrong",
  "already_considered": ["what you have already ruled out, and why"],
  "working_answer": "your best answer right now, so the panel can disagree with it",
  "help_wanted": "both"
}
```

A bare object or a list of them is accepted, because this file is written by a
model mid-stage and a malformed escalation should cost the escalation rather
than the stage. Entries whose `question` is under `MIN_QUESTION_CHARS` (25) are
dropped silently; `help_wanted` outside `perspectives` / `expertise` / `both`
falls back to `both`. There is no gate — nothing refuses a stage for writing a
bad one.

**Unlinked once consumed.** `clear_requests` deletes the file as soon as the
requests are read, so one crux is not deliberated twice. The stage is not
blocked while the panel sits: it finishes with its working answer, and the
resolution is handed back on the next pass. Reading it requires an active crux
panel (`--deliberation`, or `--rigor thorough`/`max`) — with none seated the
file is never read and never removed. The run-wide budget is
`DEFAULT_MAX_DELIBERATIONS` (3).

The resolutions land in `workspace/reviews/deliberations.json`. See
[Raising a Crux](deliberation.md).

### `workspace/reviews/deliberations.json`

Written when a stage raises a crux and a panel is seated to take it —
`--deliberation`, or `--rigor thorough`/`max`. Every question escalated, the
expert brief, each voice's position and self-objection, and the resolution with its falsifier
and surviving dissent.

`summary.confirmed_the_agents_answer` is the one to read: escalations where the panel simply
agreed with what the agent already had are escalations that were not needed.

See [Raising a Crux](deliberation.md).

### `workspace/reviews/comment_ledger.json`

Written when a reviewer anchors its objections to quoted passages. `rounds` holds
one entry per review round — the comments raised and, once the revision arrives,
its `outcome`. `summary` aggregates across all rounds, and is the part worth
reading:

| `summary` field | Meaning |
| --- | --- |
| `rounds` / `comments_raised` | How many anchored rounds ran, and how many comments they raised. |
| `comments_addressed` | Quoted passages that actually changed. |
| `comments_left_untouched` | Passages that did not, carried into the next round. |
| `comments_quoting_absent_text` | Comments whose quote was not in the draft; dropped rather than sent on. |
| `lines_changed_on_target` / `lines_changed_as_collateral` | Whether the revision stayed local. |
| `collateral_ratio` | 0.0 for a targeted patch; 0.5 and up means the stage was rewritten, not patched. |
| `verdict` | One sentence over the above. |

See [Anchored Review Comments](stage-comments.md).

### `workspace/notes/idea_pool.json`

Written when the ideation panel is seated — `--ideation-panel`, or `--rigor
thorough`/`max`, which turn it on without a flag. The Stage 02 candidate pool, with every
proposal, which ones were folded in as restatements, their novelty/feasibility/relevance
scores, and an `effect` block.

`effect` answers two separate questions. Before Stage 02 is approved it can only report
whether the panel **widened** anything (`added_by_other_proposers`); afterwards it also
reports whether anything was **used** (`adopted`, `adopted_from_other_proposers`,
`adoption_measured`). Its `verdict` is one sentence, written to be unflattering when that is
the truth. A readable `idea_pool.md` sits beside it.

See [Ideation Panel](ideation-panel.md).

### `workspace/reviews/panel/`

Written when the review panel is seated — `--review-panel`, or `--rigor max`,
the only level that includes it. Per gate, `<stage>_attempt_NN.json` and a
readable `.md` hold every position from every round, including dissent that lost and any
chair override.

Alongside them, `panel_effect.json` accumulates the panel against its own single-pass
baseline — the chair's round-1 verdict, which is one model, one call, no peer input. It
holds `gates`, the per-gate rows, and `summary`, which is where these live:

| `summary` field | Meaning |
| --- | --- |
| `gates_reviewed` | Gates the panel has judged this run. |
| `gates_where_the_panel_changed_the_decision` | How often deliberation reached a different decision than the baseline. **If this stays 0, the panel is not earning its cost.** |
| `gates_where_round_1_disagreed` | How often the seats were not already unanimous. |
| `chair_overrides` | Approvals converted to refinements by a blocking objection. |
| `panel_calls` / `single_pass_calls` | The two call counts the ratio below is built from. |
| `cost_multiple` | Reviewer calls spent per single-pass call. |
| `verdict` | One plain sentence, written to be unflattering when that is the truth. |

See [Review Panel](review-panel.md) for the pre-registered evidence this measurement exists
to answer.

### `workspace/artifacts/deliverables_coverage.json`

Did the run answer what the task statement actually demanded? Everything else
about Stage 07 measures how well the report was *made*; this measures whether it
answered the question. Required at Stage 07+ in `markdown` mode.

Observed on ResearchClawBench `Astronomy_000`. The task asked for upper limits
on masses **and self-interaction coupling strengths**; the run produced a
rigorous mass exclusion band and never reported a coupling limit. Its own rubric
scored 1.000, and the criterion asking for the coupling constant — half the
task's weight — scored 25/100. Nothing in the pipeline was comparing the report
against the ask.

```json
{
  "deliverables": [
    {
      "task_quote": "derive statistically rigorous upper limits on ULB masses",
      "addressed": true,
      "where": "Section 4: Mass Exclusion"
    },
    {
      "task_quote": "and self-interaction coupling strengths",
      "addressed": false,
      "reason": "the available spectra do not constrain the coupling at any mass we can probe"
    }
  ]
}
```

Four checks, all of them things a machine can settle:

- **`task_quote` must be a verbatim span of the task statement** (whitespace
  collapsed, case-insensitive). Without this, a stage can restate the
  requirement as something it already did and mark it answered.
- **Every demanding sentence in the task statement must be spoken to by some
  quote.** A "demanding sentence" is one of at least 25 characters carrying a
  verb from `DEMAND_VERBS` (34 of them: `derive`, `compute`, `compare`,
  `constrain`, `evaluate`, …). Overlap is scored on content words at a 34%
  threshold rather than exact containment, so a stage may legitimately quote the
  clause instead of the whole sentence.
- **`addressed: true` needs a `where` that actually appears in `report.md`.**
  Deliberately loose — a section title, a figure filename, a heading all count.
  The point is that the pointer is not fabricated, not that it follows a format.
- **`addressed: false` needs a `reason`.** Reporting a requirement as unmet is a
  valid outcome. Omitting it is not.

What the gate deliberately does not do is judge whether the answer is *correct*.
That is the same line every other AutoR validator holds.

Validated by `validate_deliverables_coverage` in
[`src/deliverables.py`](../src/deliverables.py), against the verbatim text of
`user_input.txt`.

### `workspace/artifacts/self_review.json`

Required to exist at Stage 07+, in both output formats. Its contents are not
schema-validated, so its shape is up to the writing stage.

### `workspace/artifacts/build_log.txt`

The LaTeX build output. Required at Stage 07+ in `latex` mode, and required to
be *fresh* — written during the Stage 07 execution that is asking for
approval.

---

## Studio-only state

Present only for runs driven through [AutoR Studio](studio.md):

| Path | Contents |
| --- | --- |
| `<run>/sessions/<slug>.jsonl` | per-stage trace events rendered in the Studio live view |
| `<run>/notebook/session.json` | the Notebook conversation's session ID |
| `<run>/notebook/transcript.jsonl` | the Notebook conversation transcript |
| `<repo>/.autor/projects.json` | the Studio project index (**outside** the run directory) |

`.autor/projects.json` is the one piece of state that is not per-run. Deleting
it loses the Studio's project groupings; the runs themselves are unaffected.

---

## Practical notes

- **A run directory is self-contained.** Copy or archive `runs/<run_id>/` and
  you have the whole record. Two things live outside it and neither is needed to
  read a run: the Studio's project index at `<repo>/.autor/projects.json`, and
  the cross-run topology archive at `~/.autor/archive` (`runs.jsonl`,
  `variants.json`), which records this run's route and fitness so *other* runs
  can be compared against it. `--archive PATH` moves the latter.
- **`runs/` is gitignored.** Runs are outputs, not source. Archive them
  yourself if you need them.
- **`--runs-dir` is resolved relative to the repository root.** Point it at a
  large disk before a heavy experiment; a real run with datasets and
  checkpoints gets big.
- **Read `logs.txt`, then `logs_raw.jsonl`, then `prompt_cache/`.** That is
  the fastest path from "the output is wrong" to "here is why".
