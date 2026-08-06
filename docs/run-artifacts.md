# Run Artifacts

Everything a run produces lives inside one directory, `runs/<run_id>/`, where
`run_id` is a `YYYYMMDD_HHMMSS` timestamp. Nothing is stored in a database,
nothing is stored globally, and a run directory can be copied, archived, or
handed to someone else and remain complete.

This page documents every file in that directory and the schema of every
machine-readable one.

---

## Directory layout

```text
runs/<run_id>/
├── .claude/skills/             # agent skills, installed from src/skills/ (this is the operator's cwd)
├── user_input.txt              # the original research goal, verbatim
├── memory.md                   # approved cross-stage memory (the only shared context)
├── run_config.json             # backend, model, venue, approval mode, sandbox
├── run_manifest.json           # stage lifecycle state — the machine-readable source of truth
├── artifact_index.json         # index over workspace/{data,results,figures}
├── intake_context.json         # Stage 00 Q&A, ingested resources, refined goal
├── logs.txt                    # human-readable workflow log
├── logs_raw.jsonl              # raw backend stream-json events
├── prompt_cache/               # the exact prompt sent for every attempt
├── operator_state/             # per-stage session IDs, attempt state, start markers
├── handoff/                    # compressed per-stage handoff summaries
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
    ├── notes/                  # supporting notes, hypothesis_manifest.json, preregistration.json
    ├── reviews/                # readiness, critique, dissemination material
    ├── bootstrap/              # --paper-corpus / --project-root scan output
    └── profile/                # derived researcher profile
```

The directory shape is created by `ensure_run_layout` and the paths are
defined once, in `build_run_paths` ([`src/utils.py`](../src/utils.py)). If you
need a path in code, take it from `RunPaths` rather than joining strings.

---

## Top-level files

### `user_input.txt`

The research goal exactly as given, before any intake refinement. Required for
resume; a run without it cannot be resumed.

### `memory.md`

The **only** context shared across stages. A stage does not see another
stage's conversation — it sees this file.

Each approved stage contributes one entry containing its `Objective`,
`What I Did`, `Key Results`, and `Files Produced` sections. Nothing enters
`memory.md` before you approve it, which is what makes "approval" mean
something: an unapproved stage cannot influence the rest of the run.

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
  "web_search": "auto",
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
| `web_search` | `auto`, `gemini`, or `native`. The mode, not the resolved backend. Absent in runs created before it existed, and read as `auto`. |
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

**`run_status`** — one of `pending`, `running`, `human_review`, `completed`,
`failed`, `cancelled`.

**Stage `status`** — one of `not_started`, `pending`, `running`,
`human_review`, `approved`, `skipped`, `completed`, `failed`, `cancelled`.

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

An index over `workspace/data/`, `workspace/results/`, and
`workspace/figures/`, regenerated whenever artifacts change and fed into later
stages' prompts so a stage can find data without guessing filenames. Written
by [`src/artifact_index.py`](../src/artifact_index.py).

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

`experiment_manifest.json` and any `*.schema.json` sidecar are excluded from
the index — the manifest is a view of the index, not an entry in it.

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
| `.csv`, `.tsv` | column names |
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

`resource_type` is one of `pdf`, `bib`, `code`, `dataset`, `notes`, `other`;
`dest_dir` is the workspace subdirectory the resource was copied into.

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

The required shape of both is the [stage contract](stage-contract.md).

### `prompt_cache/`

The exact prompt text sent to the backend, one file per attempt:

| Filename | Written by |
| --- | --- |
| `<slug>_attempt_NN.prompt.md` | a normal stage attempt |
| `<slug>_attempt_NN_repair.prompt.md` | a repair pass after a malformed summary |
| `<slug>_review_attempt_NN.prompt.md` | the automated reviewer in `--full-auto` |

Nothing is elided: if you want to know why a stage did what it did, the prompt
that caused it is on disk. Prompts are passed to the backend by reference
(`-p @<path>`), so these files are load-bearing during a run, not just a log.

### `operator_state/`

| File | Contents |
| --- | --- |
| `<slug>.session_id.txt` | the backend session ID for that stage |
| `<slug>.session.json` | session bookkeeping |
| `<slug>.attempt_NN.json` | per-attempt state: command line, mode (`start`/`resume`), prompt path, timestamps |
| `<slug>.started_at.txt` | the freshness cutoff used by the [artifact gate](stage-contract.md#freshness-checks) |

`<slug>.attempt_NN.json` records the literal argv used, which makes a failed
attempt reproducible by hand.

### `handoff/`

One `<slug>.md` per completed stage: a compressed view carrying only
`Objective`, `Key Results`, `Files Produced`, and the `Decision Ledger`.

At most the four most recent handoffs before the current stage are injected
into a prompt, and the `Decision Ledger` section is stripped from that
injection — the ledger is kept on disk for audit, not spent on context. This
is what keeps long runs from growing their prompts without bound.

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
| `artifacts/` | compiled PDF, `build_log.txt`, review JSON, packaged deliverables | Stage 07+ |
| `reviews/` | readiness checklists, threats to validity, critique notes | Stage 08+ |
| `notes/` | supporting notes, `hypothesis_manifest.json`, `preregistration.json` | — |
| `bootstrap/` | `--paper-corpus` / `--project-root` scan output | — |
| `profile/` | derived researcher profile and style notes | — |

---

## Validated JSON files

These are the files AutoR parses and rejects rather than merely counting. Each
schema below is what the validator actually requires.

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

### `workspace/notes/preregistration.json`

The hypothesis set, frozen. Written when Stage 04 is approved — design settled,
code written, nothing measured — and again lazily at the start of Stage 05 for
runs that arrive by resume, `--redo-stage`, or a `--project-root` bootstrap.

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

`source_digest` hashes the statements and decision rules in
`hypothesis_manifest.json`, deliberately ignoring the timestamp and the
self-declared `status`. From Stage 06 on, a manifest whose digest no longer
matches — a hypothesis edited after results existed — fails validation unless
an amendment is on record.

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

A `confirmatory` claim requires a hypothesis whose verdict is `supported` — the
run predicted it in advance and the evidence bore it out. Everything else is
`exploratory`: permitted, often the most interesting part of a run, but it has
to say so. A post-hoc finding presented as a confirmed prediction is the exact
failure preregistration exists to prevent.

Validated by `validate_claim_provenance`.

Written by [`src/hypothesis_manifest.py`](../src/hypothesis_manifest.py).

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

Content requirements are enforced, not just existence: at least 1,200
characters, no placeholder text, and at least one figure reference where every
reference is report-relative, resolves to a real file under
`workspace/report/`, and uses a format the report viewer can render
(`.png .jpg .jpeg .gif .webp`). Figures live in `workspace/report/images/` and
are referenced as `images/<name>.png`, with at most `MAX_REPORT_FIGURES` (5) published —
a benchmark judge is shown only the first five it finds, in filesystem order.

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
`priority_fixes` as a list of non-empty strings.

Validated by `validate_report_review` in
[`src/writing_manifest.py`](../src/writing_manifest.py).

### `workspace/artifacts/layout_review.json`

The `latex`-mode triage artifact.

```json
{
  "overall_status": "pass",
  "pdf_available": true,
  "build_log_checked": true,
  "issue_counts": { "overfull_hbox": 3, "missing_figure": 0 },
  "issues": [],
  "priority_fixes": ["Trim Section 4 to fit the 9-page limit."]
}
```

Required: non-empty string `overall_status`; booleans `pdf_available` and
`build_log_checked`; object `issue_counts`; list `issues`; and
`priority_fixes` as a list of non-empty strings.

Validated by `validate_layout_review` in
[`src/writing_manifest.py`](../src/writing_manifest.py).

### `workspace/artifacts/self_review.json`

Required to exist at Stage 07+. Its contents are not schema-validated, so its
shape is up to the writing stage.

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
  you have the whole record.
- **`runs/` is gitignored.** Runs are outputs, not source. Archive them
  yourself if you need them.
- **`--runs-dir` is resolved relative to the repository root.** Point it at a
  large disk before a heavy experiment; a real run with datasets and
  checkpoints gets big.
- **Read `logs.txt`, then `logs_raw.jsonl`, then `prompt_cache/`.** That is
  the fastest path from "the output is wrong" to "here is why".

## `review_policy.json`

The standing rules the approval gate has learned during this run. Written by
[`src/review_policy.py`](../src/review_policy.py) whenever the reviewer demands a
correction, and injected into every subsequent review prompt.

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
| `text` | The correction verbatim, as the reviewer worded it. |
| `origin_stage` / `origin_attempt` | Which review produced the rule. This is what makes the mechanism auditable rather than assertable. |
| `source` | `refinement` for a demanded correction, `rollback` for an approval that later proved wrong. Rollbacks are rendered first in the prompt. |

Absent until the first correction is recorded. Approvals teach nothing and are not
recorded. Rules are deduplicated on normalized text (casing, punctuation and stage numbers
collapse) and the set is capped, so a reviewer restating one complaint cannot inflate it.
A corrupt file is treated as an empty policy: the gate falls back to baseline strictness
rather than taking the run down.
