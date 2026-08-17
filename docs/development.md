# Development

How to work on AutoR itself. If you want to *use* AutoR, read the
[English Guide](tutorial_en.md) instead.

> **AutoR is proprietary software.** Running it — including running it locally
> to develop against — requires written permission from the copyright holder.
> Contributions are assigned under Section 6 of the [LICENSE](../LICENSE).
> Read [CONTRIBUTING.md](../CONTRIBUTING.md) before you start.

---

## Setup

```bash
git clone https://github.com/tangxiangru/AutoR.git
cd AutoR
python -m unittest discover -s tests -p "test_*.py"
```

That is the whole setup. There is no virtualenv step, no `pip install`, and no
build.

**AutoR has no third-party Python dependencies.** The runtime imports nothing
outside the standard library — even the venue registry is read by a hand-rolled
line parser in `src/utils.py` rather than by a YAML library, and the skill
frontmatter reader (`_parse_frontmatter`) is deliberately minimal for the same
reason. Python 3.10 is the floor; CI runs 3.12. The full suite passes on both.

Neither backend CLI is needed for development — the test suite runs against
fakes and temp directories, and `--fake-operator` exercises the full workflow
without a backend.

Optional packages, none of them needed by any test. The two worth installing
first:

```bash
pip install google-genai pyyaml
```

`google-genai` is used by three paths — `--web-search gemini` and
`--cross-review`, which both reach it through `build_genai_client` in
`src/web_search.py`, and `--research-diagram` in `src/diagram_gen.py`. `pyyaml`
is used by exactly one function, `_api_key_from_config_file` in
`src/web_search.py`, which reads a key out of `configs/diagram_config.yaml` if
you keep one there. Both degrade to a recorded *unavailable* or a printed
warning rather than to a crash, which is why the suite never installs them.

`src/diagram_gen.py` also reaches for `pillow` and `json_repair`, each inside a
`try` with a working fallback — `_convert_to_jpeg_b64` returns the base64 string
it was handed, `_convert_to_png` returns the original path, and the critic's
reply falls back to `json.loads`. They are worth installing if you work on
diagrams, and they are not dependencies.

One tool is the exception to *optional*. `tools/score_rcb_run.py` builds a judge,
and the constructor's first statement is a bare import: `from openai import
OpenAI` in `ReferenceJudge.__init__`, which is the default `--judge reference`,
and `from anthropic import AnthropicVertex` in `VertexJudge.__init__` under
`--judge vertex`. Neither import sits in a `try`, so a missing package raises
`ModuleNotFoundError` rather than degrading. No test calls either `__init__`,
which is why the suite still installs nothing.

---

## Tests

```bash
# Everything (2282 tests across 99 modules, no third-party dependency)
python -m unittest discover -s tests -p "test_*.py"

# Verbose
python -m unittest discover -s tests -p "test_*.py" -v

# One module
python -m unittest tests.test_manager_smoke

# One test
python -m unittest tests.test_manager_smoke.ManagerSmokeTests.test_manager_run_completes_full_eight_stage_smoke
```

Tests are stdlib `unittest`. They create temporary run directories, drive the
manager with a fake operator, and assert on files. They do not call any
network service, and they do not need a backend CLI installed. One test skips
by design (the markdown-report assertion in LaTeX mode); everything else runs
everywhere.

### Coverage map

Every test module in `tests/` is listed. Two files there are not test modules
and so do not appear: `__init__.py`, and `prereg_support.py`, which builds the
minimal valid validity-chain artifacts a hand-assembled run needs. Rebuild the
list with `ls tests/test_*.py`.

Some rows below are genuinely arbitrary. A test that drives the whole manager
in order to pin one validator could sit in either place, and several modules
import six `src` modules apiece; the row records what the module is *about*, per
its own docstring, not everything it touches.

| Area | Test modules |
| --- | --- |
| Workflow end to end | `test_manager_smoke.py`, `test_manager_workflow.py`, `test_cli_smoke.py`, `test_fake_pipeline_end_to_end.py`, `test_graph_walk.py`, `test_auto_skip_preserves_a_valid_draft.py`, `test_unattended.py`, `test_manager_start_stage.py` |
| Graph, routing, rounds | `test_stage_graph.py`, `test_router.py`, `test_graph_cost.py`, `test_research_rounds.py` |
| Policy dials | `test_rigor.py`, `test_effort.py` |
| Stage contract and stage summaries | `test_utils_contracts.py`, `test_stage_handoff.py`, `test_decision_ledger.py`, `test_revision_delta.py`, `test_listed_file_patterns.py`, `test_path_reference_heuristic.py`, `test_prompt_gate_correspondence.py` |
| Prompt assembly and context | `test_information_flow.py`, `test_settled_reasoning.py`, `test_prompt_fragments.py`, `test_run_skills.py` |
| The validity chain | `test_preregistration.py`, `test_experimental_protocol.py`, `test_validity_review.py`, `test_hypothesis_manifest.py`, `test_evidence_ledger.py`, `test_report_plan.py`, `test_report_plan_robustness.py`, `test_report_plan_stamping.py`, `test_task_deliverables_contract.py` |
| Manifests, indexes, rollback | `test_run_manifest.py`, `test_stage_rollback.py`, `test_artifact_index.py`, `test_experiment_manifest.py`, `test_writing_pipeline.py` |
| Improvement loop | `test_rubric.py`, `test_evolution.py` (also covers `pareto.py`), `test_ideation_panel.py` |
| Review and approval | `test_review_panel.py`, `test_panel_unreachable.py`, `test_panel_inherits_the_ledger.py`, `test_cross_reviewer.py`, `test_review_policy.py`, `test_obligations.py`, `test_stage_comments.py`, `test_deliberation.py`, `test_crux_repeat.py`, `test_verdict_extraction.py`, `test_reviewer_unreadable_verdict.py` |
| Archive and self-measurement | `test_archive.py`, `test_archive_evidence.py`, `test_archive_exploration.py`, `test_archive_exploration_wiring.py`, `test_decisions.py`, `test_trials.py`, `test_scorecard.py` |
| Operators, recovery, backend health | `test_operator_recovery.py`, `test_operator_codex.py`, `test_bounded_recovery.py`, `test_backend_health.py` |
| Web search | `test_web_search.py`, `test_web_search_off.py`, `test_mcp_web_search.py` |
| Report output and the benchmark adapter | `test_markdown_report.py`, `test_report_figure_floor.py`, `test_rcb_adapter.py`, `test_rcb_report_source.py`, `test_rcb_scoring.py`, `test_score_rcb_run.py` (which also holds the repository-wide secret scan), `test_score_rcb_run_wiring.py` |
| Intake and bootstrap | `test_intake.py`, `test_bootstrap.py`, `test_project_bootstrap.py` |
| Packaging and diagrams | `test_foundry_paper_package.py`, `test_release_package.py`, `test_diagram_gen.py` |
| Studio | `test_studio_service.py`, `test_studio_http.py` |
| Terminal UI | `test_terminal_ui.py`, `test_result_panel.py` |
| The docs themselves | `test_doc_counts.py` (see [Documentation gates](#documentation-gates)) |
| Declared-and-unread gates over the tree | `test_cli_flags_are_read.py` (a flag argparse accepts and no line reads), `test_declared_symbols_are_wired.py` (a public `src/` symbol no production line references) |

Two of these modules are worth knowing about before you write a test that
duplicates them. `test_prompt_gate_correspondence.py` treats the prompt
templates and the validators as two encodings of one contract and fails when
they drift, and `test_doc_counts.py` does the same for prose. Neither is
optional scaffolding; both have caught real drift.

### Before you push

```bash
python -m py_compile main.py studio.py rcb_agent.py src/*.py src/*/*.py tools/*.py tests/*.py
python -m unittest discover -s tests -p "test_*.py"
```

The compile step catches syntax errors in modules no test happens to import —
`tools/` and `rcb_agent.py` are the ones with the least test pressure on them.
Note that it covers more than CI does; see below. (CONTRIBUTING.md prints a
narrower form of the same command. The line above is a superset of it and costs
nothing extra.)

---

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), on pull requests,
pushes to `main`, and manual dispatch:

1. Ubuntu latest, Python 3.12, 15-minute timeout.
2. `python -m py_compile main.py src/*.py tests/*.py`
3. `python -m unittest discover -s tests -p "test_*.py" -v`

The compile step's globs are one level deep and rooted at three paths, so
`studio.py`, `rcb_agent.py`, `tools/`, `src/backend/` and `src/platform/` are
compiled only insofar as a test imports them. Run the wider compile locally.

CI installs nothing. Adding a third-party dependency would change that, which
is a good reason to avoid one.

---

## Documentation gates

Two tests police the documentation, and both fail the ordinary suite rather
than a separate docs job. You will meet them if you edit a `.md` file.

### `tests/test_doc_counts.py`

**A spelled-out numeral immediately before a countable noun must equal the live
symbol.** The scan is deliberately narrow: a fixed list of `(noun, value)` pairs
in `COUNTED_NOUNS`, matched case-insensitively across line breaks, over the
three files in `TRACKED_DOCS`. Only word numerals are checked — `NUMBER_WORDS`
runs from one to `max(NUMBER_WORDS)` — so writing the digit is always safe, and
is the right move when you are unsure. Three further assertions in the same
module pin the rubric-criteria count in `docs/self-improvement.md`, the stage
count in the README, and the number of dotted edges the README's mermaid
diagram actually draws against `len(REVISIT_EDGES)`.

To protect a new claim, add a row:

```python
# tests/test_doc_counts.py
from src.ideation_panel import DEFAULT_LENSES        # import the live symbol
from src.information_flow import CHANNELS

COUNTED_NOUNS: tuple[tuple[str, int], ...] = (
    ("typed channels", len(CHANNELS)),
    ...
    ("proposer lenses", len(DEFAULT_LENSES)),        # your new row
)
```

Three things to get right. The value must be `len(SYMBOL)` or a call that
derives it — a literal here is the same rot you are trying to prevent, moved
one file over. The noun must be the *whole* phrase you want matched, because
the pattern anchors on a word boundary at each end: `"typed channels"` does not
also catch a bare `"channels"`. And the live value must stay inside
`NUMBER_WORDS`; a symbol that grows past `max(NUMBER_WORDS)` raises a `KeyError`
from `spelled()` instead of reporting a mismatch, so extend the table in the
same commit. `tests/test_declared_symbols_are_wired.py` imports `spelled` to pin
a count in its own module docstring, so the table's reach is not only the docs.

**No doc may cite a line number in this repo's own source.** Every
`something.py:123` in a `*.md` file at the repo root or in `docs/` is put to
`_is_in_this_repo`, which resolves exactly three ways: the reference as a path
relative to the repo root, its basename found by `rglob` under `src/`, or its
basename sitting at the repo root. `EXTERNAL_REFERENCE_PREFIXES` exempts
references into a pinned outside artifact.

Read that list as a floor, not as coverage. A *bare basename* belonging to
`tools/` or `tests/` resolves none of the three ways, so `score_rcb_run.py:42`
passes the gate — while the same citation written with its directory in front
of it is caught by the first resolution and fails. The rule is the same whether
or not the test can see you break it: cite the symbol —
`validate_stage_artifacts`, not a line — because a grep finds a symbol wherever
it moved and a line number rots on the next edit above it.

### `tests/test_score_rcb_run.py`

`NoSecretInTheRepositoryTest` runs `git ls-files`, reads every tracked file
under 2 MB, and fails on any match for the regex `sk-[A-Za-z0-9_-]{16,}` — an
OpenAI-shaped judge key. It skips itself when the tree is not a git checkout,
and it does not see untracked files, so `git add` first if you want the answer.

The trap is that it is a plain regex over prose, not over code. Anywhere the
letters `sk` are followed by a hyphen and then 16 or more characters drawn from
letters, digits, underscores and further hyphens, the scan sees a key — and an
ordinary hyphenated English phrase can produce exactly that, with no secret
anywhere near it. That has already flagged one innocent sentence in these docs.
Before you push a docs change:

```bash
git grep -nE 'sk-[A-Za-z0-9_-]{16,}'
```

If it hits your sentence, rewrite the sentence — do not add an exemption.

---

## Code conventions

Match the file you are editing. The house style, as it stands:

- **`from __future__ import annotations`** in every module, with modern
  annotations (`str | None`, `list[str]`) throughout. Sweeping every `.py`
  under `src/` plus `main.py`, `studio.py`, `rcb_agent.py` and `tools/` turns up
  five files without it: the two package `__init__.py` files, the two re-export
  shims (`src/studio_http.py` and `src/studio_service.py`, each a single import
  plus an `__all__`), and `studio.py`, which is not a shim — it imports `main`
  out of `src/backend/studio_http` and calls it under a `__main__` guard.
- **Frozen dataclasses** for anything serialized, with explicit `to_dict` and
  `from_dict`. Most dataclasses in `src/` are `frozen=True`, but the mutable
  remainder is not only ledgers, so do not read the pattern as "frozen unless it
  accumulates". Alongside the genuine ledgers (`GraphState`, `ObligationLedger`,
  `EffortPlan`, `IdeaPool`) sit one-shot scan results — `src/bootstrap.py` and
  `src/project_bootstrap.py` between them declare more than a dozen plain
  `@dataclass` types — plus small verdict records such as `TierDecision`,
  `Resolution`, `Scorecard` and `RevisionOutcome`. Freeze by default; leave it
  off when a field is assigned after construction, and match the file you are
  in. Write the round trip out as named methods even when the body is one
  `asdict` call, so the on-disk shape is visible in one place.
- **Defensive `from_dict`.** Coerce, default, and skip malformed entries
  rather than raising. A corrupt artifact should degrade a view, not kill a
  six-hour run.
- **Validators return `list[str]`**, never raise, never print. An empty list
  means valid; each string is one human-readable problem. The caller decides
  what to do.
- **Paths come from `RunPaths`.** Never join run paths by hand — add a field
  to `RunPaths` and `build_run_paths` instead.
- **Rendering goes through `TerminalUI`.** The manager does not print: there is
  no bare `print(` anywhere in `src/manager.py`, and its own `_print` helper is
  a one-line forward to `self.ui.write`.
- **Local imports for cycles.** `src/utils.py` imports its validators inside
  the functions that call them to avoid import cycles; keep that pattern rather
  than restructuring around it.
- **Comments explain *why*.** The existing comments mostly record a decision
  or a trap — for example why `claims.json` accepts both `statement` and
  `claim`. Match that density; do not narrate the code.

---

## Extending AutoR

### Change what a stage asks for

Edit the stage's template under `src/prompts/`. The default name is the slug on
the `StageSpec`, which already carries the stage number (`03_study_design.md`).
No code change, no test change. This is the right lever for most behaviour
changes, and it is worth trying before reaching for anything below.

**Check which file the run actually loads first.** `load_prompt_template` builds
two candidates and takes the first that exists: `<slug>_<format>.md`, where the
format comes from `resolve_output_format`, and only then `StageSpec.filename`
(the plain `<slug>.md`). Stage 07 is the one stage that ships a variant, and
because `DEFAULT_OUTPUT_FORMAT` is `markdown` and every `load_prompt_template`
call in `src/manager.py` — `_build_stage_prompt` and the two bootstrap prompt
builders — passes `selected_output_format(paths)`, an ordinary run reads
`07_writing_markdown.md`. Editing `07_writing.md` moves nothing until the run is
started with `--output-format latex`. Every other stage has one template, so the
fall-through is the only path it ever takes.

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
2. Create `src/prompts/<slug>.md` — `StageSpec.filename` is just
   `f"{slug}.md"`, so the file has to be named for the slug exactly.
3. Extend `validate_stage_artifacts` if the stage owns an artifact class.
4. Check everything that hard-codes a stage number — and enumerate it with
   `grep -rn 'stage.number' src/` rather than from a list in a doc, because the
   list is longer than the places you would think to look. It runs past the
   `stage.number >= N` ladder in `validate_stage_artifacts` into the per-stage
   rubric checks in `src/rubric.py`, the fake operator's per-stage artifact
   writer (`_write_fake_stage_artifacts`), the gates inside
   `_build_stage_prompt` in `src/manager.py` that freeze the preregistration,
   stamp the report plan and inject a missing-hypotheses block, and the extra
   prompt rule `_prohibitions` in `src/evolution.py` appends from Stage 05 on.
   Equality tests are their own set: `src/prompt_fragments.py`, `reviewed_stage_for` in
   `src/validity_review.py` (Stage 06 answers 05, Stage 07 answers 06), and
   `ROUND_CLOSING_STAGE_NUMBER` in `src/research_rounds.py`. The stage graph is
   the other half: it keys its edge table and `_ADVANCE_GUARDS` on slugs rather
   than numbers, so both need a new entry.

Stage numbers appear in enough places that this is the most invasive change on
this list.

The Studio is *not* on that list. It holds no table of stage display names: the
SPA renders `StageSpec.stage_title` exactly as `run_manifest.json` recorded it,
`studio_runner` finds the stage after a gate by taking the first `STAGES` entry
whose number is larger, and `studio_service` only ever compares one
`StageSpec.number` against another. All of that absorbs a new stage untouched.
The exception is the project card's progress ring in
`src/frontend/static/app.js`, which hard-codes the stage count more than once:
the approved-stage count is divided by 8 for the percentage, printed as
`${approvedCount}/8` in the ring label, and compared against 8 to decide the
"done" state. Search the file for the literal, not for the division.

### Add an execution backend

Implement [`OperatorProtocol`](../src/operator_protocol.py), or subclass
`ClaudeOperator` and override `_prepare_invocation`. `CodexOperator` is the
worked example, and it is five methods: `__init__`, where the Codex-specific
construction lands; `_prepare_invocation`; `_select_effective_session_id`; and
the two workspace-alias helpers, `_ensure_workspace_alias` and
`_rewrite_prompt_for_alias`.

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
returns a `ReviewDecision`. Changes here should make it stricter, not more
permissive — but know which runs it is actually the gate for.

`create_reviewer` returns a `ReviewPanel` instead whenever `use_panel` is set,
and `use_panel` is `args.review_panel`, which `--rigor max` turns on through
`_LEVEL_FEATURES` before the reviewer is built. Two separate questions, then.
Whether a reviewer is built at all is `approval_mode == "agent"`, which
`--full-auto`, `--review-panel` and `--approval-mode agent` each reach on their
own. Which reviewer it is turns only on `args.review_panel`: `--full-auto` or
`--approval-mode agent` alone gets `AutomatedReviewer`, and anything that sets
`review_panel` — `--review-panel`, or `--rigor max` with no other flag — gets
the panel. Under a panel, `main.py` still builds an `AutomatedReviewer` and
hands it to the manager as `solo_reviewer`,
but the manager only reaches for it when `effort_plan.is_routine(stage)` — so
editing this class then changes the routine-stage fallback and nothing else.
`ReviewPanel` in [`src/review_panel.py`](../src/review_panel.py) is the other
half of the same decision; both satisfy one `review_stage` contract, which is
why the manager never learns which it got.

---

## Repository layout

Where things live, one line each. This is a layout, not a module reference:
[architecture.md](architecture.md) has the responsibility table, and
[framework.md](framework.md) has the argument for why the groups are separated
at all. Every module under `src/` appears here except the two package
`__init__.py` files; re-derive with `find src -name '*.py'`.

Two mismatches to expect when you read the two pages side by side. Not every
module below has a row of its own in architecture.md's module map:
`settled_reasoning.py` is absent from that page altogether, while
`run_skills.py` and the two top-level Studio shims are mentioned only inside
another row's prose or in the paragraph after the Studio table. Diff the two
lists rather than trusting either. And the grouping is close but not identical:
architecture.md orders Improvement →
Self-measurement → Review where this page orders Improvement → Review →
Self-measurement, it files `archive.py` under Improvement and
`ideation_panel.py` under Review, and it calls the group named "Output and
adapters" below plain "Output". Neither page is generated from the other, so
adding a module means adding it twice.

```
main.py                     terminal entry point: CLI parsing, no workflow logic
studio.py                   Studio entry point (shim over src/backend/studio_http)
rcb_agent.py                ResearchClawBench adapter entry point
```

```
src/
  # Policy — which optional machinery this run uses at all
  rigor.py                  the one dial: fast / standard / thorough / max
  effort.py                 routine vs deliberative stages, and what that spent

  # The walk — which move is admissible, and which one is taken
  manager.py                ResearchManager, the control loop
  stage_graph.py            nodes, edges, guards, visit budgets, both topologies
  router.py                 the agent's pick among admissible moves, and refusals
  research_rounds.py        Stages 03-06 as a repeatable round
  terminal_ui.py            all terminal rendering

  # Gates — what a stage must produce to be accepted
  utils.py                  contract layer: stages, paths, prompts, validation
  manifest.py               run_manifest.json: lifecycle, rollback, staleness
  preregistration.py        freeze, amend, adjudicate, trace
  hypothesis_manifest.py    Stage 02 typed T*/H*/C* claims
  experimental_protocol.py  primary metric, seeds, per-baseline competence
  report_plan.py            figures committed at Stage 03, enforced at 03/06/07
  deliverables.py           did the run answer what the task actually asked?
  evidence_ledger.py        sources.json / claims.json, and citation verification
  artifact_index.py         scans data/, results/, figures/ into artifact_index.json
  experiment_manifest.py    results/experiment_manifest.json over that index
  writing_manifest.py       Stage 07 support scan and layout review
  validity_review.py        the adversarial pass after Stages 05 and 06

  # Improvement — which draft survives
  rubric.py                 weighted criteria read off disk, no backend call
  evolution.py              the champion ratchet and the verdict-drift rejection
  pareto.py                 non-dominated drafts kept beside the champion
  ideation_panel.py         Stage 02 divergence into a scored candidate pool

  # Review — the critics, two of which are the gate
  approval_agent.py         AutomatedReviewer, the solo approval gate
  review_panel.py           five seats, cross-examination, chair synthesis
  cross_reviewer.py         a second model family auditing an approval; veto only
  deliberation.py           the crux panel: 4 voices, resolved into a falsifiable answer
  stage_comments.py         anchored comments, diffed for collateral change
  obligations.py            what an approval says a later stage still owes
  review_policy.py          standing rules learned from this run's own refusals

  # Self-measurement — did any of the above earn its cost?
  scorecard.py              reads the feature ledgers into one end-of-run verdict
  archive.py                cross-run routes and edge payoffs (~/.autor/archive)
  decisions.py              "was offered the edge and declined" — the control arm
  trials.py                 paired A/B trials over archived runs
  inference.py              exact permutation tests and attainable-p floors

  # Context and inputs — what a stage gets to see
  information_flow.py       the typed channels, with declared readers per stage
  settled_reasoning.py      builds the settled-reasoning channel for Stage 07
  prompt_fragments.py       the rules every stage prompt shares, held once
  intake.py                 Stage 00 clarification and resource ingestion
  bootstrap.py              --paper-corpus
  project_bootstrap.py      --project-root
  prompts/                  stage templates by slug, plus intake, bootstrap, 07 markdown
  skills/                   agent skills installed into each run
  run_skills.py             installs src/skills/ into <run>/.claude/skills/

  # Execution — the backend, and everything around it
  operator_protocol.py      the interface the manager depends on
  operator.py               ClaudeOperator: sessions, streaming, resume, repair
  operator_codex.py         CodexOperator: subclass overriding the invocation
  web_search.py             Gemini-backed search and pre-run readiness assessment
  mcp_web_search.py         stdlib JSON-RPC MCP stdio server exposing that tool
  backend_health.py         "unreachable" told apart from "the research failed"

  # Output and adapters
  platform/foundry.py       paper package and release package
  diagram_gen.py            optional Gemini method diagram
  rcb.py                    the ResearchClawBench export contract

  # Studio
  backend/studio_http.py    stdlib ThreadingHTTPServer, routing, static assets, SSE
  backend/studio_service.py projects, runs, documents, previews, version history
  backend/studio_runner.py  drives real runs under the Studio's approval gate
  backend/sessions.py       logs_raw.jsonl parsed into renderable trace events
  backend/notebook.py       the Notebook view's conversation over a run
  frontend/static/          the Studio SPA: index.html, app.js, notebook.js, styles.css
  studio_http.py            back-compat shim re-exporting src/backend/studio_http
  studio_service.py         back-compat shim re-exporting src/backend/studio_service
```

```
tools/
  score_rcb_run.py          scores a finished benchmark workspace
  archive_sample_complexity.py   how many runs an archive edge needs to be believable
  web_search.py             standalone search entry point handed to operators by path
templates/registry.yaml     venue registry (parsed by hand, no YAML dependency)
configs/                    optional diagram config template
assets/                     screenshots, example figures, the paper gallery
tests/                      the unittest suite
docs/                       this documentation
.github/workflows/ci.yml    the only CI job
```

New code importing the Studio should use `src.backend.*`; the two top-level
shims exist for callers that predate the move.

### Agent skills

`src/skills/` holds long-form craft guidance — paper writing, citation
discipline, venue checklists, LaTeX repair, results tables, reproducibility
review. Each is a directory with a `SKILL.md` carrying YAML frontmatter (`name`
matching the directory, plus a `description` of at least 40 characters, since
that string is the only thing the model sees when deciding whether to open the
skill) and optionally a `reference.md` for the long tail.

`install_run_skills` copies the pack into `<run_root>/.claude/skills/` when a
run is created and again on resume. That location is not incidental: the
operator invokes its agent CLI with `cwd=run_root`, and Claude Code discovers
project skills at `<cwd>/.claude/skills/<name>/SKILL.md`. Skills left in the
AutoR checkout are never on that path and are never loaded.

Skills are the pull-based half of prompt assembly. Stage prompts are
concatenated up front and grow through the run; guidance that one stage needs
in one situation belongs in a skill, which is read only when the model judges
it relevant. Adding a skill costs nothing in prompts that do not use it.

**Pull-based is not the same as reachable.** Measured over a 40-task
ResearchClawBench arm at `2ffaeb4` — 16 skills installed per run, 19.7 h median
per run — the whole pack drew 78 `Skill` calls, and 31 of those were the single
skill a rendered stage prompt names imperatively. Thirteen skills were never
pulled once. Stage 05 pulled nothing in any of the forty runs. So a general skill
also has to be *named*, in the prompt of the stage whose decision it covers, in
the imperative: "Read the `x` skill before ...".
`tests/test_a_skill_is_named_where_it_is_needed.py` holds that, and it knows
which prompts the default configuration actually renders — `07_writing.md` and
`08_dissemination.md` are not among them, so a skill named only there is a skill
nobody is told about. Field skills are exempt: the discipline filter narrows them
to two per run, and that is a small enough field of candidates for pull-based
routing to work.

**A skill can also be scoped to a shape of task.** `applies_when` is a
case-insensitive regex in the frontmatter, matched against the run's research brief
plus its data manifest (`src/run_skills.py::routing_text`); `applies_unless` vetoes.
A skill carrying either is installed only for runs whose brief matches, and must also
carry `stages:` — the `task_shaped_skills` channel announces it in exactly those
stages' prompts, which is the only way to name a skill most runs will not have.
`validate_skill_pack` refuses a scoped skill with no stages, an unparseable regex, or
a stage slug that is not a stage.

Measure the predicate before it lands. It is a claim about a kind of research problem
and it fails silently in both directions — a regex matching thirty of forty briefs is
an unconditional skill with extra steps, and one matching none is a fourteenth skill
nobody will ever be offered:

```
python3 tools/skill_selectivity.py --from-runs /path/to/run/workspaces
python3 tools/skill_selectivity.py --briefs <dir> --expect <skill>:<task>,<task>
```

Prefer `--from-runs`: it reads each run's own `user_input.txt`, which is the file the
installer reads. The first version of that tool narrowed with `research_brief` alone
and reported a predicate selecting eight tasks the installer would have selected none
of, because `research_brief` drops the data manifest and the predicate keyed on it.

To add one: create `src/skills/<name>/SKILL.md` with matching frontmatter, and either
name it in a rendered stage prompt or give it `applies_when` plus `stages`.
`validate_skill_pack` is what defines "well-formed", and
`tests/test_run_skills.py` runs it over the shipped pack and then checks the
install lands where the CLI looks — so a malformed skill fails the suite rather
than silently never loading.

---

## Contributing

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for the pull-request process,
commit conventions, and what a reviewer will look for.
