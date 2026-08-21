# Stage Contract

A stage is only accepted when it satisfies two independent checks:

1. **The markdown contract** — the stage summary has the required shape.
   Enforced by `validate_stage_markdown` in [`src/utils.py`](../src/utils.py).
2. **The artifact gate** — real files exist in the right places, and for the
   stages that produce them, they were written *during this stage's execution*.
   Enforced by `validate_stage_artifacts` in [`src/utils.py`](../src/utils.py).

A stage that passes both is shown to you for approval. A stage that fails
either one is repaired, normalized locally, or re-run — up to `--max-attempts`
attempts, which defaults to `MAX_STAGE_ATTEMPTS` (5). After that AutoR
escalates to you.

In an unattended run there is nobody to escalate to, so the stage is
auto-skipped instead and the walk continues. What lands on disk depends on the
stage's last draft, and the two outcomes are alternatives, not a pair:

- **The ordinary auto-skip.** `_skip_stage` generates a stub summary and that
  stub *is* the promoted `stages/<slug>.md`. No `.skip_stub.md` file is written.
- **A rescued draft.** `_validated_draft_for_skip` re-runs both gates on the
  stage's last `stages/<slug>.tmp.md`. If that draft passes both, it is promoted
  as `stages/<slug>.md` instead — real work is not thrown away because the retry
  budget ran out — and the stub it displaced is kept beside it as
  `stages/<slug>.skip_stub.md` for the audit trail. That sidecar is the *only*
  thing that ever writes a `.skip_stub.md`.

Either way the manifest records an auto-skip rather than an approval: nobody
reviewed the output. Auto-skipping is bounded by `--max-auto-skips` (default 3);
the run aborts once the budget is spent.

Neither check is a substitute for reading the output. They are a floor, not a
quality bar: they stop markdown-only theater, they do not certify science.

---

## 1. The markdown contract

Every stage writes `runs/<run_id>/stages/<slug>.tmp.md` as a draft, and
`runs/<run_id>/stages/<slug>.md` once approved.

### Required shape

```md
# Stage 03: Study Design

## Objective
## What I Did
## Key Results
## Files Produced
## Decision Ledger
## Suggestions for Refinement
## Your Options
```

All seven headings are required, in the list defined by
`REQUIRED_STAGE_HEADINGS`. A missing heading is reported as
`Missing required section: <name>`.

An eighth heading, in which each stage restated the approved summaries of the
stages before it, is retired. It required every stage to relay the context it
had just been given, which is where the growth from 235 to 1,211 words per
stage came from.

### Title

Two checks, in order, and they report different things.

The document must *begin* with the literal `# Stage `. This one is a
`str.startswith` on the raw text rather than on the first non-empty line, so a
summary that opens with a blank line or a leading space fails with
`Stage markdown must begin with '# Stage '.` even when its first non-empty line
is a perfect title.

Only if that passes is the title itself compared: the first non-empty line must
equal `# Stage NN: <Display Name>` for that stage — for example
`# Stage 03: Study Design`. A document that starts `# Stage ` and then says
something else fails with
`Stage markdown title must be exactly '# Stage NN: <Display Name>'.`

### No placeholders

No section may contain unfinished-work markers. The rejected patterns
(`PLACEHOLDER_PATTERNS`) are, case-insensitively:

`[in progress…]` · `[pending…]` · `[todo…]` · `[to be determined…]` ·
`[placeholder…]` · `[to be populated…]`

This is checked per section and again on each refinement suggestion.

### Files Produced

Must list at least one concrete file path. When the run paths are available,
**every listed path is checked for existence** — a summary that claims files it
did not write fails with
`Section 'Files Produced' references missing file(s): ...`.

This is the check that most often catches a stage describing work it did not
actually do.

### Decision Ledger

Must mention all four of:

- `Open Questions`
- `Locked Decisions`
- `Assumptions`
- `Rejected Alternatives`

The ledger is the run's record of *why* the research went the way it did. It
is what makes an approved run auditable months later.

### Suggestions for Refinement

Exactly three numbered suggestions, numbered `1.`, `2.`, `3.`, in order, with
no extras. These become options 1–3 on the review menu.

### Your Options

Exactly six numbered options, in order, with these exact texts
(`FIXED_STAGE_OPTIONS`):

```
1. Use suggestion 1
2. Use suggestion 2
3. Use suggestion 3
4. Refine with your own feedback
5. Approve and continue
6. Abort
```

| Choice | What happens |
| --- | --- |
| `1` / `2` / `3` | Continue the same stage conversation, applying that refinement suggestion. |
| `4` | Continue the same stage conversation with feedback you type. |
| `5` | Approve. The summary is promoted to `stages/<slug>.md`, appended to `memory.md`, and the run advances. |
| `6` | Abort the run. Everything on disk stays valid and resumable. |

### Stage 02 additional contract

`02_hypothesis_generation` must carry typed subsections inside `Key Results`
(`TYPED_HYPOTHESIS_HEADINGS`):

| Subsection | Required identifier format |
| --- | --- |
| `Theoretical Propositions` | at least one `**T1**:` |
| `Empirical Hypotheses` | at least one `**H1**:` |
| `Paper Claims (Provisional)` | at least one `**C1**:` |

These identifiers are parsed into
[`workspace/notes/hypothesis_manifest.json`](run-artifacts.md#workspacenoteshypothesis_manifestjson)
so later stages can refer to a specific hypothesis rather than to prose.

---

## 2. The artifact gate

Artifact requirements are **cumulative**: `validate_stage_artifacts` is a chain
of `if stage.number >= N` blocks, so a Stage 07 run must still satisfy
everything Stage 03, 05, and 06 required. Three checks are the exception, and
the table marks them: the Stage 01 evidence ledger runs at Stage 01 *only*
(`stage.number == 1`), and the two review-answering checks are called on every
stage and select their own.

| From stage | Requirement | Checked by |
| --- | --- | --- |
| **01 only** | `workspace/literature/sources.json` and `workspace/literature/claims.json` exist and cross-reference correctly (see [the evidence ledger](#the-evidence-ledger)). | `validate_literature_evidence` |
| **03+** | At least one machine-readable file under `workspace/data/` with a suffix in `.json .jsonl .csv .tsv .parquet .yaml .yml`. | `MACHINE_DATA_SUFFIXES` |
| **03+** | `workspace/notes/report_plan.json` exists and is a commitment (see [the report plan](#the-report-plan)). | `validate_report_plan` |
| **05+** | At least one result file under `workspace/results/` with a suffix in `.json .jsonl .csv .tsv .parquet .npz .npy`. | `RESULT_SUFFIXES` |
| **05+** | `workspace/results/experiment_manifest.json` exists and is structurally valid. | `validate_experiment_manifest` |
| **06+** | Every live slot's and headline number's `source_artifact` resolves to a file that exists and is not empty. | `validate_report_plan_sources` |
| **06+** | At least one figure under `workspace/figures/` with a suffix in `.png .pdf .svg .jpg .jpeg`. | `FIGURE_SUFFIXES` |
| **08+** | At least one file under `workspace/reviews/`. | — |
| **06 and 07 only** | Every finding of the adversarial validity review of the previous stage is answered in `workspace/reviews/`. Stage 06 answers Stage 05, Stage 07 answers Stage 06; every other stage owes nothing, and so does a stage whose review found nothing. **The findings counted are the ones AutoR stamped** to `runs/<id>/validity_review_stamp.json`, so deleting or softening the workspace copy changes nothing about what is owed — and the disagreement is itself refused, on a stage that answered everything and on a stage whose review found nothing alike. | `validate_validity_response` |
| **06, then 07+** | At Stage 06, `workspace/notes/round_decision.json` names one of the four round decisions. From Stage 07 on, a closed round must exist and must not stand `abandon`ed. | `validate_round_decision` |

One Stage 07 requirement is shared by both output formats, because it runs
before the branch:

| From stage | Requirement | Checked by |
| --- | --- | --- |
| **07+** | Every claim in `workspace/artifacts/claim_provenance.json` is `confirmatory` on a `supported` hypothesis or labelled `exploratory`, and cites a file that exists. | `validate_claim_provenance` |
| **07+** | `workspace/artifacts/deliverables_coverage.json` accounts for what the task statement demanded (see [the deliverables contract](#the-deliverables-contract)). Format-independent: whether the run answered the question it was given is not a question about how the answer was typeset. | `validate_deliverables_coverage` |

Everything else at Stage 07 depends on the run's `output_format`, and **the two
branches share very little**. In particular `validate_markdown_report` and
`validate_report_plan_coverage` do **not** run on the latex branch.

**`markdown` (the default):**

| From stage | Requirement | Checked by |
| --- | --- | --- |
| **07+** | `workspace/report/report.md` exists and holds at least `MIN_REPORT_CHARS` (1,200) characters after stripping. | `validate_markdown_report` |
| **07+** | It contains no placeholder text. | `validate_markdown_report` |
| **07+** | It references at least one image, via `![...](...)` or `<img src="...">`. | `validate_markdown_report` |
| **07+** | Every image reference is report-relative — not absolute, not a URL, and not a path that climbs out of `report/`. | `resolve_report_image` |
| **07+** | Every image reference resolves to a file that exists under `workspace/report/`. | `validate_markdown_report` |
| **07+** | Every referenced image is renderable: `.png .jpg .jpeg .gif .webp` (`RENDERABLE_IMAGE_SUFFIXES`). | `validate_markdown_report` |
| **07+** | The count of **published, renderable images under `workspace/report/images/`** is at least this run's figure floor and at most `MAX_REPORT_FIGURES` (5). | `validate_markdown_report` |
| **07+** | `workspace/artifacts/citation_verification.json`, structurally valid. | `validate_citation_verification` |
| **07+** | `workspace/artifacts/self_review.json`. | — |
| **07+** | `workspace/artifacts/report_review.json`, structurally valid. | `validate_report_review` |
| **07+** | Every slot in `report_plan.json` was published under `report/images/` and referenced from `report.md`, or carries a `dropped_because` of at least `MIN_DROP_REASON_CHARS` (20) characters — and not every slot may be dropped. | `validate_report_plan_coverage` |
| **07+** | The highest-ranked live slot is referenced within the first `JUDGE_VISIBLE_PREFIX_CHARS` (10,000) characters of `report.md`, when the report is longer than that. | `validate_report_plan_coverage` |

#### The figure floor and the figure ceiling are two different numbers

The count check is not "at least one figure". It compares the published images
against `resolve_min_report_figures(load_run_config(paths).get("min_report_figures"))`,
which is the run's own recorded floor clamped into `[1, MAX_REPORT_FIGURES]`:

| Run | Floor | Source |
| --- | --- | --- |
| An ordinary run | 1 | `MIN_REPORT_FIGURES`, the `default_run_config` value |
| A ResearchClawBench run | 3 | `BENCHMARK_MIN_REPORT_FIGURES`, passed by `rcb_agent.py` |

There is no `main.py` flag for it: a normal run gets the floor of 1, and the
raised floor arrives only through the benchmark entry point. The floor is a
count of *distinct* figures and never a target to pad toward — the ceiling is
five either way.

The upper bound is not a style preference. A benchmark judge is shown only the first five
images it finds, in filesystem order, so a sixth figure does not add a sixth chance to be
credited — it makes it arbitrary which of yours are seen. It is also why the floor is
clamped at five: a floor above the ceiling would demand figures nobody is shown.

**Reference-existence is a separate check from the count.** A report can
reference one figure and still fail the count (three published images required,
two on disk), and it can publish five images and still fail the reference checks
(one of them linked as `../figures/x.png`). Both run on every markdown Stage 07.

**`latex`:**

| From stage | Requirement | Checked by |
| --- | --- | --- |
| **07+** | `workspace/writing/main.tex` exists **and** matches the selected venue (see [venue matching](#venue-matching)). | `_looks_like_supported_manuscript` |
| **07+** | A `.bib` file under `workspace/writing/`, or an inline bibliography. | `_has_inline_bibliography` |
| **07+** | At least one `.tex` file under `workspace/writing/sections/`. | — |
| **07+** | A compiled PDF under `workspace/writing/` or `workspace/artifacts/`. | — |
| **07+** | `workspace/artifacts/build_log.txt`. | — |
| **07+** | `workspace/artifacts/citation_verification.json`, structurally valid. | `validate_citation_verification` |
| **07+** | `workspace/artifacts/self_review.json`. | — |
| **07+** | `workspace/artifacts/layout_review.json`, structurally valid. | `validate_layout_review` |

Nothing on the latex branch reads `report.md`, `report/images/` or
`deliverables_coverage.json`, and the report plan is checked for *shape* (Stage
03) and for *sources* (Stage 06) but never for coverage. The layout review is
what covers that ground for a manuscript, because a LaTeX document places its
own figures and there is no single directory a coverage check could read.

The schemas of the validated JSON files are in
[Run Artifacts](run-artifacts.md).

### The validity chain runs from the same function

`validate_stage_artifacts` also hosts the scientific-validity chain — its own
comment names the split, *"the scientific-validity chain, distinct from the
artifact gates around it"*. These are not artifact-existence checks, so they are
listed separately, but they fail a stage exactly the same way.

| From stage | Requirement | Checked by |
| --- | --- | --- |
| **05+** | A frozen preregistration exists, holds at least one empirical hypothesis, every one carries a `decision_rule`, and the manifest has not silently changed under it. | `validate_preregistration` |
| **05+** | An experimental protocol declares a primary metric, planned seeds, and per-baseline `why_competent` and `tuning_budget`. | `validate_experimental_protocol` |
| **06+** | Exactly one verdict per frozen hypothesis, nothing unpreregistered adjudicated, and every `supported`/`refuted` verdict citing an evidence file that exists. | `validate_hypothesis_outcomes` |
| **06+** | Each `supported` or `refuted` verdict carries `statistics.n_seeds`, a `dispersion_type` that starts with a known measure and may then gloss it, and a written justification when a single run settled it (`MIN_SEEDS_FOR_A_VERDICT` is 2). `inconclusive` and `not_tested` are exempt on purpose. | `validate_outcome_statistics` |

The argument for the chain, and where each link is frozen, is in
[The AutoR Framework](framework.md#33-the-validity-chain).

### Freshness checks

Existence alone is not enough for the stage that is supposed to *produce* a
class of artifact. AutoR records a timestamp when a stage starts executing
(`operator_state/<slug>.started_at.txt`) and requires the artifacts that stage
owns to be at least that new.

| Stage | Must be newly written during this stage |
| --- | --- |
| `03_study_design` | at least one file under `workspace/data/` **whose suffix is in `MACHINE_DATA_SUFFIXES`** |
| `06_analysis` | at least one file under `workspace/figures/` **whose suffix is in `FIGURE_SUFFIXES`** |
| `07_writing` (markdown) | `report/report.md`, `citation_verification.json`, `self_review.json`, `report_review.json` |
| `07_writing` (latex) | `main.tex`, `build_log.txt`, `citation_verification.json`, `self_review.json`, `layout_review.json`, a PDF, and at least one `sections/*.tex` |
| `08_dissemination` | at least one file under `workspace/reviews/` |

The rows are not one rule. The Stage 03 and Stage 06 rows go through
`_has_recent_files_with_suffixes` against the same suffix sets their existence
checks use, so writing a file is not the same as satisfying them: a run that
inherits an older `data/prior.csv` and writes only `data/notes.md` this time is
refused with *"requires machine-readable data artifacts produced or updated
during the current stage execution"*, even though a file under `workspace/data/`
was newly written. The `08_dissemination` row is the one with no suffix filter:
it iterates `_existing_files(paths.reviews_dir)`, so any newly written file
there counts.

This is what stops a re-run from being credited with the previous attempt's
files. Stages that only *consume* an artifact class (for example Stage 05
reading `workspace/data/`) check existence but not freshness.

### The report plan

`workspace/notes/report_plan.json` is where the run commits to its figures —
at Stage 03, before a result exists that could choose them for it. The module
is [`src/report_plan.py`](../src/report_plan.py), and it holds the plan at three
different stages with three different questions:

| Stage | Question | Validator |
| --- | --- | --- |
| **03+** | Is the plan a commitment — every field present, every slot distinct? | `validate_report_plan` |
| **06+** | Does the file each live slot and headline number draws from exist and hold bytes? | `validate_report_plan_sources` |
| **07+, markdown only** | Was every live slot published and referenced, or dropped on the record? | `validate_report_plan_coverage` |

Each entry in `figures` needs a `slot` (unique, contiguous from 1), a bare
`filename` whose suffix this run's deliverable publishes (see below), a
`supports` list naming the claim the figure settles (a
`hypothesis_manifest.json` id, or `exploratory:<slug>` with a slug of at least
`MIN_EXPLORATORY_SLUG_CHARS` (3) characters), a `shows` sentence of at least
`MIN_SHOWS_CHARS` (40) characters, an `if_supported` and an `if_refuted` of at
least `MIN_BRANCH_CHARS` (20) characters each that are not the same sentence,
and a `source_artifact` under `results/`, `data/` or `outputs/`. In markdown
mode there may be at most `MAX_REPORT_FIGURES` slots.

**The plan's suffix rule is narrower than the report's.**
`_allowed_figure_suffixes` returns exactly `{".png"}`
(`PREFERRED_REPORT_IMAGE_SUFFIX`) in markdown mode, and only in latex mode does
it widen to the full `FIGURE_SUFFIXES` set (`.png .pdf .svg .jpg .jpeg`).
Anything else is refused at Stage 03 with *"whose format is not published by
this run's deliverable"*. That is not the same set as
`RENDERABLE_IMAGE_SUFFIXES` (`.png .jpg .jpeg .gif .webp`), which is what Stage
07 accepts in `report.md`: a `.jpg` already on disk is a legal reference in the
report, but a plan slot that *declares* `main_result.jpg` never gets that far.
Plan every markdown figure as `.png`.

Two fields outside `figures` are also required at Stage 03:

- `headline_numbers` — the quantities the report must state, each with a
  `quantity`, a non-empty `unit` (`dimensionless` and `count` are units) and a
  `source_artifact`. The list may not be empty, and holds at most
  `MAX_HEADLINE_NUMBERS` (8) entries.
- `task_outputs` — every deliverable the task description states, each answered
  by a `figure:<slot>`, a `number:<index>`, `prose`, or `not_attempted` with a
  reason of at least 20 characters. A `figure`/`number` target that the plan
  does not declare is refused.

A plan with **no** figures is allowed but has to say so: `no_figures_because`,
at least `MIN_SHOWS_CHARS` (40) characters, naming what the prose carries
instead. Three of the forty ResearchClawBench tasks have no image criterion at
all, and this field is how such a study declines to *commit* to a figure at
Stage 03 rather than inventing a slot to satisfy the gate.

**Declining a slot does not exempt the run from publishing figures.** On the
markdown branch, Stage 07 measures `report/images/` against
`resolve_min_report_figures`, which clamps into `[1, MAX_REPORT_FIGURES]` and so
can never yield a floor of 0, and `validate_markdown_report` separately refuses
a report that references no image at all. A ResearchClawBench run is a markdown
run whose floor `rcb_agent.py` raises to `BENCHMARK_MIN_REPORT_FIGURES` (3), so
those image-criterion-free tasks still owe three published figures. An empty
plan buys a study silence at Stage 03, not an illustration-free report.

Two rules exist to stop the file being satisfied without committing to
anything:

- **Every slot must carry at least one claim no other slot carries.** This is
  the only rule here that pushes the figure count *down*, and nothing in
  `report_plan.py` pushes it up: the published-figure floor is
  `validate_markdown_report`'s, at Stage 07, not the plan's. `MAX_REPORT_FIGURES`
  is a ceiling, and a plan gate that restated it as a goal would have made it a
  quota.
- **A slot cannot be born dropped.** `dropped_because` is skipped by the Stage
  06 source check and the Stage 07 coverage check, so a slot abandoned in the
  same plan that declares it would owe nothing at all. Dropping is only allowed
  once AutoR has stamped the plan — that is, from the Stage 03 approval onward,
  which is what makes it a record of the results changing the plan rather than
  padding.

`declared_at`, `digest` and `amendments` are AutoR's, written by
`stamp_report_plan` on Stage 03 approval and kept in `report_plan_stamp.json`
outside `workspace/`. The agent does not write them, and the validators ignore
them in the file.

### The deliverables contract

Every other gate on this page measures how well the report was *made*.
`validate_deliverables_coverage` ([`src/deliverables.py`](../src/deliverables.py))
asks the prior question: did the run answer what it was asked? It is a hard
Stage 07 gate on the markdown branch, and a report that is rigorous about the
wrong question fails it.

The stage writes `workspace/artifacts/deliverables_coverage.json`:

```json
{"deliverables": [
  {"task_quote": "<verbatim span of the task statement>",
   "addressed": true,
   "where": "<section heading or images/figure.png in report.md>"},
  {"task_quote": "<verbatim span>", "addressed": false,
   "reason": "<why it could not be answered>"}
]}
```

The rules a machine can settle, and does:

- **`task_quote` must be verbatim.** The quote is compared against
  `user_input.txt` with whitespace collapsed and both sides lower-cased, and
  nothing else. This is the rule with teeth: without it a stage can restate an
  inconvenient requirement as something it happened to do and mark that
  addressed.
- **`addressed` must be a boolean.** An entry without one is refused before its
  `where`/`reason` is looked at.
- **An addressed entry needs a `where` that appears in `report.md`.** The match
  is deliberately loose — a section title, a figure filename or a heading all
  count, and the locator is also split on `/`, `,`, `;`, `|` and ` and ` so a
  fragment of at least six characters can carry it. The point is that the
  pointer is not fabricated, not that it follows a format.
- **An unaddressed entry needs a `reason`.** Reporting a requirement as unmet is
  a valid outcome; omitting it is not.
- **Every demanding sentence must be covered.** `demanding_sentences()` picks
  the sentences of the task statement that are at least 25 characters and
  contain one of the 34 `DEMAND_VERBS` — *derive*, *compute*, *compare*,
  *constrain*, *reproduce* and the rest. A sentence whose content
  words (longer than three characters) overlap the union of all quotes by less
  than 34% is reported as unaccounted for, up to five at a time.

What it does **not** do is judge whether the answer is correct. That is the same
line every other validator on this page holds.

> **A trap worth knowing.** The file is required unconditionally on the markdown
> branch, but the only place the agent is ever told to write it is
> `format_deliverables_for_prompt`, which returns `""` when `demanding_sentences()`
> finds nothing. A goal phrased without a demand verb — *"I want to know whether
> X causes Y"* — therefore gets no `# What the Task Asks For` block in any stage
> prompt, and then hits a Stage 07 refusal for a file it was never asked to
> write. Phrasing the goal with an explicit verb avoids it; so does writing the
> file by hand.

### The evidence ledger

Stage 01 must leave a citable trail rather than a paper list.

`workspace/literature/sources.json` — every entry needs a unique non-empty
`source_id` and a non-empty `title`. Duplicate IDs are rejected.

`workspace/literature/claims.json` — every entry needs a non-empty `claim_id`,
claim text under either `statement` or `claim`, and at least one entry in
`source_ids`. **Every referenced `source_id` must exist in `sources.json`**;
dangling references are reported by name.

That last rule is the point of the ledger: a claim that cites nothing real
cannot pass Stage 01.

### Venue matching

Stage 07's `main.tex` must look like a manuscript for the venue the run was
started with. `_markers_for_venue` builds the accepted markers from three of the
venue's registry fields — its key, its `display_name` and its `style_package` —
each normalized for case, spaces and punctuation, and `main.tex` passes if the
normalized text contains any one of them. A venue whose `style_package` is empty
(`nature`, `nature_communications`) is matched on the other two.

An explicit override comment is accepted anywhere in the file, not only at the
top:

```tex
% AutoR venue: iclr_2026
```

It has to name the run's own venue. A comment naming some *other* registered
venue grants nothing: the check falls back to hunting the expected venue's own
markers in the text, and fails if it finds none. A comment naming a key that is
not in the registry at all is discarded and treated as if it were absent. The
failure message names the expected venue key and repeats the comment form, so a
mismatch is self-explanatory.

---

## What the gate deliberately does not check

- Whether the science is correct.
- Whether the experiment is more than a smoke test.
- Whether the numbers in the summary match the numbers in the result files.
- Whether a figure is meaningful or merely present.
- Whether a citation supports the claim it is attached to.

Those are yours. The
[review checklists in the user guide](tutorial_en.md#10-how-to-review-each-stage)
are the practical counterpart to this page.
