# Development

How to work on AutoR itself. If you want to *use* AutoR, read the
[English Guide](tutorial_en.md) instead.

---

## Setup

```bash
git clone https://github.com/tangxiangru/AutoR.git
cd AutoR
python -m unittest discover -s tests -p "test_*.py"
```

That is the whole setup. There is no virtualenv step, no `pip install`, and no
build.

**AutoR has no third-party Python dependencies.** Everything except optional
diagram generation runs on the standard library. Python 3.10+ is the only hard
requirement; CI runs 3.12.

Neither backend CLI is needed for development — the test suite runs against
fakes and temp directories, and `--fake-operator` exercises the full workflow
without a backend.

Optional, for `--research-diagram` work only:

```bash
pip install google-genai pyyaml
```

---

## Tests

```bash
# Everything (~10s, 234 tests)
python -m unittest discover -s tests -p "test_*.py"

# Verbose
python -m unittest discover -s tests -p "test_*.py" -v

# One module
python -m unittest tests.test_manager_smoke

# One test
python -m unittest tests.test_manager_smoke.ManagerSmokeTest.test_full_run
```

Tests are stdlib `unittest`. They create temporary run directories, drive the
manager with a fake operator, and assert on files. They do not call any
network service, and they do not need a backend CLI installed.

### Coverage map

| Area | Tests |
| --- | --- |
| Workflow end to end | `test_manager_smoke.py`, `test_manager_workflow.py`, `test_cli_smoke.py` |
| Operator sessions, resume fallback, repair | `test_operator_recovery.py`, `test_bounded_recovery.py`, `test_operator_codex.py` |
| Stage contract and validation | `test_utils_contracts.py`, `test_decision_ledger.py`, `test_revision_delta.py` |
| Run state, rollback, handoff | `test_run_manifest.py`, `test_stage_rollback.py`, `test_stage_handoff.py` |
| Manifests and ledgers | `test_artifact_index.py`, `test_experiment_manifest.py`, `test_hypothesis_manifest.py`, `test_evidence_ledger.py` |
| Writing and packaging | `test_writing_pipeline.py`, `test_foundry_paper_package.py`, `test_release_package.py` |
| Intake and bootstrap | `test_intake.py`, `test_bootstrap.py`, `test_project_bootstrap.py` |
| Studio | `test_studio_service.py`, `test_studio_http.py` |
| Terminal UI | `test_terminal_ui.py` |
| Diagram generation | `test_diagram_gen.py` |

### Before you push

```bash
python -m py_compile main.py studio.py src/*.py src/*/*.py tests/*.py
python -m unittest discover -s tests -p "test_*.py"
```

The compile step catches syntax errors in modules no test happens to import.
Note that it covers more than CI does — see below.

---

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), on pull requests,
pushes to `main`, and manual dispatch:

1. Ubuntu latest, Python 3.12, 15-minute timeout.
2. `python -m py_compile main.py src/*.py tests/*.py`
3. `python -m unittest discover -s tests -p "test_*.py" -v`

The compile step's globs are one level deep, so `src/backend/`,
`src/platform/`, and `studio.py` are compiled only insofar as a test imports
them. Run the wider compile locally.

CI installs nothing. Adding a third-party dependency would change that, which
is a good reason to avoid one.

---

## Code conventions

Match the file you are editing. The house style, as it stands:

- **`from __future__ import annotations`** at the top of every module, with
  modern annotations (`str | None`, `list[str]`) throughout.
- **Frozen dataclasses** for anything serialized, with explicit `to_dict` and
  `from_dict`. Do not rely on `asdict`; the round trip is written out so the
  on-disk shape is visible in one place.
- **Defensive `from_dict`.** Coerce, default, and skip malformed entries
  rather than raising. A corrupt artifact should degrade a view, not kill a
  six-hour run.
- **Validators return `list[str]`**, never raise, never print. An empty list
  means valid; each string is one human-readable problem. The caller decides
  what to do.
- **Paths come from `RunPaths`.** Never join run paths by hand — add a field
  to `RunPaths` and `build_run_paths` instead.
- **Rendering goes through `TerminalUI`.** The manager does not print.
- **Local imports for cycles.** `src/utils.py` imports validators inside
  functions to avoid import cycles; keep that pattern rather than
  restructuring around it.
- **Comments explain *why*.** The existing comments mostly record a decision
  or a trap — for example why `claims.json` accepts both `statement` and
  `claim`. Match that density; do not narrate the code.

---

## Extending AutoR

### Change what a stage asks for

Edit `src/prompts/<slug>.md`. No code change, no test change. This is the
right lever for most behaviour changes, and it is worth trying before
reaching for anything below.

### Add a venue

Append a block to `templates/registry.yaml`. See
[Configuration → Adding a venue](configuration.md#adding-a-venue). No code
change.

### Add or change an artifact requirement

Edit `validate_stage_artifacts` in [`src/utils.py`](../src/utils.py).

1. Add the check under the right `if stage.number >= N:` block.
2. Append to `problems` with a message that names the stage and the fix.
3. If the stage *produces* the artifact, add a freshness check against
   `stage_execution_started_at`, or a re-run will be credited with the
   previous attempt's files.
4. Add a test in `tests/test_utils_contracts.py`.

Requirements are cumulative — a check under `>= 5` also applies at Stage 8.

### Add a validated JSON artifact

1. Write a `validate_*(path) -> list[str]` function in the module that owns
   that artifact class.
2. Call it from `validate_stage_artifacts`, prefixing each problem with
   `stage.stage_title`.
3. Import it *inside* the function, not at module level.
4. Document the schema in [Run Artifacts](run-artifacts.md).

### Add a stage

1. Add a `StageSpec` to `STAGES` in `src/utils.py`.
2. Create `src/prompts/<NN>_<slug>.md`.
3. Extend `validate_stage_artifacts` if the stage owns an artifact class.
4. Check anything that hard-codes stage numbers — the artifact gate, the
   Stage 02 hypothesis rules, `writing_manifest`, Studio stage display names.

Stage numbers appear in enough places that this is the most invasive change on
this list. Grep for `stage.number` before you start.

### Add an execution backend

Implement [`OperatorProtocol`](../src/operator_protocol.py), or subclass
`ClaudeOperator` and override `_prepare_invocation` — that is all
`CodexOperator` does, in about 100 lines.

You will need to handle:

- **Session lifecycle** — start vs resume, and persisting the session ID.
- **Streaming** — parse the backend's event stream into `TerminalUI` calls.
- **Resume failure** — extend `_looks_like_resume_failure` with the error text
  your backend produces when a session is gone, so AutoR falls back to a fresh
  session rather than failing the stage.
- **Prompt delivery** — file reference, stdin, or argument.

Then register it in `create_operator` in [`main.py`](../main.py) and add the
name to the `--operator` choices.

### Change the approval policy

`AutomatedReviewer` in [`src/approval_agent.py`](../src/approval_agent.py)
returns a `ReviewDecision`. It is the only thing standing between a
`--full-auto` run and unattended advancement, so changes here should make it
stricter, not more permissive.

---

## Repository layout

```
main.py                     terminal entry point
studio.py                   Studio entry point (shim)
src/
  manager.py                the control loop
  operator*.py              backend adapters + protocol
  utils.py                  contract layer: stages, paths, prompts, validation
  manifest.py               run_manifest.json
  artifact_index.py         artifact scanning and schema inference
  experiment_manifest.py    results/experiment_manifest.json
  evidence_ledger.py        literature + citation validation
  hypothesis_manifest.py    Stage 02 typed claims
  writing_manifest.py       Stage 07 support and layout review
  intake.py                 Stage 00 and resource ingestion
  bootstrap.py              --paper-corpus
  project_bootstrap.py      --project-root
  approval_agent.py         --full-auto reviewer
  terminal_ui.py            all terminal rendering
  diagram_gen.py            optional Gemini diagrams
  platform/foundry.py       paper and release packaging
  prompts/                  per-stage templates
  backend/                  Studio service, HTTP, runner, sessions, notebook
  frontend/static/          the Studio SPA (no build step)
templates/registry.yaml     venue registry
configs/                    optional diagram config template
tests/                      unittest suite
docs/                       this documentation
.claude/skills/guides/      writing, citation, and venue reference material
```

`.claude/skills/guides/` holds long-form reference material — writing
principles, citation discipline, venue checklists — available to agents
working in this repository. It is guidance, not code.

---

## Contributing

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for the pull-request process,
commit conventions, and what a reviewer will look for.
