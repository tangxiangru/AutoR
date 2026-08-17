# A Round Loop and a Stage Graph

*Design notes for the AutoR framework paper. AMAP-ML's
[LongHorizon-Harness](https://github.com/AMAP-ML/LongHorizon-Harness) attacks the same
problem AutoR attacks — keeping an agent on one goal for hours — with a different shape.
This document reads that system against ours and records what is worth taking, what is
not, and why. Everything attributed to either system was read in its source; the
LongHorizon-Harness half is pinned at commit `fd1797b` (2026-08-12) and the AutoR half at
the tree this document lands in. Where a claim is unverified it says so.*

---

## 1. Why this comparison is worth writing down

LongHorizon-Harness ("LHH") is a durable execution loop that wraps an existing coding or
computer-use agent — Claude Code, Codex, OpenCode, `dsh` — and drives it for many hours.
Its thesis is the one this repository also holds: *the model decides what an agent can do
in one turn, and everything that breaks a long task is around the turn.* It publishes
gains on three benchmarks with the backbone and the execution backend held fixed and only
the harness changed (WeaveBench pass rate 51.8 → 80.7; OSWorld 2.0 binary 2.8 → 8.3;
Terminal-Bench 2.1 success 69.7 → 77.2 with 24% fewer tokens). Those are their numbers,
measured on their tasks; nothing here reproduces them, and nothing here needs to. The
reason to read the system is that it is a second, independent answer to *what state a
harness must carry between steps*, and the places where the two answers disagree are the
places where one of them is missing something.

The disagreements are not evenly distributed. On composition — undo, staleness,
attribution, backtracking — AutoR is a generation ahead, and §3 says so with the evidence.
On the *discipline of a single step* — who may write, what a verdict is, what the next
step is allowed to see — LHH holds four positions this repository has never taken, and two
of them expose defects that are live in the tree today.

---

## 2. The two shapes

|  | LongHorizon-Harness | AutoR |
| --- | --- | --- |
| Topology | one loop, rounds until done | eight stages, guarded edges, thirteen backward moves |
| Who picks the next step | a planner emits one of five route words, parsed by string match; no precondition on any transition | code computes the admissible menu from filesystem guards, the agent picks from it, an off-menu answer degrades to the forward default and the refusal is recorded on the `Visit` |
| Roles | manager / executor / auditor / final-response, each a separate adapter and model | doer and reviewer, each a separate CLI process; optional panel, cross-family veto, validity review |
| A step's process | one fresh one-shot process per role episode; `--resume` and `--continue` appear nowhere in the tree | one process per attempt, continued within a stage by `--resume` on a per-stage session id |
| Carried state | two model-authored prose blocks (`task_state`, `task_contract`) rebuilt every round from the audit reports | twenty typed channels rendered per consumer, a monotone evidence ledger, a manifest, a provenance ledger with per-write inverses |
| Verdict | a three-line control header — status, integrity, contract audit — parsed out of prose | a rubric score per criterion, a reviewer decision, obligations, validity findings |
| Recovery | none: `resume` mints a new run id and re-runs the task from an empty history | `--resume-run` rehydrates `GraphState`, the manifest, counters, champion and session id |

The row that explains most of the rest is the third: **LHH pays for a fresh process on
every step and therefore has to be able to reconstruct the whole working state from disk.**
AutoR continues a session and therefore never had to. That is a real engineering saving and
it is also the reason four of the six findings below exist — a harness that never
reconstructs its state does not find out which parts of it are unreconstructable.

---

## 3. Where the stage graph is already ahead

Recorded because a comparison that only lists gaps is an argument, not a reading.

**Resume.** LHH writes `rounds.jsonl` as one `asdict(ManagedRound)` per line and never
reads it back to rebuild a loop. `_resume_once` mints a new run id, re-runs the saved task
from an empty history, and stamps the owner record `resume_kind: "retry"`. The README's
architecture calls the per-round write a checkpoint; the code has no path that resumes from
one. AutoR persists `GraphState` on every `enter` and every `leave` and re-enters at the
first unsettled manifest entry.

**Undo.** LHH restores nothing. The one snapshot it takes (§4.1) is used to *detect* that a
read-only role wrote, and the metadata key that would announce a restore is a hardcoded
`False`. AutoR holds per-write inverses as JSON, a content-addressed blob store, a version
chain per artifact, and an ordered recovery plan.

**Whether going back helped.** LHH has no per-node score and no notion of an excursion; a
revisit is another round and "later" is the only ordering it has. `walk_ratchet` rewinds an
excursion that measured worse.

**A step that dies does not kill the run.** In LHH a per-episode timeout is classified as a
terminal provider failure: the round is recorded with the executor output deliberately
blanked and the loop breaks, so a 30-minute overrun on round 7 of 25 ends a multi-hour run
as `failed` with an empty final response. AutoR has four escalating recovery layers and
then an exhaustion ladder.

**Cost of durability.** `_append_event` re-reads the entire event log on every append to
compute a sequence number, while holding an exclusive `flock`, and the whole round record
is one of those events — quadratic in bytes over a run. AutoR's manifest transition is a
read-modify-write of one document, written atomically.

None of this is a reason to stop reading. It is the reason to read only the step
discipline.

---

## 4. What is worth taking

Six items. Each states the LHH mechanism, what AutoR does today, the gap *after* an
adversarial pass that tried to show AutoR already had it, and the change in AutoR's own
vocabulary. Ordered by what they buy.

### 4.1 A verifier that wrote to the workspace cannot approve it

**LHH.** The auditor role is denied the write tools, and the denial is not trusted.
`snapshot_workspace` walks the workspace before the auditor episode and after it, recording
kind, mode, size, mtime and a SHA-256 digest of every file under a size limit;
`workspace_snapshot_diff` compares them. A difference sets
`verifier_workspace_mutation_detected`, and `audit_report_from_episode_result` then prepends
a harness-authored `Status: blocked / Integrity: violation / Contract audit: unknown`
header, appends the changed paths, and states that the report's claims are invalid. The
whole report is demoted, not annotated — a verifier that acted is not a verifier whose
findings you keep. One narrow exception survives: a deletion the auditor *declared* and the
diff confirms is reconciled rather than demoted.

**AutoR today.** Reviewers are the full Claude CLI. `approval_agent` and `validity_review`
both go through the operator's own invocation path, which hardcodes `bypassPermissions` and
`--dangerously-skip-permissions`, always mounts the `mcp_write` server, and sets the working
directory to the run root. `--disallowed-tools` is populated only from the web-search
module and is never conditioned on the role. *"Do not edit files. Inspect and judge."* is
prompt text. `observe_artifacts` runs at exactly three sites — intake, approval, skip —
none of them around a review, so a file a reviewer writes is observed at the next boundary
and attributed to **the stage the reviewer just approved**; and `mcp_write` stamps every
write with the manifest's current stage slug regardless of which process called it.

**What survived the adversarial pass.** Almost all of it. Two partial equivalents exist and
deserve credit: `rubric`'s `_harness_written_records` denies artifact credit to an
enumerated set of harness- and reviewer-authored paths, and `validity_review_tamper` is a
real stamp-versus-disk content diff. Neither closes this. The first is a fixed allowlist —
a reviewer writing `workspace/results/x.json` is not on it and clears both the directory
whitelist and the mtime test — and the second covers one document and guards the *executor*
rewriting a review, which is the opposite direction.

**The change.** A census around every verifier episode, and a demotion rule keyed on it.
Two corrections the design has to carry:

- **Root it at the run root, not at `workspace/`.** `_walk_workspace` starts at
  `workspace/`, but the reviewer's working directory is the run root, so a
  `workspace/`-rooted census cannot see a reviewer editing `stages/<slug>.md` — the draft
  under judgement — or `run_manifest.json`, `memory.md`, `artifact_index.json`. The census
  needs the run root with an explicit exclusion for what the harness itself churns during
  the episode: `logs.txt`, `logs_raw.jsonl`, `prompt_cache/`, `operator_state/`.
- **Do not route the record through the actor being distrusted.** An obligation is
  reviewer-authored by contract, so recording a reviewer's mutation as an obligation asks
  the suspect to file the report. It belongs on the review record the harness writes after
  the subprocess returns.

Deny the write tools as well, but the deny-list is not the mechanism — the census is. LHH's
own restore is advertised and never happens, and the demotion is the entire enforcement;
that is the part that works.

**Landed**, as `src/review_custody.py`, with two corrections the design did not survive
contact with.

*The census is over content, not modification time.* Replayed over 138 archived reviewer
episodes (`tools/review_custody_replay.py`, population pinned by name), an mtime census
fires on **138 of 138** with no exclusion list and **4 of 138** with one — and all four
are the same behaviour: the reviewer re-running the doer's producer scripts in place to
check they reproduce. Both of the two approvals among them say so in their own recorded
reason. A gate that fires hardest on the most rigorous reviewer is the wrong gate, so a
file whose digest is unchanged is recorded as `touched` and never charged.

*The demotion is armed by a flag and off by default.* `--review-custody` defaults to
`record`. The replay bounds the blast radius from above and cannot bound it from below:
an archive keeps one modification time per file, so how many of those four a content
census would also have caught is not answerable from disk. That is what the ledger is
for.

What it still cannot see is worth stating, because the reading that produced this
mechanism also produced the counterexample: in the same 138 episodes there are three
tool-level writes, and two of them go to a `~/.claude/projects/.../memory/` directory
far outside any run root. The census claims *"the reviewer changed nothing it was
judging"*, not *"the reviewer changed nothing"*.

*Class: design gap, and the largest here. Effort: medium.*

### 4.2 A promotion should carry the authority that granted it

**LHH.** A verdict the harness wrote is tagged as such and every reader branches on the tag.
When the planner emits an unroutable step or claims completion without a clean audit, the
harness synthesises a pseudo-audit, stores it under `auditor_status={'invalid_completion':
True}`, and renders it under a heading that says *not an audit; only for protocol
correction*. Both `_latest_auditor_is_clean_complete` and the latest-report reader skip
those rounds. The harness's own words can never be read back as an audit.

**AutoR today.** This discipline already exists here — for refusals.
`is_degraded_verdict` marks a verdict as AutoR's stand-in rather than a reviewer's
judgement, and three readers branch on it. It was never applied to promotions, and there is
one promotion path where that matters: when the send-back budget is spent,
`_sendback_is_out_of_budget` returns a reason and a **live reviewer refusal is rewritten to
an approval**. Downstream, the manifest records a plain approval, the stage-cost ledger
records the approved outcome with no note, the failure census deliberately does not charge
it, and the reviewer's demand is dropped because the rewrite happens before it would be
recorded. The only trace is one line in `logs.txt`.

**What survived.** The narrow half. The adversarial pass refuted the general claim: skip
paths *do* record authority (`skip_kind` is validated human-or-auto, a skip's promoted
markdown says the work was not accepted, and the stage-cost ledger has a nine-value outcome
vocabulary). What has no structured record anywhere is the overridden refusal, plus one
sliver: for an auto-skip that rescues the doer's own unreviewed draft,
`render_approved_stage_entry` emits no provenance line, so the next stage's prompt reads
that draft under *## Approved Stage Summaries* like any approved work.

**The change.** An override marker on the manifest entry — or a new stage-cost outcome kind
— set inside `mark_stage_approved_manifest` rather than at the call site, plus one
provenance line in `render_approved_stage_entry` so the prose carries what the manifest
carries. Resist the tempting second step: widening `unreviewed_stage_slugs` to cover the
override is **wrong**, because the overridden stage was read by a reviewer that scored every
criterion; calling its artifacts unreviewed conflates it with a stage nobody looked at.
That is a third state, not the second one.

*Class: record fidelity. Effort: small-to-medium.*

### 4.3 The terminal label is re-derived; ours is asserted

**LHH.** `Next: done` from the planner is not sufficient. The harness re-parses the most
recent *genuine* auditor report and requires three things at once — status complete,
integrity clean, contract aligned — before the run may end. Two downgrades run first: a
report with an integrity violation or a non-aligned contract has `complete` forced to
`incomplete`, and a report claiming complete while listing blocking acceptance constraints
is downgraded by `_apply_acceptance_constraint_guard`.

**AutoR today.** `_complete_run` already re-derives two of its three outcomes and argues for
it: `halted` comes from `halted_kind` plus the manifest's unsettled list, and `abandoned`
re-reads the abandonment record rather than the last round, with a comment explaining that a
later converged round would otherwise launder it. The third outcome is the default branch.
Because `settled` is `approved or skipped`, a run whose writing or dissemination stage was
auto-skipped reaches the terminal edge, takes that branch, writes `run_status: completed`
and logs **"All stages approved."** — a sentence that is literally false for a skipped
stage. The validity disclosure rides on the closing line, so the information exists; the
label contradicts it.

**What survived, and what the pass killed.** The pass killed the obvious version of this
change. A guard on the `08 → finish` edge contradicts three decisions this repository
already measured: a test pins that the forward gate must still count a skipped stage's
artifacts, because closing it would convert *this stage did not finish* into *the run
stops*; `_route_to_deliverable` bypasses the writing guards on purpose, on the argument that
a refusal whose only repair is unaffordable stops being a gate and becomes an exit; and
`default_move` deliberately excludes `finish` from its last-resort fallback. What survives
is the label, not the edge.

One number needs correcting before anyone quotes it in this argument. `unfinished_business`
records that guards refused 48 moves across 41 runs and 46 of them were `finish`. That is
**not** evidence that the exit is already guarded: `_advance_edges` keys its guards by
target and there is no `FINISH` key, so `08 → finish` carries `guard="always"` and can never
refuse. Every one of those 46 refusals is the *abandonment* terminal, `06 → finish` under
`round_abandoned`, being correctly shut. The blast radius of a real exit condition is
unmeasured, which is the argument for putting it on the label rather than on the edge.

**The change.** A fourth outcome in `_complete_run` — a distinct `run_status` when the walk
reaches the terminal with any stage skipped or any obligation still open — and stop emitting
"All stages approved." when they are not. This is LHH's actual insight (a terminal label is
derived, never asserted) applied at the site where AutoR already derives, and it costs no
edge.

While there: the obligation ledger is read by no deterministic decider at all. `grep
obligation src/stage_graph.py` returns nothing; obligations reach prompts, and `note_deferrals`
increments a counter with no ceiling and no reader that can refuse. An obligation that can
be deferred indefinitely with no reader is a debt with no creditor.

*Class: a record that overstates. Effort: small.*

### 4.4 A channel with no declared budget

**LHH.** `_clip_preserve` keeps 65% head and 35% tail with an inline marker naming the
dropped byte count, and `HarnessConfig` declares three ceilings that are actually wired —
auditor output, verified context, history. Per-round contributions are clipped
individually *and* the joined block is clipped again. Durably, every role episode records
`prompt_chars`, and the manager round records the sizes of the plan, the task state and the
task contract.

**AutoR today.** The pass refuted the strong version of this: AutoR does declare budgets,
with the same argument, in at least four places — the withdrawal ledger's prompt limit
("an unbounded block would grow until it crowded out the work the stage is being asked to
do"), settled reasoning's field and entry caps, the artifact index's per-category cap, and
the handoff's recency window. What is true is narrower and structural:

- `Channel` has no budget field and `render_inbound` concatenates whatever the builder
  returned, so a budget is a per-builder convention enforced nowhere and a new channel can
  be added with none.
- Two channels on the stage path are uncapped in both entries and characters: approved
  memory, which grows with every promoted stage and is passed through verbatim, and the
  concatenated decision ledger.
- `repair_stage_summary` interpolates the whole prior stdout, stderr, original prompt,
  draft and promoted file — while the same module caps stdout at 2000 characters for its
  *log* excerpt.
- There is no prompt-size telemetry at all. `_record_inbound_channels` records channel keys
  only; the size is inferable from `prompt_cache/` on disk and from nowhere in the record.
- No test references `truncate_text` or a `max_chars`.

**The change.** A declared `max_chars` on `Channel`, so the existing convention becomes
enforceable and a new channel has to state its budget; caps on the four uncapped stage-path
sites; and a per-stage prompt-size event, which is the LHH precedent worth copying. Two
things **not** to copy: a record of what the elision dropped (LHH does not have one — only
an inline marker in the prompt string), and any blanket swap of tail-drop for head-drop,
since two callers already implement the head-drop variant deliberately and one argues for
tail-drop on a goal.

*Class: design gap plus missing telemetry. Effort: medium.*

### 4.5 The contract is back-checked every round; ours is checked once, at the end

**LHH.** `task_contract` is a first-class object separate from both the plan and the state:
a stable semantic anchor that turns the request into a verifiable target state, with
acceptance constraints each carrying a source, a required condition, a verification method
and a blocking condition. It is maintained every round, it is forbidden from replacing the
request with an easier proxy, and — the part that matters — **the auditor back-checks the
contract itself**, returning `aligned | unknown | needs_revision | invalid` as its own axis.
The planner may not finish while that axis is anything but aligned.

**AutoR today.** The comparable object is stronger where it exists: `deliverables_coverage.json`
enumerates what the task demanded with *verbatim* quotes from the task statement, and
`validate_deliverables_coverage` refuses a quote that is not a verbatim span, a subset that
skips a demanding sentence, an addressed entry that does not say where, and an unaddressed
one with no reason. That is a machine-checkable contract where LHH's is prose.

It runs once. The validation sits under `if stage.number >= 7 and selected_output_format(paths)
== "markdown"`, so:

- a run discovers that it is not going to answer half the brief at the writing stage, after
  the experiments are done — the point at which the repair is most expensive;
- and a **latex run never checks coverage at all**. The condition predates the deliverables
  module: it was added by the change that made markdown the default report format, and
  coverage was later appended inside it. `validate_markdown_report` belongs there;
  "did the run answer what it was asked" has nothing to do with the output format. No test
  pins the latex behaviour either way.

`format_deliverables_for_prompt` does reach every stage on both prompt paths, so the
*contract* is delivered from the start. Only the check is terminal.

**The change.** Two separable moves. Lift `validate_deliverables_coverage` out of the
markdown branch — that one is a one-line correction with an argument, not a design. Then
give the coverage artifact an earlier writer and a reviewer axis: a stage-03 or stage-04
draft of the same JSON, delivered as a channel, and a reviewer question that asks whether
the plan still covers every demanding sentence. The stage that discovers a demand it cannot
meet at design time can still route backwards; the one that discovers it at Stage 07 cannot
afford to.

*Class: a check placed at the wrong end of the run. Effort: small for the branch, medium for
the channel.*

### 4.6 Carried refusal evidence — the machine-read half only

**LHH.** Every round's auditor report, including rejections, is rendered into the next
manager prompt tagged with its round id, under a heading distinct from the harness's own
feedback. A rejected result stays in the record as evidence and is never counted as
progress: the separation is by channel, not by deletion.

**AutoR today.** The doer-side half of this is already here and should stay refused. Within
a visit the doer carries every prior refusal in one continued session. Across visits,
`withdrawal_history` is a channel consumed by exactly the backward-edge targets, capped, and
its module argues the thesis verbatim: *the state goes back, the evidence does not.* And
there is a **measured adverse result** for feeding a stage its own accumulated refusals —
`review_policy` excludes rules whose origin stage is this stage, because doing otherwise
raised the bar by one requirement per attempt and prevented convergence.

What survives is machine-read, not prompt-read:

- `failure_census` and the closed rows' `attempt_digests` have no non-test reader anywhere
  in `src/`. The supervisor's `unchanging_failure` takes digests only from the *open* meter,
  so it cannot see that the identical failure already repeated on an earlier visit to the
  same node — which is exactly the run the supervisor exists to stop.
- The router prompt shows visits-to-node and the backward moves already taken, but never how
  many attempts that node has already refused. The figure is already computed.

**The change.** Have the supervisor read closed-row digests, and add an attempts-refused
figure to `describe_budget_for_prompt`. Do not add a `prior_refusals` doer channel. Note
also that `Visit.refusal` already exists with a different meaning — why the router's answer
was not used — so the new field needs a different name.

*Class: a ledger nobody reads. Effort: small.*

### 4.7 Retry state the harness owns, not state the provider owns

**LHH.** Each role episode is a fresh one-shot process against a per-episode prompt file;
`--resume`, `--continue` and `session_id` appear nowhere in its tree. Everything a step
needs is rebuilt from disk on every step, because nothing else could work.

**AutoR today.** Continuation is the right default here and the pass confirmed most of the
proposal was already implemented: a continuation prompt eagerly rebuilds the deliverables
block, the handoff context, the recovery context and the full typed channel set from disk.
Three things are not, and two of them are defects rather than design choices:

1. **Obligations vanish on every retry.** `obligations_context` is a parameter of
   `build_continuation_prompt`, it is passed by the manager, and it is never rendered in the
   body — the only occurrence in the function is the signature. The *## Obligations Carried
   Forward* block exists on attempt 1 and disappears from attempt 2 onward. Verified on the
   current tree.
2. **A second entry to a stage reuses a spent session id.** `_resolve_stage_session_id`
   returns a persisted, non-broken id regardless of `continue_session`, and the manager sets
   `continue_session=False` on every stage *entry* — a stage can be entered more than once,
   which is what the whole graph is for. The invocation then becomes
   `--session-id <already-used uuid>`, and the CLI answers `Error: Session ID <uuid> is
   already in use.` That string matches none of the four patterns in
   `_looks_like_resume_failure`, so there is no fallback and the attempt burns. Reproduced
   against the real binary. The existing recovery test covers only the `broken=True` case.
3. Goal and approved memory become a hedged *"read them if needed"* pointer on the
   continuation path, and the resume-failure fallback replays the same prompt file with
   `resume=False` — so a fresh, empty session is told it is *"continuing in the same AutoR
   conversation"*, which is false on exactly that path.

**The change.** Fix (1) and (2) as bugs — both are small and both are verified. For (3),
have the fallback rebuild the prompt with `continue_session=False` rather than replaying the
continuation file, and inline a bounded goal plus a memory subset rather than a pointer. Do
not adopt the general framing of "add a *what this stage has established* block": most of it
duplicates the handoff context and the channel set already in the prompt, and this repository
has already paid for sending memory and handoff together.

**(1) and (2) are fixed** (#256). The parity test that came with the first is the general
form: the two builders take five of the same optional content parameters, each gets a
sentinel, and both prompts must carry all five — a parameter one builder accepts and
drops is the same defect under another name. (3) stands.

*Class: two live defects plus one false premise. Effort: small.*

---

## 5. Refused, with the reason

Recorded so the next reading does not re-propose them.

**Attempt-grained artifact attribution.** `ArtifactVersion` carries a stage and no attempt
number, so a file written by a refused attempt and never rewritten is recorded as the
approved stage's work. Real, and it should stay. Nothing in the tree consumes
attempt-grained attribution: the live/withdrawn distinction has exactly one consumer outside
the provenance module and it is the graph, the rubric scores artifact freshness against a
per-visit marker rather than against the ledger, and a failed forward guard does not close
the edge anyway. Worse, the natural fix is the one
[composable-stage-graphs.md](composable-stage-graphs.md) measured and reversed: excluding
never-approved attempts from the counts would close the forward gate out of exactly the
auto-skipped stages that measurement showed depend on it.

**A guard on the `finish` edge.** See §4.3. Three measured decisions in this repository
point the other way, and the number usually quoted in support of "finish is already guarded"
describes a different edge.

**A `prior_refusals` channel into the doer.** See §4.6. Already measured here, adversely.

**LHH's route enum as a routing model.** Its five route words carry no precondition and no
code inspects the emitted subtask for scope; *"never bundle multiple dominant state changes
into one round"* is prompt text. AutoR's guarded menu is strictly stronger and the
comparison is not close.

**A record of what an elision dropped.** LHH does not have one. If AutoR wants it, it is an
invention and has to be argued on its own.

---

## 6. How this was established, and what is not verified

Both trees were read in source. The LHH half covers its manager loop, role prompts, prompt
texts, types, auditor agent, trajectory artifacts, agent logs, the Claude and CLI adapters
and their permission handling, the dashboard state, the web API snapshot and event modules,
the run-boundary utility, and the supervisor service and control bus. The AutoR half covers
the stage graph, walk ratchet, effects, manager, supervisor, operator, router, review panel,
validity review, approval agent, obligations, information flow, rubric, deliberation,
archive, manifest, artifact index, provenance and stage cost. Each candidate borrowing was
then handed to a reader whose brief was to refute it — to show either that the LHH mechanism
did not exist in code, or that AutoR already implemented an equivalent under another name.
That pass removed one candidate outright and cut material from every one that survived; the
§5 list is its output as much as §4 is.

What is **not** verified here:

- LHH's published benchmark numbers. They are quoted as their claim, not reproduced.
- Any AutoR prompt-size measurement in absolute bytes. No run directory was read for this
  document; §4.4's claims are about which code paths are uncapped, not about how large a
  particular prompt got.
- LHH's GUI/computer-use path. The plugins, the desktop adapters and the dashboard were read
  only far enough to establish that they do not carry state the CLI path does not.
- Whether any change in §4 improves a score. Every one of them is an argument about the
  record, and the repository's own rule applies: a mechanism that improves the record and is
  never measured on a run has improved the record.
