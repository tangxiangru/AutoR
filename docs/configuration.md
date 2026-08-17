# Configuration

AutoR has deliberately little configuration. There is no global config file,
no environment-based profile system, and no database. What a run needs is
recorded inside that run.

Three things are configurable:

1. **Per-run settings** — `runs/<run_id>/run_config.json`, set from CLI flags
   and preserved across resume.
2. **Venue profiles** — `templates/registry.yaml`, shared across runs.
3. **Optional diagram generation** — `configs/diagram_config.yaml` or
   environment variables.

One thing is *state* rather than configuration: the cross-run archive at
`~/.autor/archive`, the only place AutoR writes outside the repository and
outside a run directory. See [Filesystem locations](#filesystem-locations).

---

## Requirements

| Requirement | Needed for |
| --- | --- |
| Python 3.10+ | everything |
| `claude` on `PATH` ([Claude Code](https://docs.claude.com/en/docs/claude-code)) | real runs with `--operator claude`, and all Studio runs |
| `codex` on `PATH` ([Codex CLI](https://developers.openai.com/codex/cli)) | real runs with `--operator codex` |
| A LaTeX toolchain (`pdflatex`/`latexmk`) | Stage 07 compiling a PDF — only with `--output-format latex`; the default markdown mode needs no TeX |
| `pip install google-genai` | the three Gemini-backed optional paths: `--web-search gemini`, `--research-diagram`, and `--cross-review` (live on both entry points; refused behind `--fake-operator`) |
| `pip install pyyaml` | reading the API key out of `configs/diagram_config.yaml`; not needed if you set the key in the environment |

**AutoR itself has no third-party Python dependencies.** Every import of one is
optional and guarded, which is why there is no `requirements.txt` — there is
nothing to put in it, and setting AutoR up needs no `pip install`. The table
above is not an exhaustive list of those guarded imports: `--paper-corpus` also
reaches for PyMuPDF (`import fitz` in `_extract_pdf_text`), and unlike the rows
above it degrades **silently** — every PDF in the corpus becomes a one-line
`[PDF file: … — install PyMuPDF …]` placeholder in the researcher profile that
seeds later stages, with no warning and no error. `pip install pymupdf` if you
point `--paper-corpus` at PDFs. To enumerate the rest rather than trust a list,
grep the tree for imports inside a `try`.

The three do not fail alike, and only one of them is a soft *unavailable*:

- **`--web-search gemini` is refused, not degraded.** `resolve_search_context`
  in `main.py` raises whenever `SearchReadiness.hard_blocker` is set — that is,
  when no Gemini backend is configured or `google-genai` is not importable by
  this interpreter — so the run exits during setup, before Stage 01. It is
  `--web-search auto`, not `gemini`, that falls back to the backend's native
  search. (A network-restricted Codex sandbox is deliberately *not* a hard
  blocker: it is inferred rather than observed, so it warns.)
- **`--research-diagram` warns and continues.** The call is wrapped; a missing
  package or key prints `Diagram generation failed: ...` and the stage stands.
- **`--cross-review` records an unavailable verdict.** `CrossVerdict` keeps
  `unavailable` distinct from agreement, so a reviewer that could not run is
  not counted as one that approved.

Neither CLI backend is needed for `--fake-operator` runs or for the test
suite.

---

## `run_config.json`

Written to each run root. Every field it can hold is in the table below;
per-field value ranges are in
[Run Artifacts](run-artifacts.md#run_configjson).

### What is preserved on resume

When you resume, AutoR reuses the recorded settings unless you override them.
The precedence rules differ slightly per field:

| Field | On resume, without a flag | Notes |
| --- | --- | --- |
| `operator` | recorded value | |
| `model` | recorded value | If you switch backends with `--operator` and give no `--model`, the *new* backend's default is used, not the old model name. A recorded `"unknown"` also falls back to the default. |
| `codex_sandbox` | recorded value | |
| `venue` | recorded value | |
| `output_format` | recorded value | `markdown` for new runs. A run started as `latex` stays `latex` on resume unless `--output-format` says otherwise. |
| `approval_mode` | recorded value | Three flags put an agent in the approval seat: `--approval-mode agent`, `--full-auto` and `--review-panel`. The last two force `agent` outright, on a resume as well as on a fresh run; `--approval-mode` is otherwise `None` on the CLI, which is what lets the recorded value survive. `--unattended` on its own is *not* one of them — it removes the human without installing a reviewer, so the first approval menu raises `UnattendedInputError` rather than being decided. |
| `review_operator` | recorded value, else `operator` | |
| `review_model` | recorded value | If you pass `--review-operator` without `--review-model`, the new reviewer backend's default is used. |
| `stage_graph` | recorded value | `--stage-graph` defaults to `None` on the CLI, not to `DEFAULT_STAGE_GRAPH`, so resuming a `linear` run without repeating the flag keeps it linear. |
| `routing_mode` | recorded value | Same mechanism as `stage_graph`. |
| `evolve_rounds` | recorded value | `2` for new runs. `0` measures without polishing. `--no-evolve` also forces it to `0`, because rounds steered by a score you are not computing mean nothing. |
| `evolve_measure` | recorded value | `true` for new runs. `--evolve-rounds N` with `N > 0` turns it back on. |
| `archive_steer` | recorded value | `false` for new runs. |
| `web_search` | recorded value | The *mode* (`auto`/`gemini`/`native`/`off`) is stored, never the resolved backend: `auto` is a question about the current environment, and freezing today's answer would make a resumed run assert something about the deployment that may no longer be true. |
| `min_report_figures` | recorded value | The Stage 07 figure floor, clamped into `[1, MAX_REPORT_FIGURES]` by `resolve_min_report_figures`. `1` for new runs; `rcb_agent.py` sets it to `BENCHMARK_MIN_REPORT_FIGURES` (3). No `main.py` flag sets it. |
| `created_at` | preserved | Never rewritten. |

The settings above are the whole of `run_config.json`: `initialize_run_config`
writes exactly this key set, and `default_run_config` returns the same one minus
`created_at`, which only a real run can have. The five walk settings
(`stage_graph`, `routing_mode`, `evolve_rounds`, `evolve_measure`,
`archive_steer`) go through `normalize_walk_settings`, which exists so the field
list is defined once instead of being restated by each reader and writer.
Per-field value ranges are in
[Run Artifacts](run-artifacts.md#run_configjson).

The one thing that is *not* configurable per run is the runs directory itself:
`--runs-dir` is where AutoR looks for the run, so it must match the directory
the run lives in.

### Model defaults

| Backend | Default model |
| --- | --- |
| `claude` | `sonnet` |
| `codex` | `default` |

`--model` takes an alias (`sonnet`, `opus`) or a full model name; AutoR passes
the value straight through to the backend CLI, so whatever that CLI accepts
works here.

---

## Venue registry

`templates/registry.yaml` holds venue metadata for Stage 07. AutoR stores
metadata only — it does **not** vendor official style packages, so the writing
stage fetches or reproduces the style itself.

### Available venues

| Key | Display name | Type | Style package | Bib style | Citation style | Page limit | Refs count toward limit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `neurips_2025` | NeurIPS 2025 | conference | `neurips_2025` | `plainnat` | `natbib` | 9 | no |
| `neurips_2026` | NeurIPS 2026 | conference | `neurips_2026` | `plainnat` | `natbib` | 9 | no |
| `iclr_2026` | ICLR 2026 | conference | `iclr2026_conference` | `iclr2026_conference` | `natbib` | 9 | no |
| `icml_2026` | ICML 2026 | conference | `icml2026` | `icml2026` | `natbib` | 8 | no |
| `cvpr_2026` | CVPR 2026 | conference | `cvpr` | `ieee_fullname` | `natbib` | 8 | no |
| `acl_2026` | ACL 2026 | conference | `acl` | `acl_natbib` | `natbib` | 8 | no |
| `aaai_2026` | AAAI 2026 | conference | `aaai2026` | `aaai2026` | `natbib` | 7 | yes |
| `ieee_conference` | IEEE Conference | conference | `IEEEtran` | `IEEEtran` | `cite` | 6 | yes |
| `ieee_journal` | IEEE Transactions / Letters | journal | `IEEEtran` | `IEEEtran` | `cite` | 14 | yes |
| `nature` | Nature | journal | — | `inline_or_manual` | `numeric` | 8 | yes |
| `nature_communications` | Nature Communications | journal | — | `inline_or_manual` | `numeric` | flexible | yes |
| `jmlr` | Journal of Machine Learning Research | journal | `jmlr2e` | `plain` | `numeric` | flexible | yes |

Default: `neurips_2025`.

### How `--venue` is matched

`resolve_venue_key` accepts any of:

- the registry key — `iclr_2026`
- the display name — `"ICLR 2026"`
- the style package name — `iclr2026_conference`

Matching ignores case, spaces, and punctuation, so `ICLR-2026` and `iclr 2026`
both resolve. An unmatched value raises `Unknown venue: <value>`.

Set the venue at the start of a run. It shapes Stage 07's structure, page
budget, and citation style, and switching late means rewriting the manuscript.

### Adding a venue

Append a block to `templates/registry.yaml`:

```yaml
# venue_type is "conference" or "journal".
# style_package is matched against main.tex; use "" for a venue with none.
# page_limit is an integer, or the string "flexible".
my_venue_2027:
  display_name: "My Venue 2027"
  venue_type: "conference"
  official_url: "https://..."
  style_package: "myvenue2027"
  bib_style: "plainnat"
  citation_style: "natbib"
  page_limit: 8
  refs_in_limit: false
```

No code change is needed — the registry is read at runtime.

**Two things the parser will not forgive.** `_load_template_registry`
([`src/utils.py`](../src/utils.py)) is a small purpose-built reader, not a YAML
implementation:

- **Keep entries flat.** `key: value` pairs, indented two spaces under a
  top-level venue key, exactly as the existing entries are. A nested mapping or
  a list is not understood.
- **No trailing comments.** A whole line beginning with `#` is skipped — which is
  why the explanations above sit above the block rather than beside the fields —
  but a comment *after* a value is swallowed into that value. The reader splits
  on the first `:` and strips only whitespace and one layer of quotes, so
  `venue_type: "conference"   # conference | journal` is stored as
  `conference"   # conference | journal`. Nothing in the shipped registry carries
  an inline comment, so nothing in the repo would catch it for you, and nothing
  refuses the file either: `resolve_venue_key` still finds the venue by its key,
  and the damage surfaces downstream. `format_venue_for_prompt` sends
  `venue_type`, `page_limit`, `citation_style` and `style_package` into the
  Stage 07 prompt verbatim, comment and all, and the corrupted `style_package`
  becomes a marker no `main.tex` can match — the venue key and `display_name`
  are what keep the gate passing, which is precisely why the failure is quiet.

The `style_package` — along with the venue key and the `display_name` — is what
the [Stage 07 artifact gate](stage-contract.md#venue-matching) looks for in
`main.tex`; a venue with no style package is matched on the other two. A run can
always override the detection with a `% AutoR venue: my_venue_2027` comment.

---

## Web search (optional)

Stage 01 needs real search. Some coding-agent deployments ship with the
built-in `WebSearch` tool disabled — notably **Claude Code on Vertex AI** —
which leaves the stage unable to search at all.

`--web-search gemini` routes searches through Gemini's Google Search grounding
instead. Two backends work; AutoR picks whichever is configured:

```bash
# Vertex AI — no API key, uses Application Default Credentials
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="your-project"
python main.py --web-search gemini --goal "..."

# or the Gemini Developer API, using the same key as diagram generation
export GEMINI_API_KEY="..."
python main.py --web-search gemini --goal "..."

# The tool is also usable on its own:
python tools/web_search.py "black hole superradiance constraints" --json
```

An explicit API key wins over Vertex; `AUTOR_WEB_SEARCH_BACKEND=vertex|api_key`
forces the choice. On a box already running Claude Code on Vertex,
`ANTHROPIC_VERTEX_PROJECT_ID` is inherited as a last-resort project, so
`--web-search auto` works with no extra configuration — which matters, because
that is precisely the deployment where the built-in `WebSearch` tool is
disabled.

`auto` (the default) uses Gemini when a key is configured and falls back to the
backend's native search otherwise, so it never advertises a tool that would
fail on first use. Details in
[ResearchClawBench → Web search](researchclawbench.md#web-search-on-deployments-where-websearch-is-disabled).

### `--web-search off`

The other three modes are a choice of *which* search the agent uses, and all
three end with it holding one. `off` is the negation: no Gemini prompt section
is injected, no credentials are looked for, and `WebSearch` and `WebFetch` are
named to the Claude CLI as denied via `--disallowed-tools`. It exists for a
benchmark whose published protocol is "without browsing", where `native` — the
closest thing available before — says the opposite, and on a deployment where
the built-in tool works it *is* browsing with no prompt block to show for it.

**It narrows the path to the network; it does not close it.** `Bash` stays
available, because the stages write files and run scripts through it, and
`curl` lives inside `Bash`. So whether a run browsed is a question for its tool
calls, answered after the fact from the transcript, and not something this flag
can promise. Do not read `off` as a guarantee about what the agent could do —
read it as the removal of the two tools it would otherwise reach for first.

---

## Diagram generation (optional)

`--research-diagram` generates a method illustration with the Gemini API once
Stage 07 is approved, and injects it into whichever deliverable the run
produces. `post_writing_diagram_hook` branches on the run's `output_format`:

| Output format | Reads the method text from | Injects into |
| --- | --- | --- |
| `markdown` (the default) | the method section of `report/report.md` | `report.md`, as `![...](images/method_overview.png)`, with the image saved under `report/images/` so the path resolves relative to the report as the benchmark judge needs. The backend returns JPEG bytes whatever the filename says, so the file is re-encoded to PNG when Pillow is importable and left as `method_overview.jpg` when it is not — an honest `.jpg` beats a `.png` holding JPEG bytes |
| `latex` | `writing/sections/method.tex` | `method.tex`, as a `figure*` block referencing `../figures/method_overview.jpg`, which is the path `pdflatex` resolves from `main.tex` rather than from the included section |

Because `DEFAULT_OUTPUT_FORMAT` is `markdown`, the markdown row is what a run
gets unless it was started with `--output-format latex`. Either way the step
skips itself rather than failing the stage when the source text is missing or
shorter than 100 characters.

It is an enhancement, never a gate: the call is wrapped, so if it is not
configured the run logs and prints `Diagram generation failed: ...` and
continues.

### Setup

```bash
pip install google-genai pyyaml
export GOOGLE_API_KEY="..."      # or GEMINI_API_KEY
```

Or, instead of the environment variable:

```bash
cp configs/diagram_config.template.yaml configs/diagram_config.yaml
# then fill in api_keys.google_api_key
```

`configs/diagram_config.yaml` is gitignored.

```yaml
api_keys:
  google_api_key: ""        # or gemini_api_key
```

That is the whole of the file AutoR reads. The shipped
`configs/diagram_config.template.yaml` also carries a `defaults:` block
(`model_name`, `max_critic_rounds`), and nothing consumes it:
`_api_key_from_config_file` in [`src/web_search.py`](../src/web_search.py) is
the file's only reader and looks at `api_keys` alone, while `src/manager.py`
calls `post_writing_diagram_hook` without a `model_name`, so the function's own
parameter defaults are what run. Editing those two values changes nothing.

Key resolution order: `GOOGLE_API_KEY`, then `GEMINI_API_KEY`, then
`api_keys.google_api_key`, then `api_keys.gemini_api_key` from the config file.
With none of them set, the step raises
`Gemini API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY ...`.

The resolver lives in [`src/web_search.py`](../src/web_search.py) and is shared
with Gemini-backed web search, so a key configured for one feature works for
the other.

If `google-genai` is not installed you will see
`Diagram generation failed: No module named 'google'` — the rest of the run is
unaffected.

---

## Environment variables

AutoR reads very few environment variables of its own.

| Variable | Read by | Effect |
| --- | --- | --- |
| `GOOGLE_API_KEY` | `src/web_search.py` | Gemini key for all three Gemini paths: `--research-diagram`, `--web-search gemini`, and `--cross-review`. `resolve_gemini_api_key` is the single resolver; `src/diagram_gen.py` delegates to it so the features cannot drift apart. |
| `GEMINI_API_KEY` | `src/web_search.py` | Same, checked second. |
| `AUTOR_WEB_SEARCH_MODEL` | `src/web_search.py` | Model for Gemini-backed web search. Defaults to `gemini-2.5-flash` on the Gemini API and `gemini-3.6-flash` on Vertex AI. |
| `GEMINI_MODEL` | `src/web_search.py` | Same, checked second. |
| `AUTOR_WEB_SEARCH_BACKEND` | `src/web_search.py` | Force `vertex` or `api_key` instead of auto-detecting. |
| `AUTOR_VERTEX_PROJECT` | `src/web_search.py` | Vertex AI project for web search. Falls back to `GOOGLE_CLOUD_PROJECT`, then `ANTHROPIC_VERTEX_PROJECT_ID`. |
| `AUTOR_VERTEX_LOCATION` | `src/web_search.py` | Vertex AI location. Falls back to `GOOGLE_CLOUD_LOCATION`, then `global`. |
| `TERM` | `src/terminal_ui.py` | `TERM=dumb` disables colored output. Useful for CI logs and for piping to a file. |

Everything else — API keys, authentication, model access — belongs to the
`claude` or `codex` CLI, and is configured there, not in AutoR.

---

## Filesystem locations

| Path | Default | Override |
| --- | --- | --- |
| Runs | `<repo>/runs/` | `--runs-dir` (resolved relative to the repository root) |
| **Cross-run archive** | **`~/.autor/archive`** (`DEFAULT_ARCHIVE_DIR`) | **`--archive PATH`; `--no-archive` writes nothing** |
| Studio project index | `<repo>/.autor/projects.json` | `python studio.py --metadata-root` |
| Prompt templates | `<repo>/src/prompts/` | — (derived from `--repo-root` in the Studio) |
| Venue registry | `<repo>/templates/registry.yaml` | — |
| Diagram config | `<repo>/configs/diagram_config.yaml` | — |

`runs/`, `.autor/`, and `configs/diagram_config.yaml` are all gitignored.

**The archive is the only state AutoR writes outside the repository and outside
a run directory.** It lives under the user's home rather than the checkout on
purpose: it outlives any one clone, and an archive inside a clone would be
deleted with it. Each finished run records its route and measured fitness there,
and each graph edge is compared against runs that reached the same node and
*declined* it. Recording is best-effort — a failure to record warns and does not
end the run — and it is recording only: the archive cannot change the topology a
run uses unless `--archive-steer` says so, and even then it may only reorder
edge preferences, never open a guarded edge. `--archive-report` and
`--trial-report` read it and exit; both are refused under `--no-archive`,
because there is nothing to read.

---

## Hard-coded limits

Constants rather than settings. Change them in source if you must, and expect
the tests to have an opinion. These tables are a **selection, not an
inventory**: they cover the defaults a flag overrides and the thresholds most
likely to explain a refusal you are looking at, but there are gating constants
under `src/` that are not here. `grep -rnE '^[A-Z_]+ *=' src/` is the
authoritative list.

### Defaults a flag can override

| Constant | Module | Value | Flag |
| --- | --- | --- | --- |
| `MAX_STAGE_ATTEMPTS` | `utils.py` | 5 | `--max-attempts` — attempts per stage before it escalates or is auto-skipped. `rcb_agent.py` defaults to 8 instead. |
| `DEFAULT_VENUE` | `utils.py` | `neurips_2025` | `--venue` |
| `DEFAULT_CODEX_SANDBOX` | `utils.py` | `workspace-write` | `--codex-sandbox` |
| `DEFAULT_OUTPUT_FORMAT` | `utils.py` | `markdown` | `--output-format` |
| `DEFAULT_STAGE_GRAPH` | `utils.py` | `adaptive` | `--stage-graph` |
| `DEFAULT_ROUTING_MODE` | `utils.py` | `auto` | `--routing` (the flag is not named after the field) |
| `DEFAULT_WEB_SEARCH_MODE` | `utils.py` | `auto` | `--web-search` |
| `NO_BROWSING_DISALLOWED_TOOLS` | `web_search.py` | `WebSearch`, `WebFetch` | `--web-search off` — the tool names handed to the Claude CLI's `--disallowed-tools`. `Bash` is deliberately not among them: denying it would not produce a no-browsing run, it would produce no run. |
| `DEFAULT_EVOLVE_ROUNDS` | `utils.py` | 2 | `--evolve-rounds` (`DEFAULT_ROUNDS` in `evolution.py` is the same number) |
| `DEFAULT_MAX_STEPS` | `stage_graph.py` | 20 | `--graph-max-steps` — stage executions in one walk, whatever the per-node budgets allow |
| `DEFAULT_MAX_VISITS` | `stage_graph.py` | 3 | `--graph-max-visits` — entries into one stage; the fourth is a loop |
| `DEFAULT_MAX_DELIBERATIONS` | `deliberation.py` | 3 | `--max-deliberations` — cruxes a run may escalate to a panel before the budget is refused |
| `DEFAULT_ARCHIVE_DIR` | `main.py` | `~/.autor/archive` | `--archive`, `--no-archive` |
| stage timeout | `main.py` argparse default | 14400 s (4 h) | `--stage-timeout` |
| auto-skip budget | `main.py` argparse default | 3 stages | `--max-auto-skips` |
| rounds of Stages 03–06 | `main.py` argparse default | 1 | `--max-rounds` |

### The Stage 07 deliverable

No `main.py` flag reaches any of these; they are the shape of the deliverable.

| Constant | Module | Value | Meaning |
| --- | --- | --- | --- |
| `MIN_REPORT_CHARS` | `utils.py` | 1200 | Below this, `report.md` is a stub rather than a deliverable. |
| `MIN_REPORT_FIGURES` | `utils.py` | 1 | The published-figure floor for an ordinary run, and the `default_run_config` value of `min_report_figures`. |
| `BENCHMARK_MIN_REPORT_FIGURES` | `utils.py` | 3 | The floor `rcb_agent.py` sets instead. Most ResearchClawBench tasks carry two or more image criteria. |
| `MAX_REPORT_FIGURES` | `utils.py` | 5 | The ceiling, and what `resolve_min_report_figures` clamps the floor to. Only the first five images a judge finds are shown, in filesystem order. |
| `MAX_HEADLINE_NUMBERS` | `report_plan.py` | 8 | Numbers the report leads with, not an inventory of everything measured. |
| `MIN_SHOWS_CHARS` | `report_plan.py` | 40 | A figure slot's `shows` sentence; also the floor on `no_figures_because`. |
| `MIN_DROP_REASON_CHARS` | `report_plan.py` | 20 | A `dropped_because`; also `MIN_BRANCH_CHARS` for `if_supported`/`if_refuted`, and for the `why_not` on an unattempted `task_output`. |
| `MIN_EXPLORATORY_SLUG_CHARS` | `report_plan.py` | 3 | A slot that supports `exploratory:<slug>` needs a slug this long, so `exploratory:` cannot be a wildcard five slots share. |
| `JUDGE_VISIBLE_PREFIX_CHARS` | `report_plan.py` | 10000 | How much of the prose a figure grader reads, so the lead figure has to be referenced inside it. |

### Evidence, review and the archive

| Constant | Module | Value | Meaning |
| --- | --- | --- | --- |
| `MIN_SEEDS_FOR_A_VERDICT` | `experimental_protocol.py` | 2 | A `supported`/`refuted` verdict on one run needs a written `single_run_justification`. Not a statistical threshold — a floor under "we ran it more than once". |
| `MIN_ARTIFACT_BYTES` | `rubric.py` | 32 | Below this a file is not evidence a stage produced anything. |
| `MIN_QUOTE_CHARS` | `stage_comments.py` | 12 | An anchored comment must quote at least this much to be locatable. |
| `MIN_OBLIGATION_CHARS` / `MAX_OBLIGATIONS` | `obligations.py` | 20 / 30 | What a later stage owes, and how much of it may accumulate. |
| `MIN_RULE_CHARS` / `MAX_RULES` | `review_policy.py` | 25 / 40 | Standing rules learned from this run's own refusals. |
| `MIN_REASON_CHARS` | `cross_reviewer.py` | 40 | A cross-model *refusal* shorter than this is ignored and recorded as agreement: a veto that cannot be acted on should not bounce a stage. |
| `MIN_QUESTION_CHARS` | `deliberation.py` | 25 | A crux request shorter than this is dropped before the panel is seated — "what should we do about the data?" has no answer. |
| `DEFAULT_MIN_GAIN` | `evolution.py` | 0.005 | Rubric total a polish round must gain to count as an improvement. |
| `DEFAULT_PATIENCE` | `evolution.py` | 2 | Flat rounds before a stage is declared polished. |
| `DEFAULT_MIN_GAIN` | `archive.py` | 0.02 | Mean fitness a challenger topology must beat the incumbent by. Roughly one rubric criterion moving a quarter of its range. |
| `DEFAULT_MIN_OBSERVATIONS` | `archive.py` | 6 | Runs an edge needs before the archive will act on it. **Derived, not written down**: `minimum_arms_for(ALPHA, family=len(REVISIT_EDGES) + len(STAGES))`, so adding an edge re-corrects it instead of silently under-correcting. |
| `MIN_PAIRS_FOR_SIGNIFICANCE` | `trials.py` | 6 | Below this, an exact two-sided sign-flip test cannot reach p < 0.05 at *any* effect size, because it bottoms out at 2 / 2ⁿ. A smaller trial is labelled `underpowered`. |
| `MAX_EXACT_PAIRS` | `trials.py` | 18 | Pairs up to which `sign_flip_p` enumerates every sign assignment. 2¹⁸ takes 0.27 s; above it the null is sampled instead. `sign_flip_estimator` is the only line that compares against it, so which computation ran is one answer and the report reads that one. It used to decide how many differences the test looked at as well, which returned p = 0.0 at sixty pairs. |
| `SAMPLED_SIGN_ASSIGNMENTS` | `trials.py` | 200,000 | Size of the sampled reference set above `MAX_EXACT_PAIRS`, and therefore the floor the report prints there (5e-6). Costs 0.08 s at sixty pairs. |
| `SIGN_FLIP_SEED` | `trials.py` | 20260817 | Seed for that sample, printed in the report. A Monte-Carlo p that moves between two renderings of the same trial is a number a reader cannot check. |

### Prompt assembly

| What | Where | Value | Meaning |
| --- | --- | --- | --- |
| handoff window | `build_handoff_context(max_stages=…)` in `utils.py` | 4 stages | How many prior handoff summaries enter a prompt. A default parameter, not a module constant. |
