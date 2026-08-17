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
to) and the instructions default to `<workspace>/INSTRUCTIONS.md`. `logo` is only an icon —
point it at whatever exists under the bench's own `static/logos/`; `rcb_agent.py`'s module
docstring shows the same entry with `autor.svg`.

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
| `report/images/*.png` | whatever is already at the benchmark path, then the run tree's `workspace/report/images`, `figures`, `writing`, `results`, `artifacts`, and the benchmark's own `outputs/` **last** (PNG only, capped — see below) |
| `code/` | `workspace/code` |
| `outputs/` and `outputs/notes/` | `workspace/results` and `workspace/notes`, **images excluded** |

Run-tree figures under `report/images/` keep their filenames, because those are the names
`report.md` references. A same-named figure swept up from elsewhere is the one that gets
qualified — `_figure_candidates` prefixes it with the directory it came from. The benchmark's
own `outputs/` is ranked last on purpose: an image there must never outrank a figure the
report argues with, but a run whose only plots landed there is published from them rather
than shipped with an empty `report/images/`.

> **Warning — the export deletes files.** `collect_figures` finishes by walking
> `<workspace>/outputs/` and `<workspace>/report/` exactly as far as the scorer's sweep does —
> `rglob` over both whole trees, nested and hidden files included — and **unlinks every image
> it finds that is neither a published slot nor a file the winning report links directly**.
> "Image" there is the scorer's set (`JUDGE_IMAGE_SUFFIXES`: `.png`, `.jpg`, `.jpeg`, `.gif`,
> `.bmp`, `.webp`, `.svg`, matched case-insensitively), while only `.png` is eligible to be
> published — so an `.svg` or a `.jpg` under `outputs/` is always deleted and could never have
> filled a slot. The prune runs on every export: after a completed run, after a crashed one,
> and again on each `--export-only`. A figure a stage wrote somewhere sensible but
> unpublished — `outputs/diagnostics/fit.png`, a loose `report/panel.png` — is **lost**, not
> merely unscored. Anything the pipeline produced inside the run tree still exists under
> `<workspace>/.autor/<run_id>/workspace/`, which the prune never touches; a file written only
> to the benchmark workspace has no second copy. Why it is a delete rather than a warning is
> the next section: the scorer sweeps `outputs/` before `report/`, so a stray plot does not
> add a figure, it takes a slot away from one.

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
   `report/images/panels/*.png` takes a slot exactly the way a stray `outputs/` plot does.
   The loose one is worse: `rglob` yields a directory's own entries before it descends, so
   `report/panel.png` is reached *ahead* of everything in `report/images/`, while the nested
   one is reached after — but both are competing for the same five slots. The only images
   that survive the prune are the published slots and any image the winning report links
   directly.
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
   That number is the benchmark's, not AutoR's. It reaches the run as prose, through
   `build_benchmark_goal`, and it exists in `src/` in exactly one place — `report_plan.py`'s
   `JUDGE_VISIBLE_PREFIX_CHARS` — where it is used as an *ordering* gate and nothing else:
   Stage 07 refuses a markdown report longer than the window whose highest-ranked planned
   figure is referenced for the first time past it. Nothing in AutoR truncates on it.

A sixth figure does not add a sixth chance to match. It randomises which five are seen.

#### Where the five are chosen

Not at export, and not at Stage 07. The run commits to its figures at **Stage 03**, in
`workspace/notes/report_plan.json`: one entry per slot, each naming the claim it settles,
what the reader should see, what the figure looks like if that claim holds and if it does
not, and the result file it will be computed from. Stage 06 produces them, Stage 07
publishes them in slot order, and — in markdown mode, which is what the benchmark runs —
`validate_report_plan_coverage` turns three silences into refusals: a planned slot that was
not both published under `report/images/` *and* referenced from `report.md`, unless it
carries a `dropped_because` of at least `MIN_DROP_REASON_CHARS` characters; a plan whose
every slot is dropped, so the report argues for nothing the reader can see; and a report
past the judge's window whose highest-ranked surviving slot is first referenced after it.
`docs/stage-contract.md` carries the gate rows and `src/report_plan.py` the validator.

That machinery is **not** benchmark-specific. It is the discipline
`hypothesis_manifest.json` and `experimental_protocol.json` already apply — commit to the
choice before the results can influence it — applied a third time, to figures, and every
AutoR run gets it. What *is* benchmark-specific is everything above: the ~61% image weight,
the one fixed set of five, the 10,000-character excerpt and the `outputs/`-before-`report/`
sweep. Those reach the run through one place only, `build_benchmark_goal`, which a
non-benchmark run never receives. Outside the benchmark the `report_contract` channel still
describes the deliverable's shape: to a markdown run it gives the ceiling, interpolated from
`MAX_REPORT_FIGURES` so the prompt cannot drift away from the gate that enforces it; to a
LaTeX run it says the venue named in `## Run Configuration` sets the count, since a conference
paper routinely carries eight or ten. Read `_report_contract` for the wording it actually
sends — and do not read that block as the whole of the figure rule, because the floor is not
in it. Its markdown text tells the run there is no floor, while `validate_markdown_report`
refuses a report that references no figures and `resolve_min_report_figures` clamps every
run's floor to at least one.

#### Reference papers

Every task ships curated PDFs in `related_work/`. They are registered as run resources, so
they land in `workspace/literature/` where Stage 01 reads them, and each one is named
individually in the goal contract. Without this the literature survey searches the web and
cannot cite the very work it is reproducing.

#### Where the run stops

`--final-stage` defaults to `07_writing`. Stage 08 produces posters, slides, release notes
and readiness checklists that the judge never opens; the wall-clock is better spent on
analysis. Pass `--final-stage 08_dissemination` for the full workflow.

The report comes from the first of four paths that yields real content — "real" meaning at
least `MIN_REPORT_CHARS` (1,200) characters, below which the candidate is treated as a stub:

1. **`agent`** — something wrote `report/report.md` at the benchmark path directly. The goal
   contract injected into every stage prompt names the exact path. A report AutoR exported on
   an earlier pass does not count as the agent's: `_publish_report` records its digest in
   `.autor_export.json`, which is what stops `--export-only` re-publishing the first fallback
   forever.
2. **`stage`** — Stage 07 ran in markdown mode, so its gate-checked report already exists in
   the run tree and is promoted verbatim. **This is the normal case.**
3. **`synthesized`** — one extra operator call converts the approved artifacts into the
   benchmark's markdown format. This is what a `latex` run uses. The call is retried up to
   `ReportSynthesizer.MAX_ATTEMPTS` times, and a thin answer is retried like a failed one.
4. **`fallback`** — pure-Python assembly from the approved stage summaries, with any
   auto-skipped stages named explicitly. When *no* stage was approved it falls back further,
   to each stage's champion draft under `evolution/` (or, absent a champion, that stage's
   newest attempt), labelled "unapproved draft" — unapproved work is worth less than approved
   work, not less than nothing. AutoR's own control-loop headings are stripped, all five of
   them: `Previously Approved Stage Summaries`, `Decision Ledger`, `Suggestions for
   Refinement`, `Your Options`, `Files Produced`. A judge told to be skeptical reads them as
   an agent's run log, not as research.

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
| Figure budget | at least 3 on this path (`BENCHMARK_MIN_REPORT_FIGURES`), 1 on an ordinary run; at most 5; every one referenced | set by the venue, not by AutoR |
| Report plan | required at Stage 03; every slot must be published *and* referenced, or carry `dropped_because` | required at Stage 03; coverage not checked |
| Post-approval | — | `writing/paper_package/` bundle |

The markdown gates are not "a file exists". `validate_markdown_report` fails Stage 07, which
retries it, if `report.md` is missing, is shorter than `MIN_REPORT_CHARS` (1,200) characters,
references no figures, still holds placeholder text, or carries a figure reference that is
absolute, remote, unrenderable, or points at a file that is not there — or if
`report/images/` holds more than `MAX_REPORT_FIGURES` (15, a ceiling and not a target;
`JUDGE_VISIBLE_FIGURES` is what the grader actually reads and tracks
`evaluation/score.py`, which upstream raised from 5 to 15 on 2026-08-14) rendered figures,
or fewer than the
run's floor. `validate_report_plan_coverage` adds the plan gates listed above. A broken figure
link is the expensive defect here: the judge reads the prose promising a figure and is shown
nothing.

**The floor is 3 on this path and 1 everywhere else.** `rcb_agent.py` passes
`min_report_figures=BENCHMARK_MIN_REPORT_FIGURES` (`src/utils.py`), against the ordinary
`MIN_REPORT_FIGURES = 1`; the value is clamped into `[1, MAX_REPORT_FIGURES]` by
`resolve_min_report_figures`, written into `run_config.json`, and read back by the gate. The
argument for raising it is the benchmark's, not a general one: its instructions ask every
agent for "data overview, main results, and validation/comparison plots" — three distinct
questions — and 27 of the 40 shipped tasks carry two or more image criteria, together holding
most of the weight. A one-figure report clears the ordinary gate while structurally forfeiting
criteria it never addressed, because one image cannot answer two different questions. It is a
count of *distinct* figures and never a target to pad toward: the ceiling is still 5, and a
sixth is not shown to the judge at all.

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

The search model defaults per backend — `gemini-2.5-flash` on the Developer API,
`gemini-3.6-flash` on Vertex, as in the table above — and `resolve_search_model` lets an
explicit `--model` win over `AUTOR_WEB_SEARCH_MODEL` or `GEMINI_MODEL`, which in turn win over
both defaults.

---

## Options

All 37 of them, in `parse_args`'s own order. `rcb_agent.py` does **not** mirror `main.py`: 31
flags are shared, 6 exist only here (`--workspace`, `--prompt`, `--prompt-file`, `--intake`,
`--no-synthesis`, `--export-only`), and the 30 of main.py's it does not declare —
`--full-auto`, `--unattended`, `--approval-mode`, `--resume-run`, `--max-rounds`,
`--stage-graph`, `--evolve`, `--archive`, `--trial`, and the rest — are argparse errors here,
not no-ops. The adapter is unattended by construction, which is why it needs no approval-mode
or unattended switch of its own.

```
--workspace PATH        Benchmark workspace. Default: the current directory, which is what
                        the harness sets it to.
--prompt TEXT           Instructions as a literal string (this is what <PROMPT> expands to).
--prompt-file PATH      Instructions from a file. Default: <workspace>/INSTRUCTIONS.md.

--operator {claude,codex}         Execution backend. Default: claude.
--model NAME                      Execution model. Default: sonnet for claude, "default"
                                  for codex.
--review-operator {claude,codex}  Backend for the reviewer agent that replaces the human
                                  approval gate. Default: the execution backend.
--review-model NAME               Reviewer model. Default: the backend default, as above.
--codex-sandbox MODE              Codex CLI sandbox, used only with --operator codex.
                                  Default: workspace-write — which restricts outbound
                                  network access and so blocks the Gemini search fallback.
--venue KEY                       Venue profile for Stage 07 writing. Default: neurips_2025.
                                  It reaches every stage through `## Run Configuration`; the
                                  manuscript-style gate that reads it is latex-only.
--output-format {markdown,md,latex,tex}
                        Stage 07's deliverable. Default: markdown, which writes
                        report/report.md directly. Use latex to produce the paper package
                        and leave the report to the synthesis step.
--final-stage STAGE     Stop after this stage. Default: 07_writing, because Stage 08
                        produces nothing the judge reads.
--stage-timeout SECONDS Per stage attempt. Default: 14400. The harness enforces no wall
                        clock of its own, so this is the only thing that can cut a stage
                        short.

--rigor {fast,standard,thorough,max}
                        How much optional machinery to run. Default: standard, which turns
                        --effort-tiers ON. thorough adds --deliberation and
                        --ideation-panel; max adds --review-panel; fast turns all four off.
                        The four switches below are argparse BooleanOptionalAction with
                        default=None, so omitting one means "the level decides" rather than
                        "off": `--rigor thorough --no-ideation-panel` does what it says, and
                        `--effort-tiers` is already on unless you pass --no-effort-tiers or
                        --rigor fast.
--review-panel / --no-review-panel
                        Replace the single reviewer agent with a deliberating panel of
                        role-differentiated reviewers (pi, domain, method, repro, skeptic).
                        A blocking objection cannot be approved over. On at --rigor max.
--panel-roles ROLE [ROLE ...]     Seat only these panel roles, in this order.
--panel-models ROLE=MODEL [...]   Model per seat, as role=model or role=backend:model
                                  (pi=opus skeptic=codex:default). Unassigned seats use the
                                  reviewer default.
--effort-tiers / --no-effort-tiers
                        Run each stage as routine or deliberative rather than treating them
                        alike. On at --rigor standard, which is the default.
--routine-model MODEL   Parsed here and read nowhere. The second, cheaper operator a
                        routine stage would run on is built by main.py's configure_effort,
                        which this adapter never calls: under --effort-tiers it sets an
                        EffortPlan and a solo reviewer and nothing else, so every stage
                        runs on --model. Tiering itself still applies — a routine stage
                        gets the tier notice in its prompt and the single reviewer rather
                        than the panel — the model is the part that does not change.
--deliberation / --no-deliberation
                        Let a stage stop and pull in a voice panel when it hits a genuine
                        crux. On at --rigor thorough.
--max-deliberations N   Cruxes a run may escalate. Default: 3.
--deliberation-voices VOICE [...]   Seat only these: theorist, empiricist, critic,
                                    pragmatist.
--deliberation-models VOICE=MODEL [...]   Model per voice, voice=model or voice=backend:model.
--ideation-panel / --no-ideation-panel
                        Widen Stage 02's hypotheses with proposers working from five
                        distinct lenses. It decides nothing. On at --rigor thorough.
--ideation-lenses LENS [...]      Seat only these: mechanism, contrarian, adjacent, null,
                                  regime.
--ideation-models LENS=MODEL [...]  Model per lens.
--ideas-per-proposer N  Candidate hypotheses each proposer may return. Default: 2.
--panel-rounds N        Maximum deliberation rounds for the review panel; later rounds run
                        only on disagreement. Default: 2.
--persona PATH          Markdown description of the researcher the panel stands in for,
                        injected into every panelist.

--max-attempts N        Attempts per stage before it is auto-skipped. Default: 8, higher
                        than the interactive default because a skipped stage costs score.
--max-auto-skips N      Stages that may be auto-skipped before aborting. Default: 3.
--intake                Run the intake stage. Off by default: the benchmark instructions
                        are already a complete task specification.
--cross-review {auto,gemini,off}
                        Independent second opinion on each approval from a different model
                        family. It can veto an approval and can never override a refusal.
                        Default: auto, which enables it when a Gemini backend is configured
                        and stays silent when none is.
--cross-review-model NAME         Default: gemini-3.1-pro-preview
                                  (`DEFAULT_CROSS_REVIEW_MODEL`).
--web-search {auto,gemini,native,off}
                        Default: auto. See the section above. `off` offers no search tool and
                        denies WebSearch and WebFetch to the Claude CLI, for a protocol that
                        says the run must not browse.
--no-synthesis          Skip the operator-backed report synthesis pass and use only the
                        deterministic fallback.
--fake-operator         Smoke-test the adapter. rcb_agent.py threads fake_mode into the
                        operator, the approval reviewer and each panel it seats, and
                        ResearchManager now refuses a cross reviewer behind a fake
                        operator for every caller, so a fake run makes no external call
                        without --cross-review off.
--export-only           Skip the pipeline and only re-export the most recent run in the
                        workspace. Use this to recover deliverables from an interrupted job
                        — but note that the export prunes images, so it is not a read-only
                        operation.
```

**`--cross-review` is live on both paths now.** `main.py` seats it through
`create_cross_reviewer`; this adapter builds it directly. What differs is that the interactive
path re-decides the mode on resume, because the value is recorded in no run config.

Other flags are still inert on one side or the other, and the two
parsers are mirror images, each declaring something the other honours and it does not —
`--routine-model` is the one that works on `main.py` and not here. `docs/cli-reference.md`
diffs the two parsers row by row.

### Layout inside the workspace

```
<workspace>/
├── INSTRUCTIONS.md        # written by the harness
├── _meta.json             # run record; written by the harness, updated by write_run_meta
├── .autor_export.json     # digest of the report AutoR last exported
├── data/                  # read-only input, never modified
├── related_work/          # read-only references, never modified
├── code/                  # exported
├── outputs/               # exported; images are pruned from here
│   └── notes/             # workspace/notes from the run tree
├── report/
│   ├── report.md          # the scored deliverable
│   └── images/            # PNG figures — the only place an image survives the export
└── .autor/                # the full AutoR run tree, kept for inspection
    └── <run_id>/
```

Everything AutoR needs lives under `.autor/` and two dotfile-sized records at the root, so a
workspace stays self-contained and a run can be inspected or resumed after the fact.
`_meta.json` is the one the harness and the leaderboard importer read: a run launched by hand
has no one else to write it, and without `status: "completed"` plus `task_id` and
`duration_seconds` the workspace cannot be scored. On `--export-only` the duration is not
re-measured: `_recorded_duration` keeps a value already on record, or, for a run killed
before it wrote one, estimates the span of the run tree's file timestamps. Reporting the
export's own few seconds would put a multi-hour run on the leaderboard at near-zero cost.

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

**What it needs depends on the judge, and the default judge needs none of Vertex.**

| | `--judge reference` (the default) | `--judge vertex` |
|:---|:---|:---|
| Judge | `gpt-5.1` (`REFERENCE_JUDGE_MODEL`), what the benchmark scores with | `claude-opus-4-5@20251101` (`FALLBACK_JUDGE_MODEL`) |
| Python package | `openai` | `anthropic` |
| Credential | a key in `~/api.txt` (`DEFAULT_KEY_FILE`, moved with `--key-file`) | `ANTHROPIC_VERTEX_PROJECT_ID`, or `--project-id`; exits 2 without one |
| Endpoint | the OpenAI-compatible base URL in `REFERENCE_JUDGE_ENDPOINT`, overridable with `--endpoint` | Vertex, region `global` |

Either judge also needs the ResearchClawBench checkout at `--bench`, since the tool imports
`evaluation.score` from it and drives the bench's own `score_workspace`; that import is what
pulls in the bench's `structai`, and the judge object replaces `structai.LLMAgent` afterwards.
`--model` overrides the model id for whichever judge is selected. Nothing on the default path
reads a Vertex project, and nothing on either path accepts a key as an argument.

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

**Score with `gpt-5.1`, and quote the judge next to every total you publish.** That is
the whole rule, and it is not a style preference:

- **`gpt-5.1` is the reference judge** — it is what ResearchClawBench itself scores with
  (`evaluation/.env.example`), it is `REFERENCE_JUDGE_MODEL`, and `--judge reference` is
  the tool's default. Anything else is a local measurement that no published figure can
  be compared against.
- **Judge choice is worth roughly sixteen points.** On one identical artifact set, Gemini
  2.5 Flash scored **37.0** where Claude Opus scored **20.8**. That is not a smaller
  number, it is an **incomparable** one: the spread is a property of the grader, not of
  the run, so a total quoted without its judge compares to nothing — including to the
  same run scored yesterday.
- **The tool makes this hard to get wrong.** It prints `judge: <model>` before the
  per-item table, repeats it inside the `TOTAL (judge …)` line, and writes `judge_model`
  into the result file. Carry that string wherever the number goes.

```bash
# The default path: gpt-5.1, key read from ~/api.txt. Never pass a key as an argument —
# it lands in the shell history and in the process table.
python3 tools/score_rcb_run.py --workspace <ws> --bench <bench>

# Fallback when no reference key is available. Label the result as Claude-judged; do not
# put it beside a gpt-5.1 number.
python3 tools/score_rcb_run.py --workspace <ws> --bench <bench> --judge vertex
```

Either judge is a drop-in for `structai.LLMAgent` — `score.py` only ever calls the
agent as `agent(prompt, image_paths=, return_example=, max_try=)` and expects a dict —
so switching judges changes the grader and nothing else about the measurement.

The key is read from a file outside the repository. `DEFAULT_KEY_FILE` is
`~/api.txt` deliberately: a default inside the tree is one `git add -A` away from a
leak. `read_api_key` accepts a bare token, `KEY=token`, or a quoted value, so nobody has
to print the file to find out its shape, and it exits with instructions rather than a
traceback when the file is missing. Error text is redacted before printing, because an
HTTP client's exception can carry the request that produced it and this output gets pasted
into issues. A test scans every tracked file for a key-shaped literal, so a key pasted
into a docstring or a fixture fails the suite rather than reaching a remote.

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

**That 32.7% is a ceiling, and it has been read as an estimate.** Two corrections, both
of which cut it:

* **It counts every boundary criterion as Mode B.** A criterion that wants a number
  *and* an inference drawn from it — Physics_001, Neuroscience_000/001, Chemistry_003 —
  can be scored either way. The firm Mode B floor is **10.1%**; 30.4% is firm plus
  every boundary case resolved generously. The honest statement is a range, not a
  point.
* **Most of it is behind image criteria, which never see the argument.** 20.4pp of the
  32.7% is in the image row of the table above, and an image criterion is shown only
  `report_text[:10000]` (`evaluation/score.py`), while the Discussion is at the end of
  the report by construction — the goal contract puts it there. So Mode B weight that
  *prose in the Discussion can actually reach* is **8.2%–14.8%**, not a third.

This matters because `src/settled_reasoning.py` quotes the 32.7% in its docstring as
the justification for the channel existing. The channel is still worth having at
8–15%; it is not worth having on the strength of a number that is two to four times
its addressable surface. Nineteen of the forty tasks carry zero Mode-B *text* weight,
and nine of those have no text criteria at all — on those nine the Discussion cannot be
read by any criterion, whatever it says.

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

Both files are produced by optional machinery, so a run that seats neither panel has nothing
to publish here: `deliberations.json` needs `--deliberation` and `idea_pool.json` needs
`--ideation-panel`, and at the default `--rigor standard` both are off. `--rigor thorough`
turns both on.

The channel is Stage 07 only, and deliberately thin:

- **An unanswered crux contributes nothing.** A panel that could not be reached is not
  an open question the run chose to leave open, and presenting it as one claims
  reasoning that did not happen. (`deliberation.md` covers how the two are told apart.)
- **A duplicate or adopted candidate is not a road not taken.** Listing a restatement of
  the adopted hypothesis as an alternative overstates how wide the search was.
- **Counts and field lengths are capped** — `MAX_CRUXES`, `MAX_REJECTED` and
  `MAX_FIELD_CHARS` in `src/settled_reasoning.py`. Image criteria see only the first
  10,000 characters and the rubric says "longer is not better" in as many words, so an
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

| stratum, by what the report *is* | n | AutoR mean | the other three, same tasks |
|:---|---:|---:|---:|
| 197-byte "incomplete run" stub | 8 | **0.78** | 18.99 |
| Stage-01/02 dump | 10 | 12.88 | 12.17 |
| paper-shaped report | 22 | 19.61 | 17.84 |

**The 19.61 is a post-hoc subgroup mean and is not AutoR's number.** Only the 40-task mean
counts. It is also a subgroup of *legible* runs rather than correct ones: cutting by where
the walk actually stopped, AutoR's two best scores — Astronomy_003 at 47.70 and Physics_002
at 45.45 — came from runs that halted at `02_hypothesis_generation`, having never designed
a study or run an experiment. Five runs of forty reached Stage 05 or later. Those reports
were assembled by this adapter's synthesizer, not by the pipeline.

Four caveats travel with every number above:

- **Single attempt.** The public leaderboard aggregates the *best* score per (task, agent)
  pair (`RCB/README.md:280`). 14.16 is one run per task. The two are not comparable in
  either direction.
- **Cross-model.** All three comparison agents run GPT-5.4; AutoR ran Claude Opus. The table
  is therefore not a clean harness comparison, and the same-model baseline the
  [landscape study](researchclawbench-landscape.md) calls mandatory has not been run.
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
python3 /abs/path/to/AutoR/rcb_agent.py --fake-operator --no-synthesis \
  --cross-review off --max-auto-skips 9
```

This exercises the unattended pipeline, the auto-skip recovery and the export without calling
an execution backend. Expect exit code 0, a `report/report.md`, and a figure published under
`report/images/`. Do not expect a particular report path: the fake operator writes a report
into the run tree, so a fake run normally exports `"report_source": "stage"` even while
auto-skipping stages. Read the source off the final JSON line rather than assuming it.

**`--cross-review off` used to be mandatory for a free run, and no longer is.**
`resolve_cross_reviewer`'s default `auto` seats a live `GeminiCrossReviewer` whenever
`resolve_backend` finds a usable Gemini backend — and the Vertex project it accepts includes
`ANTHROPIC_VERTEX_PROJECT_ID`, so the boxes the web-search section above is written for were
exactly the ones where a "fake" run made real calls, one per approval, each capable of vetoing
it. `ResearchManager` now refuses a cross reviewer behind a fake operator whatever the caller
passed, so the flag is belt to that braces rather than the only thing holding it.

`--max-auto-skips 9` lifts the budget above the default of 3, so a fake run whose stages
exhaust their retries reaches the export instead of aborting part-way; how many it actually
skips is not fixed, and the export event on stdout carries `auto_skipped_stages`.

The same run works without a bench checkout — any directory with an `INSTRUCTIONS.md` in it
will do — which is the cheapest way to see what the adapter writes where.


---

## About a tenth of the weight asks about a paper the workspace does not contain

A task-by-task study of the 2026-08-16 arm found 16 criteria, **4.00 of 40.0 total weight
(10.0%)**, where AutoR's new code, AutoR's pre-fix code and a bare agent all score at or
below 10. The study called that the remaining headroom. It is not headroom, and the
correction is worth more than the original claim.

Every one of those criteria names something specific — an analysis (`SHAP`), a dataset
(`TextVQA`), a model (`Qwen2.5-3B`), a tool (`HADDOCK3`), an event (CAPRI round 57,
target 268), a pipeline (`FlyWire`, `FAFB`). Those names come from the **target paper**,
and the benchmark does not ship it. `related_work/` holds *other* papers. Searching only
what the agent is given — `related_work/` and `data/`, nothing the run wrote —
**2 of 30 distinctive identifiers from these criteria appear anywhere**:

| task | supplied text | absent from it |
|:---|---:|:---|
| Neuroscience_000 #1–#3 | 3,463,517 chars | `SHAP`, `Lab1`, `Lab2`, `CSDS` |
| Chemistry_002 #3–#4 | 1,602,208 chars | `CAPRI`, `HADDOCK3`, `VoroIF` |
| Life_001 #0, #3 | 2,462,557 chars | `NeoAgDT`, `NetMHCpan` |
| Information_001 #2 | **0 chars** | `Qwen2.5-3B`, `TextVQA` |
| Neuroscience_002 #0, #4 | **0 chars** | `FlyWire`, `FAFB`, `FFN`, `EmbedNet` |
| Information_003 #4 | **0 chars** | `DIDS`, `MFL` |

Four of those tasks supply no readable text at all: their `related_work/` and `data/` are
tensors and images. Three and a half million characters of Neuroscience_000's supplied
papers contain the string "SHAP" zero times.

So this is not a gap a skill or a gate can close. It is the benchmark's floor for an agent
that is not given the document it is graded against, and any claim about how much of
ResearchClawBench is reachable should be quoted against **90%**, not 100%.

The one route that would reach it is fetching the target paper from the web and reading
its methods section. That is a research-integrity question rather than an engineering one
— on a reproduction benchmark, reading the target's results and restating them is close to
copying the answer — and it is recorded here rather than taken.

`python tools/unreachable_criteria.py --arms <score dirs> --runs <workspace root>`
re-derives all of it. Two earlier attempts at this measurement were wrong in the same
direction: one searched the criterion's words in a corpus that included `_score.json`, the
judge's own output, which contains the criteria verbatim, and got 30 of 30 "present". A
search for a criterion's words that includes the criterion answers yes by construction.

## Measuring a change against the benchmark score

AutoR's own rubric cannot answer "did this PR make the research better" — it is AutoR
grading its own drafts, and a change that makes it like its own work more is not the
claim. `src/trials.py` already does the paired statistics honestly; what it lacked was
an outcome measure that came from outside. `src/rcb_trial.py` supplies one, as a
*producer* of the two dicts `trials.Pair` reads, so every refusal in that module keeps
working untouched:

* `stage_fitness` — exactly one key, `"<task_id>|<env_digest>"`, holding the 0–100
  total. One key because `Pair._mean_over` is unweighted while the benchmark total is
  weighted, and a mean over one element is that element. The environment digest is in
  the key so that a pair whose arms differed in judge, `model`, `review_model`,
  checklist bytes, resolved web-search level, *requested web-search mode*,
  `INSTRUCTIONS.md`, benchmark revision or
  *the number of judge draws its total averages* is excluded by the composition refusal
  that already exists, with no new gate to get wrong. `rcb_trial.py report` additionally
  names *which* field differed; that is diagnostics, and a test holds it in step with
  the digest field by field — and a second test holds that the fields are actually read
  off the run, because eight blank strings are a constant digest and a gate that
  excludes nothing.

  The requested mode sits beside the resolved level because the level stopped
  separating what it was added to separate. `--web-search off` announces itself at
  `level: info`, which is the right level for a deliberate choice and is also what an
  `auto` that found a working backend emits; since `rcb_agent.py` began accepting `off`,
  an arm told not to browse and an arm that browsed freely could carry the same level.
  The mode is read off `run_config.json`, which stores the request and never the
  resolved backend.

  The draw count is in there because `final_pass` gives each replicate two tries and
  then moves on writing nothing: an arm silently scored once against an arm scored three
  times is the ordinary failure, and it is the direction that inflates, since the single
  draw carries the judge's whole sampling range into the delta while the other arm has
  averaged its own away. The pair block prints both arms' counts against the planned
  number, and says **unmeasured** rather than ±0.00 when one arm has a single draw —
  fewer draws must not produce a smaller stated uncertainty.
* `criterion_fitness` — one key per checklist item, holding `weight * score`. Every
  shipped checklist's weights sum to 1.0, so **within one run** the decomposition sums
  to the scalar and `concentration` becomes literally the share of the movement in one
  checklist item. The identity is per-run; adding raw per-pair contributions across
  *n* pairs gives *n* times the total, and the trial table reports means on both sides
  rather than sums.

No record is ever written to disk. `RunRecord.usable` requires AutoR's rubric version,
which a benchmark row cannot honestly carry; the containment is that no `Archive` is
constructible from either file, and a test says so.

### The plan file

One `--plan PATH` in place of ten flags (`configs/rcb_trial_175.json` is the shipped
one). Fields: `capability`, `bench`, `tasks`, `control`/`treatment` (each
`{label, worktree, sha}`), `judge_kind`, `judge_model`, `agent_model`, `review_model`,
`state_dir`, `arm_order_mode`, `deadline`, `stall_seconds`, `replicates`, `operator`,
`fake_quality`. It is sha256-frozen before the first launch and stamped into every
state file: an apparatus that can be re-planned while it runs is an apparatus that can
be stopped when the sign looks good, and the report says `INTERIM — k of N planned
pairs` whenever it was.

`control_arm` and `treatment_arm` are always explicit, so `_infer_arms` never runs.
Its lexicographic fallback happens to give the right direction for `621566b` against
`47f3fbf` only because ASCII digits sort below letters; two SHAs both starting with a
letter would invert the sign silently.

### The ten admission clauses

A run becomes a measurement only after all ten pass, and a failure refuses the **pair**
— refusing one arm turns it into "no treatment arm" and hides the cause. Each is here
because of something observed on a real workspace:

| Clause | The observation |
| --- | --- |
| `status_completed` | The scorer never reads `_meta.status`; a workspace mid-run scored its 12 KB working draft. |
| `pipeline_completed` | A second witness: one workspace has `status: completed` and `pipeline_completed: false`. |
| `report_from_agent` | A quota death still exports a fallback report worth about 7.5 points and records `completed`. |
| `single_run_root` | Nothing stops a second invocation in one workspace; the exporter picks the lexicographically last root, which is the failed retry. |
| `no_images_under_outputs` | Thirteen PNGs under `outputs/` took all five judge image slots: one image item 48 → 0, total 46.0 → 9.6. |
| `single_report_md` | With `report.md` missing the scorer reads whatever an unsorted glob yields first, and records nothing about which file it read. |
| `backend_reached` | `run.backend_unavailable` is the only machine-readable trace of a quota death; `last_error` stays null. |
| `no_quota_in_logs` | `classify_backend` runs only when neither attempt wrote a stage file, so a mid-stage 429 reports itself complete. |
| `revision_matches_arm` | `RunRecord` has no revision field and `run_config.json` records no SHA; the arm label is the only carrier. |
| `every_item_judged` | A judge failure is scored 0: one run's honest total was 37.0 and the number on screen was 19.5. |

The report prints a refused-run count **per clause, including zeros**, above the total.
A clause that has stopped firing because an internal artifact was renamed looks exactly
like a clause never violated, and the gate does not fail loudly when that happens — it
stops refusing.

### What no clause can bound: which five images

`no_images_under_outputs` bounds where the judge's images come from. It cannot bound how
many there were: the scorer shows the first five of one `rglob` list against *every*
image criterion, and image criteria are 60.6% of the benchmark's weight. Four figures all
shown and twelve figures of which an arbitrary five were shown are different evidence,
and the score file was already recording which images went in — the trial simply threw
it away, so two arms shown different figures produced an identical `env_digest` and the
whole delta was attributed to the code change. It is not a gate, because how many figures
a run produced is an *effect* of the change under test rather than a confound to hold
fixed. Both counts are printed per arm, and a pair whose arms were shown different
evidence is told so where its image stratum is read.

### The refusals the gate never sees

Most deaths never reach a clause. `final_pass` scores only runs classified `ok`, and an
arm with no score file produces no evidence at all, so a run killed by quota, by the
stall watchdog, by a backend outage, by a fallback report, by an incomplete pipeline or
by the scorer's own refusal was rendered as "no `<arm>` arm" — the same sentence as an
arm that was never launched — while the paragraph underneath told the reader to judge
the difference on the per-arm death counts. Those deaths now enter the same ledger as
`driver:quota`, `driver:stalled`, `driver:fallback`, `driver:unscored` and so on, they
are named in the exclusion line for the pair, and the per-arm counts are printed even
when both are zero, because that is the reading where the reader most needs them.

This also fixes what a zero in the clause table means. Four of the ten clauses
(`status_completed`, `report_from_agent`, `backend_reached`, `no_quota_in_logs`) are
implied by `classification == "ok"`, which is the only classification `final_pass` will
score, so they cannot fire on the driver's path at all: a quota death arrives as a
`driver:` row and never as `no_quota_in_logs`. The caveat under the table says so.

Two things the ledger deliberately does not do: it does not count a run in flight as a
death, and it counts each `(task, arm)` once however many ways it died — a doubled
per-arm count is a lie in the direction that looks like a finding.

### What it cannot show

Both changes in PR #175 are in one commit, so the trial cannot attribute an effect to
one of them; the task choice makes an argument (Astronomy_000 is (a)-only at 0.00 Mode-B
weight, Energy_002 is (b)-dominant with its image criteria floored, Energy_001 carries
both) and an argument is not an attribution. At three pairs the exact p cannot go below
0.25 at any effect size. Each (task, arm) runs once, so replicate scoring measures the
judge's sampling range and there are **zero** observations of AutoR's own run-to-run
variance. And a refusal removes a pair, not an arm — refusals are not random with
respect to arm, so a lopsided refusal ledger is itself the result.

### How wide the judge's sampling range actually is

The paragraph above says replicate scoring measures the judge's sampling range without
saying how wide it is. Measured, on `Astronomy_000`, with `gpt-5.1` and **nothing changed
between draws** — same workspace, same `report.md`, same five published figures:

| draw | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| `[0]` text, w=0.2 | 45 | 55 | 55 | 55 | 40 | 45 | 45 | 40 |
| `[1]` image, w=0.3 | 46 | 46 | 52 | 48 | 48 | 55 | 52 | 47 |
| `[2]` text, w=0.5 | 40 | 50 | 45 | 32 | 55 | 40 | 45 | 55 |
| **total** | 42.8 | 49.8 | 49.1 | 41.4 | 49.9 | 45.5 | 47.1 | 49.6 |

Mean 46.9, median 48.1, sd 3.4, **spread 8.5**. The variance is worst where it is most
expensive: item `[2]` carries half the weight and spanned 32 to 55, which is 11.5 points of
the total on its own.

Three consequences, and the third is the one that bites:

1. A single-draw score on a single task carries roughly **±4 points** of sampling noise.
2. Any one-task A/B below about eight points is uninterpretable. An earlier before-and-after
   on this task read 46.0 against 42.8 and looked like a small regression; 46.0 sits at the
   3/8 percentile of the *unchanged* artifact's own distribution, so it was noise. The 9.6 →
   46.0 jump from the export repairs is 36 points and survives this comfortably — the point is
   not that nothing is measurable, it is where the floor sits.
3. This is judge variance with the artifacts held fixed. AutoR's own run-to-run variance is
   **additional and still unmeasured**, so the floor for a full A/B is higher than 8.5, not
   equal to it.

Eight draws of one task is a small sample and the number is a floor rather than an estimate.
It is enough to say that a one-draw per-arm trial cannot resolve a small effect, which is what
the `stage_fitness` key's draw count exists to refuse.

### Dry run

```bash
python3 -m unittest tests.test_rcb_trial_driver
```

`operator: "fake"` and `judge_kind: "fake"` in the plan fabricate workspaces and scores
while keeping the real lock, real `start_new_session` children, real atomic state, the
real stall watchdog, the real gate and the real report. It runs a whole trial in about
twenty seconds instead of four days.
