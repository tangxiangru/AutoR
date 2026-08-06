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

---

## Requirements

| Requirement | Needed for |
| --- | --- |
| Python 3.10+ | everything |
| `claude` on `PATH` ([Claude Code](https://docs.claude.com/en/docs/claude-code)) | real runs with `--operator claude`, and all Studio runs |
| `codex` on `PATH` ([Codex CLI](https://developers.openai.com/codex/cli)) | real runs with `--operator codex` |
| A LaTeX toolchain (`pdflatex`/`latexmk`) | Stage 07 compiling a PDF |
| `pip install google-genai pyyaml` | `--research-diagram` only |

**AutoR itself has no third-party Python dependencies.** Everything but the
optional diagram feature runs on the standard library, which is why there is
no `requirements.txt` — there is nothing to put in it. `pip install` is
never a step in setting AutoR up.

Neither CLI backend is needed for `--fake-operator` runs or for the test
suite.

---

## `run_config.json`

Written to each run root. Full field reference in
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
| `approval_mode` | recorded value | `--full-auto` always forces `agent`. |
| `review_operator` | recorded value, else `operator` | |
| `review_model` | recorded value | If you pass `--review-operator` without `--review-model`, the new reviewer backend's default is used. |
| `created_at` | preserved | Never rewritten. |

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
my_venue_2027:
  display_name: "My Venue 2027"
  venue_type: "conference"        # conference | journal
  official_url: "https://..."
  style_package: "myvenue2027"    # matched against main.tex; "" for none
  bib_style: "plainnat"
  citation_style: "natbib"
  page_limit: 8                   # integer, or "flexible"
  refs_in_limit: false
```

No code change is needed — the registry is read at runtime. Note that the
parser is a small purpose-built one in `_load_template_registry`
([`src/utils.py`](../src/utils.py)), not a full YAML parser: keep entries to
flat `key: value` pairs under a top-level venue key, as the existing ones are.

`style_package` is what the [Stage 07 artifact gate](stage-contract.md#venue-matching)
looks for in `main.tex`. A run can always override the detection with a
`% AutoR venue: my_venue_2027` comment.

---

## Diagram generation (optional)

`--research-diagram` generates a method illustration with the Gemini API after
Stage 07 and injects it into the LaTeX paper. It is an enhancement: if it is
not configured, the step prints a failure line and the run continues.

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

defaults:
  model_name: "gemini-2.5-flash"
  max_critic_rounds: 2
```

Key resolution order: `GOOGLE_API_KEY`, then `GEMINI_API_KEY`, then
`api_keys.google_api_key`, then `api_keys.gemini_api_key` from the config file.
With none of them set, the step raises
`Gemini API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY ...`.

If `google-genai` is not installed you will see
`Diagram generation failed: No module named 'google'` — the rest of the run is
unaffected.

---

## Environment variables

AutoR reads very few environment variables of its own.

| Variable | Read by | Effect |
| --- | --- | --- |
| `GOOGLE_API_KEY` | `src/diagram_gen.py` | Gemini key for `--research-diagram`. |
| `GEMINI_API_KEY` | `src/diagram_gen.py` | Same, checked second. |
| `TERM` | `src/terminal_ui.py` | `TERM=dumb` disables colored output. Useful for CI logs and for piping to a file. |

Everything else — API keys, authentication, model access — belongs to the
`claude` or `codex` CLI, and is configured there, not in AutoR.

---

## Filesystem locations

| Path | Default | Override |
| --- | --- | --- |
| Runs | `<repo>/runs/` | `--runs-dir` (resolved relative to the repository root) |
| Studio project index | `<repo>/.autor/projects.json` | `python studio.py --metadata-root` |
| Prompt templates | `<repo>/src/prompts/` | — (derived from `--repo-root` in the Studio) |
| Venue registry | `<repo>/templates/registry.yaml` | — |
| Diagram config | `<repo>/configs/diagram_config.yaml` | — |

`runs/`, `.autor/`, and `configs/diagram_config.yaml` are all gitignored.

---

## Hard-coded limits

These are constants in [`src/utils.py`](../src/utils.py) rather than settings.
Change them in source if you must, and expect the tests to have an opinion.

| Constant | Value | Meaning |
| --- | --- | --- |
| `MAX_STAGE_ATTEMPTS` | 5 | Attempts before a stage escalates to you. |
| `DEFAULT_VENUE` | `neurips_2025` | Venue when `--venue` is omitted. |
| `DEFAULT_CODEX_SANDBOX` | `workspace-write` | Codex sandbox when unspecified. |
| stage timeout | 14400 s | Per-attempt ceiling — this one *is* a flag, `--stage-timeout`. |
| handoff window | 4 stages | How many prior handoff summaries enter a prompt. |
