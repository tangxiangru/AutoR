# Running AutoR on ResearchClawBench

[ResearchClawBench](https://github.com/InternScience/ResearchClawBench) evaluates whether an
agent can conduct research end to end: it hands the agent a workspace of raw data and
reference papers, lets it work unsupervised, and then scores the resulting
`report/report.md` against the original published paper with a multimodal LLM judge.

AutoR runs it through `rcb_agent.py`. No human is involved at any point — the approval gate
is a reviewer agent (a second Claude Code instance), and every remaining terminal prompt is
a hard error rather than a hang.

---

## Quick start

```bash
# 1. Point ResearchClawBench at AutoR by adding this entry to evaluation/agents.json.
# 2. Restart the ResearchClawBench server, pick "AutoR", hit Start Run.
```

```json
{
  "autor": {
    "label": "AutoR",
    "icon": "A",
    "logo": "/static/logos/anthropic.svg",
    "cmd": "python3 /abs/path/to/AutoR/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT>"
  }
}
```

The harness substitutes `<WORKSPACE>` with the absolute workspace path and `<PROMPT>` with
the contents of the generated `INSTRUCTIONS.md`. Both flags are optional when running by
hand: the workspace defaults to the current directory (which is what the harness sets it
to) and the instructions default to `<workspace>/INSTRUCTIONS.md`.

Run one task manually:

```bash
cd /path/to/ResearchClawBench
python3 -m evaluation            # start the UI, or build a workspace yourself

cd workspaces/Astronomy_000_20260806_015140
python3 /abs/path/to/AutoR/rcb_agent.py
```

---

## What the adapter does

### 1. Removes the human

| Interaction point | Before | Now |
|:---|:---|:---|
| "Do you have existing resources to include?" | Blocked on stdin **even with `--full-auto`** | Never asked unattended |
| Intake clarification Q&A | Reviewer agent answers (already automatic) | unchanged |
| Stage approval gate | Reviewer agent decides (already automatic) | unchanged |
| Stage exhausted its retries | Blocked on a TTY, aborted the whole run otherwise | Auto-skips, bounded by `--max-auto-skips` |
| Any prompt missed by the above | Would hang the benchmark silently | Raises `UnattendedInputError` |

That last row is the important one. Unattended mode does not merely avoid known prompts —
`TerminalUI` refuses to read stdin at all, so a future prompt added anywhere in the codebase
fails loudly on the first run instead of hanging a benchmark job for hours.

### 2. Bridges the output contract

Stage 07 runs in **markdown mode** by default (`--output-format markdown`), so the report
the benchmark scores is the pipeline's own gate-checked deliverable rather than a
translation of one. AutoR writes it to `workspace/report/report.md` in the run tree; the
adapter copies it to the benchmark path. In `--output-format latex` Stage 07 produces the
submission-oriented paper package instead and the report is synthesized afterwards.

After the pipeline finishes — **whether or not it succeeded** — the adapter exports:

| Benchmark path | Source |
|:---|:---|
| `report/report.md` | see below |
| `report/images/*.png` | `workspace/report/images` first, then `figures`, `writing`, `results`, `artifacts` (PNG only, capped — see below) |
| `code/` | `workspace/code` |
| `outputs/` | `workspace/results` and `workspace/notes`, **images excluded** — and any image a stage wrote straight to `<workspace>/outputs/`, or anywhere under `<workspace>/report/` other than a published slot, is deleted; see below |

Run-tree figures under `report/images/` keep their filenames, because those are the names
`report.md` references. A same-named figure swept up from elsewhere is the one that gets
qualified.

#### The five image slots

This is where most of the score is. Across the 40 shipped tasks, 91 of 154 checklist items
are `type: image` and they carry **60.6% of total weight** (median 62.5%; images are the
strict majority of weight in **24 of 40** tasks and at or above half in 25 — `Material_000`
is exactly 50/50). Every number in this section is re-derivable from
`tasks/*/target_study/checklist.json`: sum `weight` grouped on `type` for the weights, count
the `type: image` entries per task for the criterion counts. They move when the task set
does, and they were last measured on 2026-08-10 against the 40 shipped tasks.

The judge is **not** shown five images chosen for the item. `evaluation/score.py` collects
one set per *workspace* and hands the first five of that same set to every image criterion:

```python
generated_images = _find_generated_images(workspace)               # once, per workspace
...
for search_dir in [workspace / "outputs", workspace / "report"]:   # outputs first
    for ext in IMAGE_EXTENSIONS:
        images.extend(search_dir.rglob(f"*{ext}"))                 # filesystem order
...
for img in generated_images[:5]:                                   # per item, the same five
```

Four consequences drive the export, and the plan the run writes at Stage 03:

1. **`outputs/` is drained before `report/`.** A diagnostic plot there takes a slot from a
   figure the report argues with, so images are excluded from the `outputs/` mirror
   entirely — the machine-readable results still go across — **and** `collect_figures`
   deletes any image a stage wrote directly to `<workspace>/outputs/`, which the goal
   contract's own instruction to keep `outputs/` up to date makes easy to do by accident.
   Withholding them from the mirror is only half the defence: six stray PNGs there take all
   five slots and the report's figures reach the judge as nothing.
2. **`rglob` order is filesystem order, not alphabetical.** Naming cannot influence which
   five survive. The only lever is publishing no more than five — so `collect_figures`
   enforces `MAX_REPORT_FIGURES`, picks by the report's own reference order, and prunes
   anything else already at the benchmark path. A figure the report references is never
   pruned; Stage 07's gate is what keeps a run from arriving over budget.
   The prune is the *same walk* as the sweep, over both trees: `rglob` over `outputs/` and
   over `report/`, not `iterdir()` over `report/images/`. `report/images/` is not the only
   place under `report/` the scorer looks, so a loose `report/panel.png` or a nested
   `report/images/panels/*.png` takes a slot exactly the way a stray `outputs/` plot does —
   and both sort *ahead* of `report/images/` in the walk. The only images that survive the
   prune are the published slots and any image the winning report links directly.
3. **No shipped task has more than five image criteria**, and 34 of 40 have three or fewer
   (distribution over image criteria per task: 0×3, 1×10, 2×9, 3×12, 4×3, 5×3). Five is a
   ceiling, not a target. The weight is earned by figures that settle *different* questions;
   several views of one result spend most of the budget on one criterion.
4. **Image criteria are shown only the first 10,000 characters of `report.md`**
   (`report_text[:10000]` in `_build_image_prompt`; `_build_text_prompt` interpolates
   `report_text` whole, so text criteria are *not* truncated). This is an ordering
   constraint, not a length limit, and the goal text has to say so in those words: the
   ~39% of weight the text criteria carry reads the entire report, so a run told its report
   is "forfeited" past 10,000 characters would cut methodology and discussion that were
   still being scored. The headline numbers, the results and the figure captions come
   first; everything else comes after them, not instead of them.
   That number is the benchmark's, not AutoR's: it lives in this file and in
   `build_benchmark_goal`'s prose, and deliberately not as a constant in `src/` — nothing in
   AutoR should start truncating on it.

A sixth figure does not add a sixth chance to match. It randomises which five are seen.

#### Where the five are chosen

Not at export, and not at Stage 07. The run commits to its figures at **Stage 03**, in
`workspace/notes/report_plan.json`: one entry per slot, each naming the claim it settles,
what the reader should see, what the figure looks like if that claim holds and if it does
not, and the result file it will be computed from. Stage 06 produces them, Stage 07
publishes them in slot order, and — in markdown mode, which is what the benchmark runs — a
planned figure that was neither published nor explicitly dropped is a refusal rather than a
silence. `docs/stage-contract.md` carries the gate rows and `src/report_plan.py` the
validator.

That machinery is **not** benchmark-specific. It is the discipline
`hypothesis_manifest.json` and `experimental_protocol.json` already apply — commit to the
choice before the results can influence it — applied a third time, to figures, and every
AutoR run gets it. What *is* benchmark-specific is everything above: the ~61% image weight,
the one fixed set of five, the 10,000-character excerpt and the `outputs/`-before-`report/`
sweep. Those reach the run through one place only, `build_benchmark_goal`, which a
non-benchmark run never receives. Outside the benchmark a markdown run is told only that at
most `MAX_REPORT_FIGURES` figures reach its reader — which `validate_markdown_report` has
always enforced — and a LaTeX run is told there is no ceiling at all.

#### Reference papers

Every task ships curated PDFs in `related_work/`. They are registered as run resources, so
they land in `workspace/literature/` where Stage 01 reads them, and each one is named
individually in the goal contract. Without this the literature survey searches the web and
cannot cite the very work it is reproducing.

#### Where the run stops

`--final-stage` defaults to `07_writing`. Stage 08 produces posters, slides, release notes
and readiness checklists that the judge never opens; the wall-clock is better spent on
analysis. Pass `--final-stage 08_dissemination` for the full workflow.

The report comes from the first of four paths that yields real content:

1. **`agent`** — something wrote `report/report.md` at the benchmark path directly. The goal
   contract injected into every stage prompt names the exact path.
2. **`stage`** — Stage 07 ran in markdown mode, so its gate-checked report already exists in
   the run tree and is promoted verbatim. **This is the normal case.**
3. **`synthesized`** — one extra operator call converts the approved artifacts into the
   benchmark's markdown format. This is what a `latex` run uses.
4. **`fallback`** — pure-Python assembly from the approved stage summaries, with any
   auto-skipped stages named explicitly. AutoR's own control-loop headings
   (`Your Options`, `Decision Ledger`, `Previously Approved Stage Summaries`) are stripped:
   a judge told to be skeptical reads them as an agent's run log, not as research.

A partial report scores better than no report, so a crashed or incomplete pipeline still
exports everything it produced. The exit code tracks whether a report reached the harness,
not whether every stage was approved.

#### What markdown mode changes inside the pipeline

| | `markdown` (default) | `latex` |
|:---|:---|:---|
| Stage 07 prompt | `src/prompts/07_writing_markdown.md` | `src/prompts/07_writing.md` |
| Deliverable | `workspace/report/report.md` | `main.tex` + `sections/*.tex` + compiled PDF |
| Figures | `workspace/report/images/*.png`, referenced as `images/<name>.png` | `workspace/figures`, `\includegraphics` |
| Triage artifact | `artifacts/report_review.json` | `artifacts/layout_review.json` |
| Also required | `citation_verification.json`, `self_review.json` | same, plus `build_log.txt` and a `.bib` |
| Figure budget | at most 5, all referenced | none |
| Report plan | required at Stage 03; every slot must be published or carry `dropped_because` | required at Stage 03; coverage not checked |
| Post-approval | — | `writing/paper_package/` bundle |

The markdown gates are not "a file exists". Stage 07 fails and retries if `report.md` is
shorter than 1,200 characters, references no figures, still holds placeholder text, or
carries a figure reference that is absolute, remote, unrenderable, or points at a file that
is not there, or publishes more than five figures, or leaves a figure the Stage 03 plan
committed to neither published nor explicitly dropped. A broken figure link is the expensive
defect here: the judge reads the prose promising a figure and is shown nothing.

The coverage check is narrowed to markdown on purpose: a LaTeX run has no single
well-defined published-figure location for it to match against, and `layout_review.json`
covers that branch instead.

### 3. Spends the time it is given

Neither the UI runner nor the batch CLI puts a timeout on the agent subprocess — the
`max_runtime_seconds` in the shipped configs is a ResearchHarness-internal setting, not
something the harness enforces. Nothing outside AutoR will stop a run, so the adapter's own
ceilings are the only ones that bind, and they are set for quality rather than thrift:
`--stage-timeout 14400` and `--max-attempts 8`. Every retry re-runs the stage with its
validation errors attached, and an exhausted stage is auto-skipped, which is the expensive
outcome.

### 4. Streams progress

`rcb_agent.py` writes JSON lines to stdout, which the harness captures into
`_agent_output.jsonl`. The first line carries the model name so the run browser can display
it.

---

## Web search on deployments where `WebSearch` is disabled

Stage 01 (Literature Survey) needs real search. Some Claude Code deployments — notably
**Claude Code on Vertex AI** — ship with the built-in `WebSearch` tool disabled, which
quietly guts that stage: the agent cannot search, so it either stalls or invents citations.

AutoR ships a replacement backed by Gemini's Google Search grounding. It reaches Gemini
two ways, and picks whichever is configured:

```bash
# Vertex AI (no API key needed) — the natural fit if you already run Claude Code on Vertex
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project        # or AUTOR_VERTEX_PROJECT

# or the Gemini Developer API
export GEMINI_API_KEY=...                       # or GOOGLE_API_KEY, or configs/diagram_config.yaml

python3 tools/web_search.py "black hole superradiance constraints"
python3 tools/web_search.py "diffusion model scaling laws" --json --max-results 8
```

| | Vertex AI | Gemini Developer API |
|:---|:---|:---|
| Auth | Application Default Credentials | API key |
| Project | `AUTOR_VERTEX_PROJECT`, `GOOGLE_CLOUD_PROJECT`, or `ANTHROPIC_VERTEX_PROJECT_ID` | — |
| Location | `AUTOR_VERTEX_LOCATION`, `GOOGLE_CLOUD_LOCATION`, default `global` | — |
| Default model | `gemini-3.6-flash` | `gemini-2.5-flash` |

An explicit API key wins over Vertex, because setting one is deliberate whereas the Vertex
project is often inherited from the host's Claude Code configuration. Force the choice with
`AUTOR_WEB_SEARCH_BACKEND=vertex|api_key`.

`ANTHROPIC_VERTEX_PROJECT_ID` is consulted last and on purpose: a box already running Claude
Code on Vertex has it set, and that is exactly the deployment where the built-in `WebSearch`
tool is disabled and this module is needed. On such a box `--web-search auto` just works
with no extra configuration.

**Grounding redirects.** Vertex returns citations as opaque
`vertexaisearch.cloud.google.com/...` stubs rather than source URLs. The tool follows each
one to its canonical URL (`https://arxiv.org/abs/2606.07591`) before reporting it, and
de-duplicates afterwards, since two stubs routinely resolve to the same page. A stub that
cannot be resolved is kept but labelled **unresolved redirect, not citable**, and the prompt
tells operators to treat it as a lead rather than a reference. `--no-resolve-urls` skips the
resolution step. Following the redirect is already a GET, so the tool also reads the page's
`<title>` from it and uses that when grounding supplied only a bare domain — the difference
between a bibliography entry that says `arxiv.org` and one that says what the paper is.

**What a "snippet" is, and why the tool no longer calls it one.** Gemini's grounding
metadata pairs each source with sentences from *its own generated answer* — it asserts that
the source **supports** the claim, never that the page **contains** that sentence. Reported
as a blockquote under a source hyperlink, as the tool originally did, that reads as a
quotation, and an agent under instruction to cite only what the tool returned will transcribe
it as one. The field is therefore named `supported_claims`, rendered as a labelled bullet
list, and the prompt block states outright that it is not text from the page. Every claim a
source was cited for is kept, rather than only the first.

**Groundedness is a field, not a sentence.** `--json` carries `grounded` and
`citable_source_count` at the response level and `citable` per result, and the CLI exits `2`
(distinct from `1`, "the search failed") when nothing citable came back. Before, that
judgement existed only as prose inside the markdown renderer, invisible to the `--json`
consumer the prompt tells the agent to parse.

Both `main.py` and `rcb_agent.py` take `--web-search`:

| Value | Behaviour |
|:---|:---|
| `auto` (default) | Gemini when it can actually run, native search otherwise |
| `gemini` | Always Gemini. Use this where `WebSearch` is blocked. Refuses to start if Gemini provably cannot work. |
| `native` | Leave the backend's own search tool in charge |

**"Can actually run" is three checks, not one.** A credential is not a working
search tool. `google-genai` has to be importable by the interpreter that will run the
script — it is not a default dependency, and the Vertex probe uses `google.auth`, a
different distribution that can be installed without it. And the sandbox has to permit
egress: `--operator codex` with `read-only` or `workspace-write` (the default) restricts
outbound network access, so the search subprocess cannot reach Gemini at all. `auto` falls
back to native on any of them and names the blocker at startup; `--web-search gemini`
refuses to start on the first two, and warns on the third because it is inferred from the
requested mode rather than observed.

The advertised command names AutoR's own interpreter rather than a bare `python3`, so the
interpreter checked for the SDK is the one that runs the script.

When Gemini search is active, a `# Web Search Capability` block is injected into every stage
prompt telling the operator that `WebSearch` is disabled, how to call the replacement, and
that every citation must come from a URL the tool actually returned. `auto` degrades to
native rather than advertising a tool that would fail on first use.

The search model defaults to `gemini-2.5-flash` and is overridable with
`AUTOR_WEB_SEARCH_MODEL` or `GEMINI_MODEL`.

---

## Options

```
--workspace PATH        Benchmark workspace. Defaults to the current directory.
--prompt TEXT           Instructions as a literal string (this is what <PROMPT> expands to).
--prompt-file PATH      Instructions from a file. Defaults to <workspace>/INSTRUCTIONS.md.

--operator {claude,codex}       Execution backend. Default: claude.
--model NAME                    Execution model. Default: the backend default.
--review-operator {claude,codex}  Reviewer backend. Default: the execution backend.
--review-model NAME             Reviewer model. Default: the backend default.

--stage-timeout SECONDS  Per stage attempt. Default: 14400. The harness enforces no wall
                         clock of its own, so this is the only thing that can cut a stage
                         short.
--max-attempts N         Attempts per stage before it is auto-skipped. Default: 8, higher
                         than the interactive default because a skipped stage costs score.
--max-auto-skips N       Stages that may be auto-skipped before aborting. Default: 3.
--intake                 Run the intake stage. Off by default: the benchmark instructions
                         are already a complete task specification.
--output-format {markdown,md,latex,tex}
                         Stage 07's deliverable. Default: markdown, which writes
                         report/report.md directly. Use latex to produce the paper package
                         and leave the report to the synthesis step.
--final-stage STAGE      Stop after this stage. Default: 07_writing, because Stage 08
                         produces nothing the judge reads.
--web-search {auto,gemini,native}
--no-synthesis           Skip the operator-backed report synthesis pass.
--export-only            Re-export the latest run without re-running the pipeline. Use this
                         to recover deliverables from an interrupted job.
--fake-operator          Smoke-test the adapter without touching a real backend.
```

### Layout inside the workspace

```
<workspace>/
├── INSTRUCTIONS.md        # written by the harness
├── data/                  # read-only input, never modified
├── related_work/          # read-only references, never modified
├── code/                  # exported
├── outputs/               # exported
├── report/
│   ├── report.md          # the scored deliverable
│   └── images/            # PNG figures
└── .autor/                # the full AutoR run tree, kept for inspection
    └── <run_id>/
```

Everything AutoR needs lives under `.autor/`, so a workspace stays self-contained and a run
can be inspected or resumed after the fact.

---

## Scoring a run locally

`tools/score_rcb_run.py` drives ResearchClawBench's own `score_workspace`, so every
number it prints is that scorer's rather than a reimplementation. What it changes is
three defaults that turn a failed judge call into a score of zero, and it will not
print a total until it has checked that every item was actually judged.

```bash
python3 tools/score_rcb_run.py \
  --workspace /path/to/workspaces/Astronomy_001_20260811_022244 \
  --bench /path/to/ResearchClawBench \
  --out score.json
```

Needs `anthropic`, the bench's `structai`, and `ANTHROPIC_VERTEX_PROJECT_ID`.

### The three ways the stock scorer fakes a low score

All three record as `{"score": 0, "reasoning": "Failed to parse scoring response."}`,
which is indistinguishable in the output from a criterion the report genuinely missed.
Scoring one run here, two of three items were judge failures: the honest total was
**37.0** and the number on screen was **19.5**.

| Stock default | Why it fails | Used here |
|:---|:---|:---|
| `max_tokens=500` | a reasoning judge spends the budget thinking and returns an empty body | 4096 |
| `time_limit=120` | too short for a multimodal call carrying a target image plus five agent images | 600 |
| `multi_thread(max_workers=16)` | concurrent multimodal calls were the actual cause of most failures | serial |

The tool counts failed calls separately from scored ones and **refuses to quote a
total while any call failed**. A benchmark number computed over silent judge failures
is not a measurement of the run.

### The judge is part of the result

The reference judge is `gpt-5.1` (`evaluation/.env.example`), and it is what
`score_rcb_run.py` uses by default:

```bash
# Reads the key from ~/api.txt. Never pass a key as an argument — it lands in the
# shell history and in the process table.
python3 tools/score_rcb_run.py --workspace <ws> --bench <bench>

# No reference key available:
python3 tools/score_rcb_run.py --workspace <ws> --bench <bench> --judge vertex
```

Either judge is a drop-in for `structai.LLMAgent` — `score.py` only ever calls the
agent as `agent(prompt, image_paths=, return_example=, max_try=)` and expects a dict.

The key is read from a file outside the repository. `DEFAULT_KEY_FILE` is
`~/api.txt` deliberately: a default inside the tree is one `git add -A` away from a
leak. Error text is redacted before printing, because an HTTP client's exception can
carry the request that produced it and this output gets pasted into issues. A test
scans every tracked file for a key-shaped literal, so a key pasted into a docstring
or a fixture fails the suite rather than reaching a remote.

On identical artifacts, **Gemini 2.5 Flash scored 37.0 where Claude Opus scored 20.8**.
A sixteen-point spread is a property of the judge, not of the run, so a number quoted
without naming its judge compares to nothing. The tool prints the judge on every run
and writes it into the result file.

### What the scale means

`evaluation/score.py` scores each criterion 0–100 against the *original published
paper*, where **50 means as good as that paper**:

| Band | Meaning |
|:---|:---|
| 0 | absent from the report |
| 1–10 | mentioned, but no quantitative result, or only a vague generic statement |
| 41–50 | comparable to the published paper |
| >50 | better than the published paper |

Two consequences for reading a score. A run that produced a result but never wrote it
down scores zero for it, with no partial credit — coverage is the cheapest points on
the board. And a criterion mentioned without its number is capped in single digits, so
the gap between 10 and 45 is real work, not phrasing.

Image criteria are graded on the picture plus only the **first 10,000 characters** of
the report (`report_text[:10000]`, `evaluation/score.py:138`); text criteria see the
whole document. Since image criteria carry 60.6% of the weight, prose arguing for a
figure past that point is worth nothing.

### Two ladders, and only one of them has headroom

The band table above is a simplification: `RUBRIC` makes the judge **classify each
criterion first**, then apply one of two different scales.

| | Above 50 requires |
|:---|:---|
| **Mode A** — quantitative results, metrics, benchmarks | metrics *better than the paper's* |
| **Mode B** — mechanism, theory, interpretation | more supporting evidence than the paper (51–60); a more complete logical chain and more rigorous argumentation (61–70); insights the paper did not cover (71–80) |

**Mode A has no reachable headroom on a reproduction task.** The agent is not given the
target paper — `run_task.py:setup_workspace` copies `data/` and `related_work/` and
leaves `target_study/` behind, and a hash comparison confirms the target paper is not
hiding among the related work. Beating a number you cannot see, on the data that
produced it, is not a strategy. Mode A is effectively capped at 50, and everything
interesting about it is *below*: absent → 0, mentioned without a number → 1–10, a
number from a methodology with a fundamental error → 11–20, a sound number → 41–50.

Classifying all 154 shipped criteria against the two definitions gives:

| | Mode A | Mode B | row |
|:---|---:|---:|---:|
| image criteria | 40.2% | 20.4% | 60.6% |
| text criteria | 27.0% | 12.4% | 39.4% |
| **column** | **67.2%** | **32.7%** | |

Reproduce it with:

```bash
# For each item in tasks/*/target_study/checklist.json, ask a model which mode the
# judge would pick, using score.py's own Mode A / Mode B definitions verbatim, then
# aggregate by item weight. Weights sum to 1.0 per task, so the shares are directly
# comparable across the 40 tasks.
```

The classification is a model's reading of a rubric, not ground truth — a criterion
near the boundary could go either way, and the judge re-decides on every run. Treat the
split as an order of magnitude: **roughly two-thirds capped, roughly one-third open.**

Three consequences that invert the usual instinct, and which AutoR now passes to the
run in its goal contract:

1. **Covering one more result beats polishing every result you have.** Absent → sound
   number is worth about 45 points on that criterion; sound number → better-written
   sound number is worth nothing across two-thirds of the board.
2. **Report the number you have with its caveat rather than omitting it.** Honest and
   uncertain scores in the 40s if the method is sound; omitted scores 0. This is not
   licence to invent one — the judge is told to be highly skeptical of fabricated
   numbers, and an invented figure lands in the 11–20 band that a real one clears
   anyway, so the honest version dominates on both correctness *and* score.
3. **Prose quality is not a lever; evidence and argument are.** "No inflation for
   well-written but shallow content" is in the rubric verbatim. What moves the
   mechanistic third is the alternative ruled out, the sensitivity check run, and what
   would overturn the claim — which is why
   the `settled_reasoning` channel exists (below).

### Publishing the reasoning the run already did

Mode B's three bands above 50 — *more supporting evidence than the paper*, *a more
complete logical chain and more rigorous argumentation*, *insights the paper did not
cover* — describe the contents of `workspace/reviews/deliberations.json` almost
literally: a settled methodological question, the alternatives rejected and why, a
mandatory falsifier, and the dissent that lost. `idea_pool.json` holds hypotheses five
distinct lenses proposed and the run did not pursue.

Until the `settled_reasoning` channel, none of it reached the report. Stage 07 did not
read `workspace/reviews/` at all, so a run that argued with itself for six voice calls
wrote its report as though the argument had not happened — spending the calls and
collecting none of the weight they could have earned.

The channel is Stage 07 only, and deliberately thin:

- **An unanswered crux contributes nothing.** A panel that could not be reached is not
  an open question the run chose to leave open, and presenting it as one claims
  reasoning that did not happen. (`deliberation.md` covers how the two are told apart.)
- **A duplicate or adopted candidate is not a road not taken.** Listing a restatement of
  the adopted hypothesis as an alternative overstates how wide the search was.
- **Counts and field lengths are capped.** Image criteria see only the first 10,000
  characters and the rubric says "longer is not better" in as many words, so an
  unbounded transcript costs more than it earns. The preface sends the material to
  Discussion, after the numbers.
- **A run that argued nothing sends nothing.** An empty heading invites the stage to
  fill it, and a discussion section about nothing scores below one that is absent.

## Where AutoR lands

**40 tasks, one attempt each, Claude Opus executing and reviewing, judged by `gpt-5.1`.**
The three comparison agents were re-scored from their public runs under that same judge, so
the four rows are commensurable with each other. Measured 2026-08-06, scored 2026-08-11.

| agent | mean | median | max | tasks scoring 0 |
|:---|---:|---:|---:|---:|
| Codex CLI | 19.53 | 17.73 | 48.40 | 2 |
| ResearchHarness (GPT-5.4) | 15.40 | 10.85 | 45.10 | 1 |
| ARIS Codex | 15.02 | 12.65 | 46.90 | 2 |
| **AutoR** | **14.16** | 11.50 | 47.70 | **7** |

AutoR is last, below the bare Codex CLI it can be configured to run on top of. Read the
distribution rather than the mean: its best task (47.70) is competitive in a benchmark
where only three agent-task pairs have ever crossed 50, and its deficit is entirely at the
floor. Stratified by what the report physically is:

| stratum | n | AutoR mean | the other three, same tasks |
|:---|---:|---:|---:|
| 197-byte "incomplete run" stub | 8 | **0.78** | 18.99 |
| Stage-01/02 dump | 10 | 12.88 | — |
| paper-shaped report | 22 | 19.61 | 17.84 |

**The 19.61 is a post-hoc subgroup mean and is not AutoR's number.** It locates the defect —
the pipeline is capable and the deaths are the deficit — and nothing more. Only the 40-task
mean counts.

Three caveats travel with every number above:

- **Single attempt.** The public leaderboard aggregates the *best* score per (task, agent)
  pair. 14.16 is one run per task. The two are not comparable in either direction.
- **The judge is part of the result.** `gpt-5.1` is the benchmark's own. On identical
  artifacts Gemini 2.5 Flash scored 37.0 where Claude Opus scored 20.8, so a number quoted
  without its judge compares to nothing.
- **This is the pre-repair batch.** #180 and #181 closed the routes that produced the eight
  stubs; their effect is unmeasured until a re-run lands.
  [The framework document's §6](framework.md#6-the-system-measured-against-itself) works
  through what the eight zeros were made of and what changed.

## How other agents score

[researchclawbench-landscape.md](researchclawbench-landscape.md) works through the public
leaderboard: where EvoScientist, ARIS Codex and MIRA actually land, which of their reported
numbers reproduce, and what the same-model baseline is that any AutoR result has to be
quoted against. Two findings worth knowing before you run:

- **Model choice dominates harness choice.** Most agents above any given harness on the
  board simply use a stronger model. Quote AutoR against the same-model baseline or the
  number says nothing.
- **A scaffold can be negative.** ARIS Codex, a large skill library over Codex CLI, loses to
  the plain Codex CLI it wraps on 31 of 40 tasks.

---

## Smoke test

```bash
cd /path/to/ResearchClawBench
python3 -c "
import sys; sys.path.insert(0, '.')
from evaluation.run_task import TaskRunner
r = TaskRunner('Astronomy_000', agent_cmd='true', agent_name='autor')
r.setup_workspace()
print(r.workspace.resolve())
"

cd workspaces/Astronomy_000_*
python3 /abs/path/to/AutoR/rcb_agent.py --fake-operator --no-synthesis --max-auto-skips 9
```

This exercises the whole path — unattended pipeline, auto-skip recovery, export — without
spending tokens. Expect exit code 0 and a `report/report.md` assembled by the fallback.
