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
6. [The system measured against itself](#6-the-system-measured-against-itself)
7. [Contribution](#7-contribution)
8. [What has not been established](#8-what-has-not-been-established)

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

### 1.1 Why the controller has to be a graph

A validator is a function of the state it is called on. That makes the second half of the problem a
question about *where it is called from*, and this is the half most harnesses do not have a
vocabulary for.

Almost every autonomous research system in the current literature is a **loop**: plan, act, observe,
repeat, until a budget runs out or a stopping heuristic fires. The engineering goes into making each
turn better — better tools, better prompts, better memory, better search inside a step. The loop's
only control state is which iteration it is on.

Research is not shaped like that. An analysis finds that the experiment answered a different
question than the one asked. A draft finds that a claim has no result behind it. An unplanned result
turns out to be worth more than the planned one. Each is a move *backwards*, and a loop cannot
express one: its response to "Stage 06 shows the design was wrong" is to write up the wrong design
more carefully.

So the object being controlled is not an iteration counter but a **stage**, and the relation between
stages is a directed graph the run navigates rather than a sequence it walks
([`stage_graph.py`](../src/stage_graph.py)). Nodes are stages, edges are the moves allowed between
them, guards are functions over artifacts on disk, and after each stage the run chooses an edge and
records why.

**What a guard is and is not.** A failed guard removes an edge from the *menu* the agent chooses
from; it is not an absolute barrier. When nothing forward is live, `default_move` advances anyway,
and says why in its own docstring: *"A guard is a routing preference, not a correctness gate — the
correctness gate is the stage's own validation."* Treating a failed guard as a barrier would mean a
run that genuinely cannot satisfy it bounces between backward edges until its visit budget runs out
and halts with nothing, where the linear pipeline would have produced a deliverable and failed the
stage gate honestly. So the graph **orders and explains**; `validate_stage_artifacts` at the target
stage **refuses**. Anywhere this document says a move is impossible, read: not offered to the agent,
and taken by the default only when there is no alternative.

The two halves of the problem are the same problem, and §6 is the episode that showed it:

> **A warrant gate is only as good as the set of nodes it is reachable from.** A check that refuses
> unwarranted claims, placed at a node an unwarranted run never reaches, refuses nothing. Rigour is
> therefore a property of the topology and not only of the checks — which is the argument for making
> the controller an explicit graph rather than a loop with conditionals in it.

---

## 2. The design commitments

Seven commitments determine most of the architecture. Each one is a decision that could have gone
the other way, and each one costs something. Six were designed; the seventh was derived from a
failure, which is the most credible provenance a design rule can have.

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

**"Cannot influence" was too strong, and an adversarial read of this section found where.** The
criteria are individually sound and the *composition* was not. `quantification` counts numbers in
Key Results; `numeric_fidelity` checks each against an artifact the draft did not write. Scored
independently and summed, a draft quoting six invented metrics collected the first and merely
failed to collect the second:

| Key Results says | quantification (w 2) | numeric_fidelity (w 3) | weighted, of 5 |
| --- | ---: | ---: | ---: |
| "the method works better" | 0.00 | 0.00 | 0.0 |
| six numbers, nothing to check them against | 1.00 | 0.00 | **2.0** |
| six numbers, all traceable | 1.00 | 1.00 | 5.0 |

So inventing numbers was worth two weighted points more than honestly reporting none, on the total
the champion ratchet promotes by — the automated p-hacking this module's docstring says the design
exists to prevent, reached by a route the design did not consider. Declining to *reward* a
fabrication is not the same as declining to *pay* for it. `_cap_quantification_by_fidelity` now caps
the first criterion at the second wherever both apply, which makes the middle row 0.0; the cap is
recorded in `observed` so a stage can still tell which half to fix, and Stage 04 is exempt because
fidelity does not apply before there are results. `RUBRIC_VERSION` is `3`, so no score from before
the change is ranked against one after it.

1,842 tests passed before the fix and none of them failed after it: the hole was in a composition
nothing asserted over. The four tests added with it are mutation-checked — they fail when the cap is
removed.

*Cost:* the rubric can only measure what is mechanically checkable, so it is blind to whether the
idea is any good.
*Why anyway:* a self-improvement loop scored by a model develops a taste for whatever that model
likes. Removing the incentive (verdict-blindness) and then removing the possibility (drift
rejection) is belt and braces, on purpose: the failure it prevents — a loop that improves its
*answer* rather than its *work* — is the one that would be hardest to detect after the fact. The
episode above is the honest qualifier on that: the guarantee is only as good as the arithmetic that
combines the criteria, and it took an adversarial read rather than a test to find it.

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

AutoR's runtime imports nothing that is not in the Python standard library. The runtime is 53
modules and ~31 k lines; with the test suite the tree is 151 files and ~63 k lines, and 1826 tests
run in ~69 s with no install step. The MCP web-search server
([`mcp_web_search.py`](../src/mcp_web_search.py)) is a stdlib JSON-RPC 2.0 implementation over stdio
rather than an SDK. `google-genai` is needed only by three optional paths (`--web-search gemini`,
`--cross-review`, `--research-diagram`), and each degrades to a recorded *unavailable* rather than a
crash.

*Cost:* some wheels get reinvented.
*Why anyway:* a research harness that cannot be run five years from now cannot be used to reproduce
anything, and a dependency tree is the most common reason a scientific artifact stops running.

### 2.7 A gate an unattended run cannot satisfy must disclose, not refuse

The seventh was not designed. It was derived from the failure in §6, and it is kept here with the
six because it constrains the architecture the same way they do.

A guard is a repair instruction: it says what would make the move legal. The validity chain's repair
is *go back and adjudicate the hypotheses* — a rollback. An unattended run whose budget is spent
cannot perform a rollback, so for that run the guard states no repair at all, and a refusal whose
repair is unaffordable is not a gate; it is an exit under another name. Eight of forty benchmark
runs took that exit and published 197 bytes.

> **The discriminating test is whether the repair is in-stage.** If the only repair is a rollback
> the run cannot afford, the gate is a trapdoor, and what the run owes is *disclosure* — name the
> stages that did not happen, in the deliverable — rather than silence plus a non-zero exit code.

*Cost:* one guard is now bypassable by construction, and the honesty of the run rests on a banner in
a report rather than on a refusal in code. That is strictly weaker.
*Why anyway:* the alternative is not a stricter system, it is the same refusal with the evidence
thrown away. §8 keeps this on the list of things a reviewer should push on.

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
an abandoned round finish from Stage 06. `--stage-graph linear` is nine edges: the eight-step
sequence plus that same abandoned-round terminal, which both topologies carry because refusing to
write up an abandoned round is a correctness property rather than a routing preference. What
`linear` turns off is the six forward guards and the thirteen backward edges.

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

53 runtime modules, ~31 k lines. Grouped by what they own rather than by directory.

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

**The claim, narrowed until it is defensible.** "Research is not linear" is too coarse to survive
review, and three neighbouring ideas are established prior art. All three are conceded here by name,
because the version of this claim that ignores them does not survive one reviewer:

- **Branching search inside a stage.** The AI Scientist v2 does tree search over candidate
  experiments; EvoScientist does idea tree search in its first stage and experiment tree search in
  its second. Neither is linear *within* a stage.
- **Closed-loop feedback between stages.** NovelSeek is subtitled "Building Closed-Loop System from
  Hypothesis to Verification"; InternAgent describes itself as a closed-loop multi-agent framework.
  Feedback from a later step to an earlier one is not new.
- **A state graph as the LLM controller.** This is the one that bites. **StateFlow**
  ([arXiv:2403.11322](https://arxiv.org/abs/2403.11322)) models task-solving as a state machine in
  which "the transitions between states are controlled by heuristic rules or decisions made by the
  LLM", which is very close to the arrangement described in §1.1. LangGraph's
  `add_conditional_edges` is the same idea as a library. And the whole scientific-workflow tradition
  — make, Snakemake, Nextflow, Airflow, Pegasus — has computed admissibility from predicates over
  files on disk for decades. **A graph controller whose transition predicates are evaluated in code
  is not a contribution**, and this document previously claimed it was.

What survives is not the graph. It is what the predicates are *about*:

> Existing workflow graphs put **data-dependency and freshness** predicates on their edges: does
> file X exist, is it newer than Y. Existing agent state machines put **heuristics or LLM judgement**
> on theirs. AutoR puts **scientific-validity** predicates there — a frozen preregistration whose
> digest matches its source, exactly one verdict per preregistered hypothesis, every verdict citing
> an evidence path that resolves to a file, every manuscript claim traced to a supported hypothesis
> or labelled exploratory. The contribution is the predicate vocabulary and the fact that it is
> evaluated from the filesystem rather than from the transcript — not the existence of the graph.

Under that narrowing the honest one-line claim is *"scientific-validity predicates as edge
conditions in an agent workflow graph"*, and §6 is where it is tested rather than asserted.

**The foil, stated accurately.** EvoScientist's runtime does hold a LangGraph object: `deepagents`'
`create_deep_agent` returns a `CompiledStateGraph`. But that is an *agent-execution* graph — the
tool-calling loop — and it is composed by a library rather than authored. EvoScientist's *research*
stages are a six-step workflow living in a prompt string, whose only non-linear affordance is a
checkpoint asking a planner agent to emit a JSON plan update with `stage_modifications` and
`new_stages` fields, both of which appear only in `prompts.py` and `subagents/planner.yaml`. The
distinction worth drawing is therefore not graph-versus-no-graph but **agent-execution graph versus
research-stage graph**: nothing in the former can express "the analysis invalidated the design", and
nothing about it is inspectable as a topology.

The same narrowing applies to the improvement half. EvoScientist's critique axis is cross-run
memory — "static execution pipelines … accumulated outcomes and failures are rarely distilled into
reusable experience". That bet is *unmeasured on this benchmark by anyone*, including its strongest
advocate: its two leaderboard entries (0.0.4 at 15.47, 0.1.1 at 18.76) differ by release, not by
evolution state — both predate every memory feature it ships, which arrive in v0.1.7 through v0.2.1
— and ResearchClawBench isolates tasks, so cross-task memory has no channel to express itself
through by construction. That is the reason AutoR spends its complexity budget on stage control
rather than on memory, and it is an argument from their evidence rather than from preference.

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

## 6. The system measured against itself

Everything above is design. This section is the one place the design was put on a benchmark it does
not control, and it did badly. The episode is included in full because it is the strongest evidence
either way: it is what §1.1's claim about topology was derived from, and it is also the sharpest
objection to it.

### 6.1 The measurement

[ResearchClawBench](https://github.com/InternScience/ResearchClawBench) hands an agent a workspace of
raw data and reference papers, lets it work unsupervised, and scores the resulting
`report/report.md` against the original published paper with a multimodal judge. 40 tasks, 154
weighted criteria, 0–100 each, where **50 means as good as the paper being reproduced**. Images
carry 60.6% of total weight. It gives no credit for process, which makes it a hard test of a system
whose thesis is about process.

40 tasks, one attempt each, Claude Opus executing and reviewing, scored with the benchmark's own
reference judge `gpt-5.1`. Three comparison agents re-scored from their public runs under the
identical judge:

| agent | mean | median | max | tasks scoring 0 |
|:---|---:|---:|---:|---:|
| Codex CLI | 19.53 | 17.73 | 48.40 | 2 |
| ResearchHarness (GPT-5.4) | 15.40 | 10.85 | 45.10 | 1 |
| ARIS Codex | 15.02 | 12.65 | 46.90 | 2 |
| **AutoR** | **14.16** | 11.50 | 47.70 | **7** |

Last, below the bare Codex CLI it can be configured to run on top of. §2.5 exists because structure
is not self-justifying; this is that principle applied to the whole system.

### 6.2 What the deficit was made of

| stratum, by what the report *is* | n | AutoR mean | the other three, same tasks |
|:---|---:|---:|---:|
| 197-byte "incomplete run" stub | 8 | **0.78** | 18.99 |
| Stage-01/02 dump | 10 | 12.88 | 12.17 |
| paper-shaped report | 22 | 19.61 | 17.84 |

Eight runs shipped a 197-byte stub reading `_No completed stage output was produced._`, each
reporting `exit_code: 0, status: completed`; one spent 6,150 seconds doing it. The tasks are not
hard — the other three agents average 18.99 on those same eight.

**The 19.61 is a post-hoc subgroup mean and is not AutoR's number.** Only the 40-task mean counts,
and quoting a subgroup as a result would be exactly the move §2.4 and §5.2 exist to prevent the
system from making about itself.

**It is also weaker than it looks, in a way worth spelling out.** The strata above are cut by what
the file *looks like*, not by what produced it. Cutting instead by where the walk actually stopped
(`evolution/stage_graph.json`, §6.6) gives a different picture:

| task | score | terminal stage |
|:---|---:|:---|
| Astronomy_003 | 47.70 | `02_hypothesis_generation` |
| Physics_002 | 45.45 | `02_hypothesis_generation` |
| Astronomy_001 | 34.80 | `03_study_design` |
| Earth_002 | 32.90 | `02_hypothesis_generation` |

**AutoR's two best scores on this benchmark came from runs that never designed a study, never ran an
experiment and never analysed a result.** Those reports were assembled by the benchmark adapter's
synthesizer (`src/rcb.py`) out of Stage 01–02 material. Five runs of forty reached Stage 05 or
later.

So the reading "the pipeline is capable and the deaths are the deficit" — which an earlier draft of
this section made, and which `docs/researchclawbench.md` repeated — **does not follow, and is
withdrawn**. What 19.61 measures is a *legible* subgroup, not a correct one, and much of what it
measures is the adapter's fallback path rather than the eight-stage pipeline this document is about.

### 6.3 Four defects, all of them topological

**The graph had no terminal edge.** Thirteen backward edges, six guarded forward ones — and every
way a stage could fail *terminally* was `return False`: the auto-skip budget running out, and an
abort at the approval gate. A `return False` is not an edge; it is the absence of one, and the
runtime expresses that as process exit. On eight of forty runs the only reachable terminal state was
`sys.exit`, and a run holding 18 KB of survey and five rendered figures published 197 bytes. What
this document calls a graph was, on a fifth of the benchmark, a linear pipeline with a retry loop
and two trapdoors.

**The router had never read the research question.** `user_input.txt` is excerpted by four callers,
each taking a *prefix*. Measured over all 40 shipped tasks:

| reader | budget | characters of the research question it saw |
|:---|---:|:---|
| the router that chooses the next move | 2,500 | **0** |
| the deliberation panel | 3,000 | **0** |
| the adversarial validity reviewer | 3,000 | **0** |
| the report synthesizer | 8,000 | 331 of ~5,000 — median 6.9% |

The benchmark adapter had grown a grading contract in front of the task, and nothing noticed,
because what a prefix reader sees is decided by what goes first and no test looked.

**The check that should have caught it was reading AutoR's own prose.** `deliverables.py` compares
the deliverable against what the task asked for by finding sentences that ask for something. Given
the wrapped goal it found **857 demands across the 40 tasks where the tasks contain 337** — 520
phantoms, 61%. The first requirement enumerated to the stage was `Benchmark Run: ResearchClawBench`.
It is also gated at `stage.number >= 7`, which puts it topologically downstream of the failure it
exists to catch.

**The improvement loop was running open-loop.** This is the one that bears on §2.4. The rubric's
eight criteria cost nothing and are read off disk — and **zero of the benchmark's 154 checklist
items measures any of them**. Two runs of one task:

| internal rubric | benchmark score |
| --- | ---: |
| 0.998 – 1.000 | 9.6 |
| 0.983 – 1.000 | 46.0 |

Roughly 17% of every run's wall clock went to hill-climbing a metric already at ceiling on the first
draft. Improving a quantity uncorrelated with the objective is not self-improvement; it is a fixed
point advertised as a gradient. §2.4's commitment — score with something the loop cannot influence —
is satisfied, and this is its price: a measure the loop cannot influence is also a measure that can
fail to point anywhere.

### 6.4 The worst case, in full

`Chemistry_003` scored **0.0** with a 27,826-byte report and six rendered figures. The report is
good. It opens:

> This run was terminated after its first stage. **No machine-learning interatomic potential was
> trained, and no model-accuracy number is reported anywhere below.**

and delivers a rigorous audit of the input data, finding three real defects in the supplied
datasets — including two files that are bit-identical where the task requires them to differ. Its
Section 6 enumerates every criterion it did not meet. Every honesty mechanism in this document fired
exactly as designed. The rubric scored it 1.000. The judge scored it zero, correctly, because the
task asked about latent-charge recovery and force MAE and the report does not attempt them.

Stated in its strongest form against the thesis: a graph that can route backwards but cannot route
*toward its deliverable under a budget* has not earned the word. Stated for it: "the node holding
the quality control is unreachable from the failure mode it targets" is a sentence about topology,
and a system without an explicit topology cannot say it, let alone repair it.

### 6.5 What changed, and the rule it produced

Landed as [#180](https://github.com/tangxiangru/AutoR/pull/180) and
[#181](https://github.com/tangxiangru/AutoR/pull/181):

| defect | change |
|:---|:---|
| no terminal edge | `_route_to_deliverable` makes the writing node reachable from any node under one predicate — *the budget for doing more research is spent and the deliverable node has not been visited*. The node still runs its own gates; when it too exhausts, the run aborts as before. |
| the question was last | the goal emits the task second, and `goal_excerpt` returns the fenced task and truncates from the tail |
| phantom demands | `task_statement()` unwraps the goal at all four `deliverables` call sites |
| five routes to the stub | synthesis judged on the file not the exit code; the fallback re-reads before overwriting; `stages/<slug>.tmp.md` as last-resort recovery; the skip-rescue passes the arguments the real gate passes; `exit_code` reads content, not `.exists()` |

The terminal edge bypasses the validity-chain guard deliberately. It is not the only bypass in the
system — `default_move` advances across a failed forward guard as a last resort (§1.1), and on this
benchmark that path decided the route far more often than this one did — but it is the only one
taken *knowingly*, and the reasoning behind it generalised into §2.7, the seventh design commitment,
which was derived from this failure rather than designed.

Two smaller things worth recording precisely, because both are easy to overstate. The terminal edge
is not an edge in `stage_graph.py`: `git diff` over that file is empty for #181, and
`_route_to_deliverable` is a method on the manager that sets `_jump_target_stage` and is recorded on
the route with `bypassed=True`. And it is a *route*, not a relaxation — the writing node still runs
every gate it always ran.

**The effect of these changes is not yet measured.** A 40-task re-run at the repaired HEAD is in
flight. Until it lands, §6.5 is a description of code, not a result, and no claim in this document
rests on it.

### 6.6 The finding that most constrains what this document may claim

§6 is titled "the system measured against itself". It is worth being exact about *which* system was
measured, because it was not the one §1.1 describes.

Every run writes its route to `evolution/stage_graph.json`. Across the 50 route files the batch left
behind — 133 stage visits:

| | |
|:---|---:|
| visits | 133 |
| moves recorded as `advance` | 82 |
| moves recorded as `revisit` | **1** |
| visits where more than one move was on offer | 27 |
| visits where a blocked move was shown to the agent with its reason | **2** |
| visits where the agent, not the default, chose the move | **4** |

And where the runs stopped:

| terminal stage | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| runs | 12 | 14 | 15 | 4 | 1 | 3 | 1 | **0** |

`run_status` across the same manifests: 46 `cancelled`, 4 `running`, 3 `human_review`, **0
completed**.

So: **the thirteen backward edges that are "the reason the graph exists" were taken once in the
entire batch, and the mechanism §5.4 calls the one that makes them usable — a blocked move handed to
the agent with its blocking reason — fired twice.** Forty-one of fifty runs halted at or before
Stage 03. On this benchmark the adaptive graph produced a walk that was, in every respect a
`--stage-graph linear` run would also have produced, linear.

Three consequences, and none of them is optional.

1. **§6 does not test the thesis.** It measures a system dying early, and a system dying early is
   exactly the case in which topology cannot matter — there is nothing to route about at Stage 02.
   The four defects in §6.3 are real and were worth fixing, but they are defects in the *floor*, and
   the paper's claim is about the *ceiling*.
2. **Most of the validity chain never ran either.** `validate_preregistration`,
   `validate_hypothesis_outcomes`, `validate_outcome_statistics` and `validate_claim_provenance` are
   gated at Stage 05, 06, 06 and 07. Five runs of fifty reached Stage 05 or later. The predicate
   vocabulary that §5.4 now claims as the contribution is, on this evidence, almost entirely
   untested.
3. **The control arm ships and was never run.** `--stage-graph linear` is one flag. Nothing in the
   40-task batch passed it; every `run_config.json` says `"stage_graph": "adaptive"`. Comparing
   against three other people's systems varies model, prompt, scaffolding and budget at once and
   cannot isolate topology — and it is additionally confounded, because all three comparison agents
   run GPT-5.4 while AutoR ran Claude Opus, so §6.1 reports a cross-model difference as a harness
   result.

**The experiment this document owes.** Same model, same judge, same 40 tasks, `--stage-graph
adaptive` against `--stage-graph linear`, paired, with enough seeds to say something. It is not run
here because its outcome is currently predetermined: a graph that produced one revisit in 133 visits
cannot differ from a linear walk. The repairs in §6.5 are the precondition — they are what lets a
run reach a stage where a routing decision exists — and the ordering is therefore repair, re-measure,
*then* ablate. Until that ablation lands, the correct summary of this document is:

> A system whose stated contribution is a topology has demonstrated that the topology is
> inspectable and that four defects in it were findable **because** it is inspectable. It has not
> demonstrated that the topology helps.

---

## 7. Contribution

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
   apparatus, not evidence — see §8.

7. **A full-fidelity research run as an inspectable artifact.** Every prompt of every attempt, every
   reviewer verdict, every panel seat's dissent that lost, every routing refusal, every losing draft,
   and the ledger of why each was rejected. `evolution/` sits outside `workspace/` precisely so an
   export ships the answer and not the search.

8. **A documented negative result about benchmark scoring.** Judge choice can move a score by more
   than the gap between the top and the bottom third of the leaderboard. On one identical artifact
   set Gemini 2.5 Flash scored 37.0 where Opus scored 20.8, a spread of 16.2; on another, Opus
   scored 52.6 where the reference judge gpt-5.1 scored 46.0, a spread of 6.6. A score carrying the wrong judge is not a smaller number, it is an
   incomparable one — and a scorer that records a judge parse failure as `0` will quietly turn a
   working run into a broken-looking one. See [researchclawbench.md](researchclawbench.md).

---

## 8. What has not been established

Stated as plainly as the rest, because a system built to refuse unwarranted claims should not make
any.

- **We make no efficacy claim for any individual mechanism.** Not for the panel, the ideation
  lenses, the crux deliberation or the ratchet. What §7 claims is mechanism *design* — that these
  constraints can be enforced from the filesystem at all — and §6 supplies a diagnostic result, not
  an efficacy one.
  [`trials.py`](../src/trials.py) is the apparatus built to produce that evidence and **no paired
  trial has been run**. The run scorecard says when a feature did not change a decision *within one
  run*, which is a genuinely weaker claim than "it does not help".
- **The archive has not learned anything yet.** It records every run, and it proposes variants, but
  the shipped archive holds no paired trials and the sample-complexity tool exists precisely because
  the observation counts are not there yet.
- **The benchmark number is 14.16, and it is last.** §6 is the full account. Three things travel
  with it and none can be dropped: it is **single-attempt** where the public leaderboard aggregates
  the *best* score per (task, agent) pair, so the two are not comparable in either direction; it is
  a `gpt-5.1` number, and judge choice has been measured to move a score by up to 16.2; and it is
  **cross-model** — all three comparison agents run GPT-5.4 where AutoR ran Claude Opus, so the
  table is not a clean harness comparison and the same-model baseline the landscape study calls
  mandatory has not been run; and it is the **pre-repair**
  batch, so the effect of #180 and #181 is unmeasured. The landscape study's first conclusion also
  stands: model choice dominates harness choice, and any result must be quoted against the
  same-model bare-harness baseline.
- **No mechanism in §6.5 has been measured.** The re-run is in flight. Until it lands, the correct
  reading of this document is that a system with a stated topology found four topological defects in
  itself and repaired them, and that the repair is unevaluated.
- **The rubric may not point at anything.** §6.3 is a two-point observation — internal rubric
  0.998–1.000 scoring 9.6, and 0.983–1.000 scoring 46.0 — against a benchmark none of whose 154
  criteria measures any of the eight. That is enough to refuse the claim that the ratchet improves a
  benchmark score. It is not enough to quantify the relationship, and it does not establish that the
  rubric is measuring nothing: rigour and rubric-coverage are different objectives, and §2.4 chose
  the first deliberately. What it does establish is that the second is not a corollary of the first.
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
- **The chain is bypassable in unattended mode, and now deliberately so.** A stage that burns its
  attempts against the gate is auto-skipped, up to three per run; past that the terminal edge routes
  to the writing stage *around* the validity guard (§6.5). The bypass used to be an accident of the
  retry budget and is now a stated rule with a disclosure obligation attached, which is an
  improvement in honesty rather than in strictness. Whether the disclosure is enough is exactly the
  kind of thing a reviewer should push on.

Each of these is also a specific next thing to build, named at the code that would have to change.
The list is maintained in the README's [Limits](../README.md#limits) section and is meant to shrink.

---

*AutoR is proprietary software; see [LICENSE](../LICENSE). Copyright © 2026 Xiangru Tang.*
