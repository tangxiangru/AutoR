# Stage Contract

A stage is only accepted when it satisfies two independent checks:

1. **The markdown contract** — the stage summary has the required shape.
   Enforced by `validate_stage_markdown` in [`src/utils.py`](../src/utils.py).
2. **The artifact gate** — real files exist in the right places, and for the
   stages that produce them, they were written *during this stage's execution*.
   Enforced by `validate_stage_artifacts` in [`src/utils.py`](../src/utils.py).

A stage that passes both is shown to you for approval. A stage that fails
either one is repaired, normalized locally, or re-run — up to
`MAX_STAGE_ATTEMPTS` (5) attempts, after which AutoR stops and escalates.

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
## Previously Approved Stage Summaries
## What I Did
## Key Results
## Files Produced
## Decision Ledger
## Suggestions for Refinement
## Your Options
```

All eight headings are required, in the list defined by
`REQUIRED_STAGE_HEADINGS`. A missing heading is reported as
`Missing required section: <name>`.

### Title

The first non-empty line must be exactly `# Stage NN: <Display Name>` for that
stage — for example `# Stage 03: Study Design`. Anything else fails with
`Stage markdown title must be exactly '...'`.

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

Artifact requirements are **cumulative**: a Stage 07 run must still satisfy
everything Stage 03, 05, and 06 required.

| From stage | Requirement |
| --- | --- |
| **01** | `workspace/literature/sources.json` and `workspace/literature/claims.json` exist and cross-reference correctly (see [the evidence ledger](#the-evidence-ledger)). |
| **03+** | At least one machine-readable file under `workspace/data/` with a suffix in `.json .jsonl .csv .tsv .parquet .yaml .yml`. |
| **05+** | At least one result file under `workspace/results/` with a suffix in `.json .jsonl .csv .tsv .parquet .npz .npy`. |
| **05+** | `workspace/results/experiment_manifest.json` exists and is structurally valid. |
| **06+** | At least one figure under `workspace/figures/` with a suffix in `.png .pdf .svg .jpg .jpeg`. |
| **08+** | At least one file under `workspace/reviews/`. |

Stage 07's requirements depend on the run's `output_format`.

**`markdown` (the default):**

| From stage | Requirement |
| --- | --- |
| **07+** | `workspace/report/report.md` exists and holds at least 1,200 characters. |
| **07+** | It contains no placeholder text. |
| **07+** | It references at least one figure, via `![...](...)` or `<img src="...">`. |
| **07+** | Every figure reference is report-relative — not absolute, not a URL. |
| **07+** | Every figure reference resolves to a file that exists under `workspace/report/`. |
| **07+** | Every referenced figure is renderable: `.png .jpg .jpeg .gif .webp`. |
| **07+** | At least one renderable image under `workspace/report/images/`, and **at most 5**. |
| **07+** | `workspace/artifacts/citation_verification.json`, structurally valid. |
| **07+** | `workspace/artifacts/self_review.json`. |
| **07+** | `workspace/artifacts/report_review.json`, structurally valid. |

The upper bound is not a style preference. A benchmark judge is shown only the first five
images it finds, in filesystem order, so a sixth figure does not add a sixth chance to be
credited — it makes it arbitrary which of yours are seen.

**`latex`:**

| From stage | Requirement |
| --- | --- |
| **07+** | `workspace/writing/main.tex` exists **and** matches the selected venue (see [venue matching](#venue-matching)). |
| **07+** | A `.bib` file under `workspace/writing/`, or an inline bibliography. |
| **07+** | At least one `.tex` file under `workspace/writing/sections/`. |
| **07+** | A compiled PDF under `workspace/writing/` or `workspace/artifacts/`. |
| **07+** | `workspace/artifacts/build_log.txt`. |
| **07+** | `workspace/artifacts/citation_verification.json`, structurally valid. |
| **07+** | `workspace/artifacts/self_review.json`. |
| **07+** | `workspace/artifacts/layout_review.json`, structurally valid. |

The schemas of the validated JSON files are in
[Run Artifacts](run-artifacts.md).

### Freshness checks

Existence alone is not enough for the stage that is supposed to *produce* a
class of artifact. AutoR records a timestamp when a stage starts executing
(`operator_state/<slug>.started_at.txt`) and requires the artifacts that stage
owns to be at least that new.

| Stage | Must be newly written during this stage |
| --- | --- |
| `03_study_design` | at least one file under `workspace/data/` |
| `06_analysis` | at least one file under `workspace/figures/` |
| `07_writing` (markdown) | `report/report.md`, `citation_verification.json`, `self_review.json`, `report_review.json` |
| `07_writing` (latex) | `main.tex`, `build_log.txt`, `citation_verification.json`, `self_review.json`, `layout_review.json`, a PDF, and at least one `sections/*.tex` |
| `08_dissemination` | at least one file under `workspace/reviews/` |

This is what stops a re-run from being credited with the previous attempt's
files. Stages that only *consume* an artifact class (for example Stage 05
reading `workspace/data/`) check existence but not freshness.

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
started with. AutoR checks for the venue's style package, and accepts an
explicit override comment near the top of the file:

```tex
% AutoR venue: iclr_2026
```

The failure message names the expected venue key, so a mismatch is
self-explanatory.

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
