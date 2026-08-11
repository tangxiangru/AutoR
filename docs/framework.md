# The AutoR Framework

*What this system is, how it is built, what is new in it, and what it contributes.*

This is the design document. [The README](../README.md) is the overview and the operating manual;
[architecture.md](architecture.md) is the module map; this page is the argument. Every claim here
names the symbol that implements it, so it can be checked rather than believed.

---

## Contents

1. [The problem](#1-the-problem)
2. [The design commitments](#2-the-design-commitments)
3. [Implementation: the control loop](#3-implementation-the-control-loop)
4. [The modules, by layer](#4-the-modules-by-layer)
5. [Novelty](#5-novelty)
6. [Contribution](#6-contribution)
7. [What has not been established](#7-what-has-not-been-established)

---

## 1. The problem

A coding agent is already a competent research executor. Give one a GPU, a dataset and a clear
instruction and it will write the training loop, run the sweep, make the plot and describe what it
found. That capability is not the bottleneck.

The bottleneck is that **nothing in the loop distinguishes a finding from a fluent description of
one.** Three failure modes recur, and they are all invisible to the artifact the agent produces:

1. **Post-hoc hypothesis.** The agent runs the experiment, sees the result, and writes the
   hypothesis the result supports. Nothing in the transcript reveals the reordering, because the
   final document is written last either way.
2. **The self-graded loop.** Ask the agent to improve its own work and it will produce something
   different and describe it as better. Iteration without an external measurement is drift with a
   progress bar.
3. **The unfalsifiable report.** Prose is a lossy encoding of evidence. "The method improves
   performance" survives the loss of the number, the seed, the baseline and the file that would have
   let a reader disagree.

Existing research harnesses mostly attack the *capability* gap: better tools, more subagents, longer
memory, accumulated skills. AutoR attacks the *warrant* gap. Its thesis is that the interesting
engineering problem is not making an agent produce more research-shaped output, but building a
structure in which a claim that is not warranted **cannot be advanced** — enforced in code, not in a
prompt.

The design constraint that follows: **every mechanism must be a file on disk and a function that
refuses.** Not an instruction the model is asked to follow, not a persona, not a self-report. A
prompt asking a model to be rigorous is a wish. A validator that reads `hypothesis_outcomes.json`,
resolves each cited evidence path, and returns a non-empty problem list is a gate.

---

## 2. The design commitments

Six commitments determine most of the architecture. Each one is a decision that could have gone the
other way, and each one costs something.

### 2.1 The human owns the approval gate

`approval_mode` is `manual` unless a flag opts out. Of the eight recursive mechanisms, seven can only
**score, refuse, revert or re-order** — none can approve a stage. The eighth, the review panel, *is*
an approval gate, and only exists on runs where you hand it the gate.

*Cost:* a default run is not autonomous, and cannot be benchmarked without `--full-auto`.
*Why anyway:* the alternative is a system whose most consequential act — deciding that a stage is
done — is performed by the same model family that produced the work.

### 2.2 A gate reads the filesystem, not the transcript

Every gate in AutoR takes `RunPaths` and returns a list of problems. It does not read the model's
account of what it did; it reads what is on disk. `validate_hypothesis_outcomes` does not ask whether
the agent says it adjudicated H1 — it opens `workspace/results/hypothesis_outcomes.json`, checks the
verdict is one of four legal tokens, and resolves every cited evidence path to a file that exists.

*Cost:* the agent has to write machine-readable artifacts it would not otherwise write, and the gate
has to be told about every new artifact class.
*Why anyway:* a check over a self-report measures the model's willingness to describe itself
accurately, which is exactly the variable under test.

### 2.3 Commitments are frozen before the evidence exists

`freeze_preregistration()` copies the typed hypothesis manifest into `preregistration.json` with a
`digest` and a `source_digest` when Stage 04 is approved, and never overwrites it. From Stage 05 on,
every empirical hypothesis must carry a `decision_rule` stated **before** the experiment. At Stage
06, exactly one verdict per frozen hypothesis, adjudicating nothing that was not preregistered. The
same shape applies to the report: `report_plan.json` commits at Stage 03 to which figures the report
will carry and which claim each supports, and it is stamped into
`runs/<id>/report_plan_stamp.json` — deliberately **outside** `workspace/`, so the agent cannot
backdate its own declaration.

*Cost:* a run that discovers something better at Stage 06 has to file an amendment rather than just
change the plan.
*Why anyway:* this is the only structural defence against the post-hoc hypothesis, and an amendment
with a `previous_digest` is a record of the change rather than an erasure of it.

### 2.4 The improvement loop is scored by something it cannot influence

`src/rubric.py` scores a draft on eight weighted criteria, **never calls a backend**, and is
**verdict-blind**: a refuted hypothesis with clean evidence outscores a supported one resting on an
assertion. `src/evolution.py` keeps the champion and reverts a round that scores worse. On top of
that, `verdict_digest()` hashes the `(id, verdict)` set, and any AutoR-initiated polish round that
moves it is rejected outright with a `verdict_drift` ledger row.

*Cost:* the rubric can only measure what is mechanically checkable, so it is blind to whether the
idea is any good.
*Why anyway:* a self-improvement loop scored by a model develops a taste for whatever that model
likes. Removing the incentive (verdict-blindness) and then removing the possibility (drift
rejection) is belt and braces, on purpose: the failure it prevents — a loop that improves its
*answer* rather than its *work* — is the one that would be hardest to detect after the fact.

### 2.5 Every optional mechanism carries its own control arm

A review panel run also records what its chair alone would have decided in round 1: one model, one
call, no peer input. `panel_effect.json` accumulates panel-vs-solo across the run. The ideation panel
measures adoption after the stage is approved. Anchored comments are diffed for collateral change.
Crux deliberation is compared against what the agent already believed. Effort tiers record what they
routed where. `src/scorecard.py` reads all five ledgers at the end of every run and writes a verdict
phrased to be unflattering — *"it did not earn that cost; consider dropping the panel"* — when that
is the truth, and keeps *"could not be measured"* strictly separate from *"changed nothing"*.

*Cost:* every feature is roughly 20% more code than the feature alone would need.
*Why anyway:* a research harness that cannot say whether its own machinery helps is asking for the
same credulity it is built to remove.

### 2.6 No runtime dependency outside the standard library

AutoR's runtime imports nothing that is not in the Python standard library. 150 modules, ~62 k lines,
1820 tests running in ~70 s with no install step. The MCP web-search server
([`mcp_web_search.py`](../src/mcp_web_search.py)) is a stdlib JSON-RPC 2.0 implementation over stdio
rather than an SDK. `google-genai` is needed only by three optional paths (`--web-search gemini`,
`--cross-review`, `--research-diagram`), and each degrades to a recorded *unavailable* rather than a
crash.

*Cost:* some wheels get reinvented.
*Why anyway:* a research harness that cannot be run five years from now cannot be used to reproduce
anything, and a dependency tree is the most common reason a scientific artifact stops running.

---

## 3. Implementation: the control loop

### 3.1 The unit of work

One **run** is one directory: `runs/<run_id>/`. Everything the run knows, produced, was told, and
decided is inside it. The only state written outside is the optional cross-run archive at
`~/.autor/archive`. A run is isolated, resumable (`--resume-run`), replayable at a single stage
(`--redo-stage`), and reversible (`--rollback-stage`).

### 3.2 The walk

Eight stages are nodes in a directed graph ([`stage_graph.py`](../src/stage_graph.py)); a `finish`
node closes the walk. The default topology is `adaptive`: **22 edges** — eight advance edges of which
six carry a guard, thirteen `REVISIT_EDGES` that go backward, and one conditional terminal that lets
an abandoned round finish from Stage 06. `--stage-graph linear` is nine edges and no guards.

```
                        ┌──────────────── 13 backward edges ─────────────────┐
                        ▼                                                    │
  01 ──▶ 02 ──▶ 03 ──▶ 04 ──▶ 05 ──▶ 06 ──▶ 07 ──▶ 08 ──▶ finish             │
   survey  hypo  design  impl   exp   analysis  write  release               │
                  ▲       ▲      ▲      ▲        ▲        ▲                  │
              has_hypo  design  runnable results validity report ────────────┘
                        artifacts  code   exist   chain    exists
```

The control loop, per step:

1. **Compose the prompt.** `render_inbound(ChannelContext(...), CHANNELS)` builds the stage's inbound
   context from the sixteen typed channels in [`information_flow.py`](../src/information_flow.py).
   Each channel declares `produced_by`, a `consumed_by` set of real stage slugs, and a written
   `rationale`; a test fails any channel that withholds itself from a stage without saying why.
2. **Execute.** The prompt is written verbatim to `prompt_cache/` and handed to the coding agent CLI
   in streaming mode, with a per-stage session ID so a refinement attempt continues the same
   conversation. A skill pack is installed into the operator's working directory so the agent can
   *pull* long-form craft guidance instead of being pushed it.
3. **Validate.** `validate_stage_markdown` checks the seven-heading contract; `validate_stage_artifacts`
   runs the cumulative artifact gates and the seventeen `validate_*` functions. A failure triggers a
   repair attempt, then local normalisation, then a full re-run, bounded by `--max-attempts` (5).
4. **Measure and improve.** Every *valid* draft is scored by the rubric. Up to two polish rounds per
   stage are budgeted, skipped entirely when no criterion has a shortfall worth acting on. Losing
   rounds are reverted; the Pareto frontier keeps a draft that loses on the weighted total but is
   non-dominated on the criterion vector.
5. **Review.** The gate: a human by default, or a solo agent reviewer, or a five-seat panel. An
   approval may attach obligations to a later stage; a refusal becomes a standing rule. After Stages
   05 and 06 an adversarial reviewer attacks the approved result, and the *next* stage is refused
   until it answers every finding in writing.
6. **Route.** `StageGraph.moves()` evaluates every edge's guard against the artifacts on disk and
   hands the agent the admissible moves **plus the reason each blocked one is blocked**. The agent
   picks and justifies; an off-menu pick, or one with no stated reason, is refused, logged to
   `routing_refusals.jsonl`, and replaced by the forward edge.
7. **Record.** The route, the per-stage and per-criterion fitness, the comparability basis, and the
   decisions that were *offered and declined* go into the archive.

Two properties of step 6 are load-bearing. First, **AutoR owns the menu and the agent owns the
pick**: the guards are the correctness argument for letting a model route at all, so the component
that learns from outcomes (the archive) may reorder preferences but can never open a guarded edge,
add an undeclared one, or remove one. Second, **the default is always forward**. A refusal, a routing
failure, or a run nobody is steering all come out as the linear pipeline rather than as a stall — a
backward move is only ever a deliberate, justified choice, and one whose justification repeats a
reason already on the path is refused as a loop.

### 3.3 The validity chain

The chain that runs unconditionally at every rigor level, `fast` included:

| Point | What happens | Enforced by |
| --- | --- | --- |
| Stage 02 | Markdown is parsed into typed `T*`/`H*`/`C*` entries with `decision_rule` | `write_hypothesis_manifest` |
| Stage 04 approval | The hypothesis set is copied, hashed and frozen; never overwritten | `freeze_preregistration` |
| Stage 02 re-run | The freeze is re-derived and an amendment row records `previous_digest` | `amend_preregistration` |
| Stage 05+ | A prereg exists, has an empirical hypothesis, every one has a decision rule, the manifest has not silently changed | `validate_preregistration` |
| Stage 05+ | A protocol declares a primary metric, planned seeds, and per-baseline `why_competent` + `tuning_budget` | `validate_experimental_protocol` |
| Stage 06+ | Exactly one verdict per frozen hypothesis, nothing unpreregistered adjudicated, every `supported`/`refuted` verdict citing an evidence file that exists | `validate_hypothesis_outcomes` |
| Stage 06+ | A verdict carries `n_seeds`, a `dispersion_type` from a fixed vocabulary, and a written justification if a single seed settled it | `validate_outcome_statistics` |
| Stage 06 close | `converged` is refused when nothing came out supported, unless the round declares `negative_result: true` | `validate_round_decision` |
| Stage 06→07 edge | The router keeps writing closed until every empirical id has a verdict and a figure exists | `_guard_validity_chain` |
| Stage 07+ | Every manuscript claim is `confirmatory` on a `supported` hypothesis, or labelled `exploratory` — and cites a file that exists | `validate_claim_provenance` |
| Stage 07 | The report answers every demanding sentence of the task statement, quoting the task verbatim | `validate_deliverables_coverage` |

Every one of these can be traced from `validate_stage_artifacts` in [`utils.py`](../src/utils.py),
whose own comment names the split: *"the scientific-validity chain, distinct from the artifact gates
around it"*.

### 3.4 Rounds, not just stages

Stages 03–06 form a repeatable **round** ([`research_rounds.py`](../src/research_rounds.py)). A round
closes at Stage 06 with one of four decisions — `converged`, `refine_design`, `new_hypothesis`,
`abandon` — recorded with the hypothesis verdicts as they stood. This is what makes a refuted
hypothesis a legitimate outcome that can start a second round rather than a failure to be written
around. `--max-rounds` defaults to 1, which is the main place the recursion is currently throttled.

### 3.5 The rigor dial

Four levels collapse the optional machinery into one flag ([`rigor.py`](../src/rigor.py)), ordered by
what each costs and what evidence there is for it:

| `--rigor` | effort tiers | crux deliberation | ideation panel | review panel |
| --- | :---: | :---: | :---: | :---: |
| `fast` | – | – | – | – |
| `standard` *(default)* | **on** | – | – | – |
| `thorough` | **on** | **on** | **on** | – |
| `max` | **on** | **on** | **on** | **on** |

An explicit `--flag`/`--no-flag` always beats the level. The validity chain is not on this dial.

---

## 4. The modules, by layer

150 Python modules, ~62 k lines. Grouped by what they own rather than by directory.

### Policy — what machinery this run uses

| Module | Owns |
| --- | --- |
| [`rigor.py`](../src/rigor.py) | The four levels and the feature set each turns on. One source of truth. |
| [`effort.py`](../src/effort.py) | Routine vs deliberative stages; each stage sets the next one's tier; a routine stage that keeps failing is promoted. Concentrates the strong model where something is undecided. |

### The walk — where the run goes next

| Module | Owns |
| --- | --- |
| [`manager.py`](../src/manager.py) | The control loop: the attempt/repair/normalise cycle, the freeze seam, the round close, the crux settlement, the obligation ledger, the cross-review call, the inbound-channel record. The largest module, and deliberately so — it is the place the sequencing lives. |
| [`stage_graph.py`](../src/stage_graph.py) | Nodes, edges, guards, visit budgets, and the two topologies. |
| [`router.py`](../src/router.py) | The agent's pick among admissible moves, and the refusal of an off-menu or unjustified one. |
| [`research_rounds.py`](../src/research_rounds.py) | Stages 03–06 as a repeatable round with a recorded closing decision. |
| [`information_flow.py`](../src/information_flow.py) | Sixteen typed context channels with declared readers and written rationales. |

### Gates — what a stage must produce to be accepted

| Module | Owns |
| --- | --- |
| [`utils.py`](../src/utils.py) | `validate_stage_artifacts`: the single cumulative gate that hosts everything below, plus stage metadata, run paths and prompt assembly. |
| [`preregistration.py`](../src/preregistration.py) | Freeze, amend, adjudicate, trace. |
| [`hypothesis_manifest.py`](../src/hypothesis_manifest.py) | Stage 02 markdown → typed `T`/`H`/`C` entries. |
| [`experimental_protocol.py`](../src/experimental_protocol.py) | Declared baselines, seeds and dispersion, fixed before the result. |
| [`report_plan.py`](../src/report_plan.py) | Figures and headline numbers committed at Stage 03, stamped outside the workspace, enforced at 03, 06 and 07. |
| [`deliverables.py`](../src/deliverables.py) | Did the run answer what the task statement actually demanded? |
| [`evidence_ledger.py`](../src/evidence_ledger.py) | Stage 01's `sources.json`/`claims.json` cross-reference, and Stage 07's citation self-report. |
| [`experiment_manifest.py`](../src/experiment_manifest.py) · [`artifact_index.py`](../src/artifact_index.py) · [`writing_manifest.py`](../src/writing_manifest.py) | The machine-readable inventories later stages read instead of guessing from filenames. |

### Review — five kinds of critic, two of which are the gate

| Module | Owns | Can approve? |
| --- | --- | :---: |
| [`approval_agent.py`](../src/approval_agent.py) | The solo gate: six choices, a re-ask-once parser, an unattended fallback that sends back rather than aborting. | yes |
| [`review_panel.py`](../src/review_panel.py) | Five seats, blind round then anonymised cross-examination then a chair; a blocking objection is enforced *in code* against the chair. | yes |
| [`cross_reviewer.py`](../src/cross_reviewer.py) | A different model family auditing an approval. Unavailable is never laundered into agreement. | veto only |
| [`validity_review.py`](../src/validity_review.py) | The adversarial pass after 05 and 06 across ten named failure modes, and the response gate that follows it. | no |
| [`deliberation.py`](../src/deliberation.py) | The crux panel: four voices, each committing then arguing against itself, resolved into an answer that must name its own falsifier. | no |
| [`stage_comments.py`](../src/stage_comments.py) | Anchored comments: quote ≥12 characters, change only those spans, diff for collateral. | no |
| [`obligations.py`](../src/obligations.py) | What a later stage owes; only a reviewer discharges it; deferral is counted. | no |
| [`review_policy.py`](../src/review_policy.py) | Standing rules learned from this run's own refusals, deduplicated so restatement cannot fake learning. | no |

### Improvement — which draft survives

| Module | Owns |
| --- | --- |
| [`rubric.py`](../src/rubric.py) | Eight weighted criteria over a draft and the artifacts it names. Backend-free, verdict-blind, versioned. |
| [`evolution.py`](../src/evolution.py) | The champion ratchet, the polish budget, the revert, and the `verdict_drift` rejection. |
| [`pareto.py`](../src/pareto.py) | Non-dominated drafts kept beside the champion. |
| [`ideation_panel.py`](../src/ideation_panel.py) | Five divergent Stage 02 proposers, Jaccard-deduplicated into a scored candidate pool. It decides nothing. |

### Self-measurement — did any of this help?

| Module | Owns |
| --- | --- |
| [`scorecard.py`](../src/scorecard.py) | Reads all five feature ledgers and writes the end-of-run verdict on which flags earned their cost. |
| [`archive.py`](../src/archive.py) | Cross-run routes and edge payoffs keyed on a comparability basis; variant proposal, exploration and conservative promotion. |
| [`decisions.py`](../src/decisions.py) | "Was offered this edge and declined" — the control arm the payoffs are computed against. |
| [`trials.py`](../src/trials.py) | Paired A/B trials over archived runs. |
| [`inference.py`](../src/inference.py) | Exact permutation tests and attainable-p floors; derives the archive's `min_observations` from the family size rather than asserting it. |

### Execution — the agent, and everything around it

| Module | Owns |
| --- | --- |
| [`operator.py`](../src/operator.py) · [`operator_codex.py`](../src/operator_codex.py) · [`operator_protocol.py`](../src/operator_protocol.py) | The Claude and Codex CLI adapters behind one protocol: session state, live streaming, resume fallback, MCP config, skill install. |
| [`web_search.py`](../src/web_search.py) · [`mcp_web_search.py`](../src/mcp_web_search.py) | Gemini-backed search, readiness assessment, and a stdlib JSON-RPC MCP stdio server exposing it as a tool. |
| [`backend_health.py`](../src/backend_health.py) | Telling "the model was unreachable" apart from "the research failed". |
| [`prompt_fragments.py`](../src/prompt_fragments.py) | Shared prompt blocks generated from the validators' own constants, so a limit cannot drift between the gate and the instruction. |
| [`run_skills.py`](../src/run_skills.py) · [`skills/`](../src/skills) | Six pull-on-demand craft skills installed into the run's working directory. |

### Output and adapters

| Module | Owns |
| --- | --- |
| [`platform/foundry.py`](../src/platform/foundry.py) | The LaTeX paper package and the Stage 08 release bundle. |
| [`rcb.py`](../src/rcb.py) · [`rcb_agent.py`](../rcb_agent.py) | The ResearchClawBench adapter: workspace layout, goal construction, report selection, figure publication, export. |
| [`studio_service.py`](../src/studio_service.py) · [`backend/`](../src/backend) · [`frontend/`](../src/frontend) | The local browser workspace over the same run directories. |
| [`terminal_ui.py`](../src/terminal_ui.py) | The terminal-first interaction layer. |

---

## 5. Novelty

Four things in AutoR are, as far as we are aware, not present in the research-agent systems it is
comparable to. Each is stated as a mechanism, not as an aspiration, and each names the file.

### 5.1 A preregistration that is a gate, not a document

Many systems ask a model to state hypotheses before experimenting. AutoR makes the statement
**structurally binding**: the typed hypothesis set is hashed at Stage 04 approval, the digest is
echoed into the outcomes file at Stage 06, and `validate_hypothesis_outcomes` refuses a run that
adjudicates something not in the frozen set, omits something that is, or cites an evidence path that
does not resolve. Changing the set later is legal, but only as an `amendment` row carrying
`previous_digest`. A dropped hypothesis leaves a trace; it cannot be silently deleted.

The distinctive part is not the freeze — it is the **chain**: freeze at 04, adjudicate at 06 against
a file that exists, trace every manuscript claim at 07 to a `supported` hypothesis or an explicit
`exploratory` label, and close the router edge into writing until all of that holds. Each link is a
function that returns problems, and a run cannot advance while any of them does.

We are not aware of another agentic research harness in which the post-hoc hypothesis is refused by a
validator rather than discouraged by a prompt.

### 5.2 A self-improvement loop that is explicitly prevented from improving the answer

The obvious way to build a scored improvement loop is to score the output. That produces a system
that optimises toward whatever the scorer likes — and if the scorer is a model, toward whatever that
model finds persuasive.

AutoR's rubric is deliberately weaker than that and deliberately blind. It **never calls a backend**:
it resolves paths, matches reported numbers against results files, checks artifact freshness against
the stage-execution marker, and inspects the decision ledger for four distinct entries. It is
**verdict-blind**: a refuted hypothesis with clean evidence scores above a supported one resting on
an assertion, so there is no gradient toward a nicer conclusion. And it is backed by a second,
independent guard: `verdict_digest()` hashes the `(id, verdict)` set, and an AutoR-initiated polish
round that moves it is rejected outright with a `verdict_drift` row — whatever it scored.

The pairing is the point. Verdict-blindness removes the *incentive* to improve the answer; drift
rejection removes the *possibility*. A revision a **human** asked for is exempt by design: the
ratchet governs AutoR's own rounds, not the direction it is given.

### 5.3 Machinery that reports on itself, in the unflattering direction

Every optional feature in AutoR runs its own control arm and writes a ledger:

- **Review panel** — the chair's round-1 verdict is the solo baseline; `panel_effect.json` records
  gates reviewed, gates where the panel *changed* the decision, chair overrides, call count and cost
  multiple.
- **Ideation panel** — adoption is measured *after* the stage is approved, so "the panel proposed
  five ideas" is separated from "the stage used one".
- **Anchored comments** — `comment_ledger.json` counts lines changed on target against lines changed
  as collateral, so "preserve the correct parts" is measured.
- **Crux deliberation** — the resolution is compared against what the agent already believed, so an
  escalation that confirmed a prior belief is not counted as an escalation that changed one.
- **Effort tiers** — `effort.json` records what was routed where and what it saved.

[`scorecard.py`](../src/scorecard.py) reads all five at the end of every run, keeps *"could not be
measured"* strictly apart from *"changed nothing"*, and writes sentences like *"it did not earn that
cost; consider dropping the panel."* A harness that ships a mechanism to tell you to turn its own
features off is an unusual design choice, and it is the one we would most like to see copied.

The cross-run half is [`decisions.py`](../src/decisions.py): the control arm for "did taking this
edge pay?" is not "runs that did not take it" but **"runs that were offered it and declined"** —
which is the comparison that isolates the decision from the circumstances that produced it. Payoffs
are keyed on a comparability basis so a run cannot win by stopping early, and
[`inference.py`](../src/inference.py) derives the observation count needed for believability from the
family size rather than asserting a threshold.

### 5.4 A workflow graph whose guards are computed from the filesystem

Agentic workflow graphs are common. Two things here are not:

**The guards are evaluated against artifacts on disk, not against agent state.** `results_exist` is
a directory listing; `validity_chain` is a parse of `preregistration.json` and
`hypothesis_outcomes.json`. Which move is legal is therefore a property of what the run has actually
produced, and it survives a resume, a crash, a manual edit and a different model.

**A blocked move is handed to the agent with its blocking reason.** The useful thing to say is not
"you may go to 06" but "07 is closed because H2 has no verdict" — an agent that sees *why* writing is
closed routes to the analysis that opens it. This turns the guard set from a fence into an
explanation, and it is why the thirteen backward edges are usable at all.

Two smaller mechanisms fall out of the same idea. A revisit whose justification **repeats a reason
already on the path** is refused (`repeats_a_previous_reason`): going again on the same grounds is a
loop, not an iteration. And the archive, which learns from outcomes, is permitted to reorder edge
preferences but **never** to open a guarded edge, add an undeclared one, or remove one — the
component that learns is precisely the one that must not be able to weaken the correctness argument.

### 5.5 How this sits against the systems it is comparable to

Grounded in [the landscape study](researchclawbench-landscape.md), which recomputed the published
numbers rather than quoting them:

| | EvoScientist | ARIS Codex | MIRA | **AutoR** |
| --- | --- | --- | --- | --- |
| Bets the bottleneck is | accumulated capability | self-deception | premature convergence | **unwarranted claims** |
| Mechanism | skills + memory that compound | cross-model adversarial review | competing hypotheses, physical lab | **preregistration → adjudication → provenance, as validators** |
| Improvement loop | skill evolution | — | — | **backend-free, verdict-blind, drift-rejecting ratchet** |
| Self-measurement | — | integrity forensics | — | **per-feature control arm + run scorecard** |
| Human role | on-the-loop | `human checkpoint: false` | unspecified | **in-the-loop by default; seven of eight mechanisms cannot approve** |
| Dependencies | LangChain / LangGraph / DeepAgents | host coding agent | proprietary cloud | **stdlib only** |

ARIS's bet — that the executor grading its own work is the problem — is the closest to AutoR's, and
AutoR includes that mechanism ([`cross_reviewer.py`](../src/cross_reviewer.py)) as one of five
critics rather than as the thesis. The landscape study also records ARIS as the cautionary case: a
large, thoughtful scaffold that lands *below* the bare-harness baseline. Structure is not
self-justifying, which is the reason §2.5 exists.

---

## 6. Contribution

What a reader can take from this system, in descending order of how transferable it is.

1. **A working demonstration that scientific-method constraints can be enforced mechanically over an
   LLM agent.** Preregistration, decision rules, seed and dispersion requirements, hypothesis
   adjudication against files that exist, and claim provenance are all implemented as functions
   returning problem lists over a directory tree. None of them requires the model's cooperation, and
   none is a prompt. This is the part most directly reusable in another harness.

2. **A concrete answer to "how do you score a self-improvement loop without corrupting it?"** —
   score with something that cannot call a model, make the score blind to the conclusion, and then
   separately reject any round that moves the conclusion. The result is a loop that can improve the
   *work* and is structurally prevented from improving the *answer*.

3. **A pattern for shipping an optional mechanism together with its own control arm**, and a reader
   ([`scorecard.py`](../src/scorecard.py)) that reports the result in the direction that costs the
   author something. Five features do this today. The pattern generalises to any agentic feature
   whose value is asserted rather than measured.

4. **A stage graph whose admissibility is a function of the filesystem**, with blocked moves
   explained rather than hidden, revisit-reason deduplication, and a learning component that is
   structurally forbidden from weakening the guards it learns around.

5. **A typed information-flow layer for agent prompts.** Sixteen channels, each naming its producer,
   its consumers by stage slug, and a written rationale for every narrowing — with a test that fails
   a channel that withholds itself without an argument. It makes "what did this stage actually see?"
   a diffable topology instead of a reconstruction from `if` statements.

6. **A statistically literate archive.** Paired trials with an exact sign-flip p-value, the
   attainable-p floor printed beside it, an explicit `underpowered` label below six pairs, and a
   sample-complexity tool that says how many runs an edge needs before it is believable. This is
   apparatus, not evidence — see §7.

7. **A full-fidelity research run as an inspectable artifact.** Every prompt of every attempt, every
   reviewer verdict, every panel seat's dissent that lost, every routing refusal, every losing draft,
   and the ledger of why each was rejected. `evolution/` sits outside `workspace/` precisely so an
   export ships the answer and not the search.

8. **A documented negative result about benchmark scoring.** Judge choice is worth roughly sixteen
   points on ResearchClawBench: on one identical artifact set Opus scored 52.6 where the reference
   judge gpt-5.1 scored 46.0. A score carrying the wrong judge is not a smaller number, it is an
   incomparable one — and a scorer that records a judge parse failure as `0` will quietly turn a
   working run into a broken-looking one. See [researchclawbench.md](researchclawbench.md).

---

## 7. What has not been established

Stated as plainly as the rest, because a system built to refuse unwarranted claims should not make
any.

- **No mechanism in AutoR has evidence that it improves a research output.** Not the panel, not the
  ideation lenses, not the crux deliberation, not the graph, not the ratchet.
  [`trials.py`](../src/trials.py) is the apparatus built to produce that evidence and **no paired
  trial has been run**. The run scorecard says when a feature did not change a decision *within one
  run*, which is a genuinely weaker claim than "it does not help".
- **The archive has not learned anything yet.** It records every run, and it proposes variants, but
  the shipped archive holds no paired trials and the sample-complexity tool exists precisely because
  the observation counts are not there yet.
- **The benchmark number is one task of forty.** 46.0 on `Astronomy_000` under the reference judge
  is a real measurement of a real run, and it is not comparable to a 40-task leaderboard mean. The
  landscape study's first conclusion also stands: model choice dominates harness choice, and any
  result must be quoted against the same-model bare-harness baseline.
- **The frozen preregistration is not checked against itself.** `validate_preregistration` compares
  the *manifest's* digest to the recorded `source_digest`; it never recomputes the digest of the
  frozen file. Editing `preregistration.json` in place passes. The honest claim is that a manifest
  rewrite is detected.
- **Standing rules and obligations never reach a panel seat.** Both are injected only into the solo
  reviewer's prompt, so `--review-panel` silently loses two of the accumulation mechanisms.
- **The cross-model veto is unreachable from `main.py`.** It is wired on the `rcb_agent.py` path
  only.
- **A crashed adversarial reviewer is indistinguishable from a clean result.** `reviewer_failed:
  true` is written and nothing reads it.
- **The chain is bypassable in unattended mode.** A stage that burns its five attempts against the
  gate is auto-skipped, up to three per run.

Each of these is also a specific next thing to build, named at the code that would have to change.
The list is maintained in the README's [Limits](../README.md#limits) section and is meant to shrink.

---

*AutoR is proprietary software; see [LICENSE](../LICENSE). Copyright © 2026 Xiangru Tang.*
