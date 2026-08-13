# The review panel

AutoR's premise is that a human owns direction while an agent owns execution. For unattended
runs that human is replaced by a reviewer agent standing at each stage gate. One model, asked
once, with one framing, is a thin stand-in for the thing it replaces.

`--review-panel` replaces it with a room.

```bash
python main.py --review-panel --goal "..."
python main.py --review-panel --persona docs/persona-example.md --goal "..."
python rcb_agent.py --review-panel          # benchmark runs
```

`--review-panel` implies `--approval-mode agent`.

---

## Does this actually help? Read this first

There is a pre-registered result that argues it may not.

Havranek and Irsova (2026, [arXiv:2607.14713](https://arxiv.org/abs/2607.14713)) had the
authors of 44 economics meta-analyses rank three identity-masked AI reports on their own
paper. A plain **single pass beat both multi-agent tools** — mean rank 1.59 against 2.25 and
2.16, Holm-adjusted p = 0.005 and 0.026 — and the multi-agent tools were the study authors'
own, pre-registered to win. The most elaborate arm spent about thirty times the tokens and
ranked 0.57 places worse. The mechanism the authors report is the one that should worry
anyone building a panel: the reports "tended to raise much the same points."

Two further findings from that paper bear directly on this feature:

- **An AI judge is not a substitute for the intended user.** Author–judge rank correlation was
  0.14, indistinguishable from zero. Had the external judge ranked the arms instead of the
  authors, it would have crowned the most expensive tool and *reversed* the finding.
- **AI judges systematically undervalue human review.** Authors placed their real journal
  referee report first 71% of the time and never last; the AI judges placed it last on 92–100%
  of papers. A panel simulating humans is built out of exactly the judges that got this wrong.

So the panel is not offered here as an established improvement. It is offered with an
instrument attached that can say it did not help — see [Measuring whether it
helped](#measuring-whether-it-helped).

What the evidence does support is *heterogeneity over deliberation*. Both that paper and
AgentPanel ([arXiv:2608.03283](https://arxiv.org/abs/2608.03283)) cite Zhang et al. (2025),
"Stop overvaluing multi-agent debate — we must rethink evaluation and embrace model
heterogeneity." AgentPanel's own gains over centralized debate are concentrated in
*feasibility* (5.08 vs 4.08 on LiveIdeaBench; 0.28 vs 0.11 and 0.31 vs 0.04 on IdeaBench),
not originality, and come from a pool of 20+ heterogeneous model backends with agents free to
**abstain** and with **deliberately uneven exposure** to each other's output. Those three
levers — different models, permitted silence, withheld context — are the ones implemented
here.

## Why a panel rather than a longer prompt

Asking one reviewer to "consider multiple perspectives" produces one voice listing
perspectives it already agreed with. The disagreement is simulated inside a single forward
pass, and a model that has already decided will find reasons rather than objections.

Independent reviewers, each with a distinct mandate, a distinct model, and no sight of each
other, produce genuinely different reads. **The disagreement between them is information a
single reviewer cannot generate.** That is the whole argument for the design, and it is why
round one is blind on purpose.

## The seats

| Role | Key | Owns | Skill |
| --- | --- | --- | --- |
| Principal Investigator | `pi` | Does this advance the central claim? Has the story drifted? Chairs the panel. | — |
| Domain Expert | `domain` | Field correctness, prior work, whether the claim is actually novel. | `citation-discipline` |
| Methodologist | `method` | Design validity: confounds, baselines, ablations, leakage, sample size. | `result-table` |
| Reproducibility Engineer | `repro` | Do the numbers trace to files that exist and could be rerun. | `reproducibility-check` |
| Adversarial Reviewer | `skeptic` | Reviewer 2. Finds the strongest reason to reject. | — |

Each seat is told to review *its part* properly and trust the panel for the rest, rather than
five members each writing a mediocre whole review.

Seat a subset with `--panel-roles method repro skeptic`. The first seat chairs unless the PI is
present. An unknown role name is an error, not a silent drop — a panel whose composition
nobody can trust is worse than no panel.

`PanelRole` carries optional `backend` and `model` overrides. **A verdict from a different
harness is the only kind that is genuinely uncorrelated**, so mixing `claude` and `codex` seats
is where the panel earns the most. Both fall back to the run's reviewer defaults so a
single-backend deployment still gets the benefit of distinct mandates.

## The protocol

1. **Round 1 — independent.** Every member reviews blind. No member sees another's position.
2. **Round 2 — cross-examination.** Only runs if the panel disagreed. Each member is shown what
   the others concluded and may revise. They are told explicitly that converging to be
   agreeable is the failure mode this round exists to avoid, and that a lone correct objection
   beats a comfortable consensus.
3. **Chair synthesis.** The chair reads every position and issues the single decision the
   workflow acts on, required to address the dissent rather than ignore it.

A unanimous, unblocked room skips both the second round and the chair. There is nothing to
deliberate about, and a second round would only invite the panel to talk itself out of an
agreement it already reached.

Raise or lower the ceiling with `--panel-rounds N`.

## What every seat inherits

A run accumulates two records that every later review has to see:

- **Standing rules** (`review_policy.json`) — the corrections earlier refusals demanded, promoted
  into requirements checked at every gate after them. This is what makes the gate strictly harder
  as a run proceeds.
- **Obligations** (`obligations.json`) — what an earlier *approval* said a later stage still owes,
  injected into that stage's prompt and into that stage's review, so the debt is actually checked.

Both were rendered into `AutomatedReviewer`'s prompt and into nothing else. No seat saw either,
and neither the seat prompt nor the chair prompt asked for `carry_forward`, so a panel run could
not create an obligation to inherit in the first place. Stated at the dial, which is the sharpest
form of it: **`--rigor max` had fewer live mechanisms than `--rigor standard`**, because the higher
setting swaps the solo reviewer for the panel and the panel could not see what the solo reviewer
sees. A knob that loses a mechanism as it is turned up is the exact thing the knob exists to
prevent.

The panel was also *writing* rules it could never read. A panel refusal reaches `record_correction`
by the same manager path a solo refusal does, so the room was teaching itself lessons it would
never be shown.

Both blocks now render inside `_context_block`, the one builder the seat prompt and the chair
prompt share, through `format_policy_for_prompt` and `format_for_review_prompt` — the same two
renderers the solo reviewer calls, so the two gates argue from one copy of the rules rather than
two that can drift. An empty policy and an empty ledger render nothing, not a heading over
nothing.

Same renderer *and* the same arguments. `format_policy_for_prompt` takes a `stage`, which
withholds the rules this stage's own earlier attempts produced; every review that demands
anything records one, so a gate that omits the argument raises the bar by a requirement per
attempt and its retry loop cannot converge. Calling the shared function is therefore necessary
and not sufficient, which is why the parity here is pinned twice: `assertIs` on the two function
objects, and `test_neither_gate_judges_a_stage_against_a_rule_its_own_retries_invented`, which
puts a rule from the stage under review into the fixture so the filter has a row to reject.

### Who may open a debt, and who may close one

| | Any seat | The chair |
| --- | --- | --- |
| Records `carry_forward` | yes — carried whatever the rest of the room decides | yes, added to the room's |
| Refuses over an unmet obligation | yes | yes |
| `discharged` actually closes one | no — recorded as a claim and put in front of the chair | yes |

The asymmetry is deliberate, because the two directions fail differently. Recording a debt is the
strict direction: it costs a line in the ledger and buys a check at the stage that owes it, so a
seat that noticed something must not need four others to agree before the run remembers it — five
seats make the run *stricter* than one. Discharge is the lenient direction, and five seats must
not become five chances for someone to accept a restatement as payment, which would make the panel
weaker than the single reviewer it replaced. So the seats advise and the chair decides.

Three rules follow, and each has a test:

- **The chair's last word closes a debt, and only that.** Its seat verdict when the room never
  split — a unanimous approval makes no chair call at all — and its synthesis once it has spoken.
  A position the chair took *before* hearing the objections stops counting once the room splits.
- **A chair that was asked and could not answer closes nothing.** Unreachable, or unreadable
  twice, and the debt stays open for a later gate.
- **Nothing is discharged while a blocking objection stands.** A draft the panel is refusing is a
  draft that is about to change, and closing a debt against it is the approval the blocking rule
  just refused, wearing another name.

Every claim a seat made is in the record next to what the chair did with it, so a discharge the
chair declined is visible rather than lost.

## Measuring whether it helped

Every panel run contains its own control arm for free: **the chair's round-1 verdict is a
single pass** — one model, one call, no peer input. Recording it costs nothing and answers the
only question that matters about this feature.

`workspace/reviews/panel/panel_effect.json` accumulates the comparison across the run:

```json
{
  "summary": {
    "gates_reviewed": 8,
    "gates_where_the_panel_changed_the_decision": 0,
    "gates_where_round_1_disagreed": 1,
    "chair_overrides": 0,
    "cost_multiple": 5.0,
    "verdict": "The panel reached the same decision as its own single-pass baseline at all 8 gate(s), at 5.0x the reviewer cost. On this run it did not earn that cost; consider --panel-roles with fewer seats, or dropping the panel."
  },
  "gates": [ ... ]
}
```

That verdict line is written to be unflattering when that is the truth. A feature that can
only report its own success is not measured, and the literature above is what happens when
builders grade their own tools without a baseline.

The same line is appended to the run log at each gate, so a long run surfaces the answer
without anyone opening a JSON file.

## Abstention

A seat may return `{"decision":"abstain"}` when it has nothing substantive to add. An
abstention is **not** disagreement — the room can still be unanimous — but it is also not
agreement, and a panel where every seat abstains reaches the chair rather than passing as
consensus.

This exists because of the null above. Forcing five seats to produce a verdict on every gate
is precisely how five reviewers come to raise much the same points. A seat with nothing to say
is better silent than padding.

## Uneven exposure

Round two does not show every seat the same thing.

- Most seats see the other positions, **anonymised as "Reviewer A/B/C"**. The substance
  survives; the attribution does not, so a methodologist weighs an objection on its evidence
  rather than deferring to it because the chair signed it. This is what the cross-model audit
  tool in the study above does.
- The **adversarial reviewer sees nothing**. Its entire value is that its read is not
  downstream of the room's, so it is asked to hold or revise from the artifacts alone.

Per-seat exposure is a `PanelRole` field (`full`, `objections`, `none`). Uniform full exposure
turns the second round into a convergence machine, which is the failure mode that makes
deliberation look like agreement.

## Model heterogeneity

`--panel-models pi=opus skeptic=codex:default method=sonnet`

Assign a model, or a backend and model, per seat. Seats left unassigned use the reviewer
default.

This is the lever with the best evidence behind it. Errors idiosyncratic to one model survive
when that model checks its own work and correlate less across families than within them — the
reason the cross-model audit tool in the study above deliberately used two families. Five
prompts against one model are five correlated reads wearing five hats.

The panel record says so plainly: `homogeneous_panel: true` when every seat shares one
backend and model, alongside `distinct_backends` and `distinct_models`.

## The blocking rule

Any member may mark an objection `blocking`. **If a blocking objection survives the final
round, approval is refused in code** — the chair's approval is converted into a refinement and
the conversion is recorded.

This is deliberately mechanical. The chair is a model, and a model asked to weigh dissent can
be argued into discounting it. A prompt-level rule the chair can talk itself out of is not a
rule, and a gate that cannot say no is not a gate.

Three guards sit alongside it:

- A member that could not be reached is **not** counted as agreeing. It breaks unanimity and
  forces deliberation.
- An unparseable answer degrades to `abort`, and cannot also count as a blocking veto — one
  malformed response should not be able to stop a run.
- **A panel nobody could reach refuses rather than approves.** When the chair is unreachable
  the panel falls back to its own seats' objections, and an unreachable seat is filtered out of
  that list because it has no opinion to weigh. With *every* seat down — the ordinary shape of a
  backend outage, five seats and a chair against one dead endpoint — the objection list came out
  empty and the empty list read as consent, so a total review outage approved the stage.
  `_decision_from_dissent` now takes an outage arm first, and the refusal it returns carries
  `CRASHED_REASON`, so `is_degraded_verdict` keeps it out of `review_policy.json`: an outage is
  not a correction anybody demanded. The guard is `all(...)` and not `any(...)` on purpose — four
  dead seats and one that answered is a panel degraded to a solo reviewer, which is thin but is
  still a judgement somebody made, and refusing on one flaky seat would make the panel unusable.

## The persona

`--persona PATH` takes a markdown description of the researcher the panel is standing in for,
and injects it into every seat. Without it, five simulated humans improvise five slightly
different bars, and the bar drifts across eight stages. With it, they hold one.

[`docs/persona-example.md`](persona-example.md) is a starting point. Write it as a description
of a person rather than a list of rules — the panel reads it the way a new postdoc reads their
advisor, to work out what this particular researcher will and will not sign their name to.

## What it leaves behind

```
workspace/reviews/panel/
├── 03_study_design_attempt_01.json
└── 03_study_design_attempt_01.md
```

Every position from every round, including **dissent that lost** and any chair override.
Stage 08 reads `workspace/reviews/`, and a run's auditability is the product's whole claim: a
panel that reported only its verdict would be less inspectable than the single reviewer it
replaced.

Each seat's own `carry_forward` and `discharged` are recorded per verdict, and the deliberation's
`carry_forward` and `discharged` are what the run's ledger was actually handed. The gap between
the two is the discharge claims the chair did not take.

The run log gets a one-line summary per gate:

```
03_study_design attempt 1 panel_decision
rounds: 2
positions: Principal Investigator=approve; Domain Expert=approve; Methodologist=custom_feedback; ...
obligations: 1 carried forward, 0 discharged
chair_overridden: True
final_choice: 4
```

## Cost

A panel costs roughly `seats x rounds + 1` reviewer calls per gate instead of one. With the
default five seats that is 5 calls when the room agrees and 11 when it does not, per stage
attempt. Nothing about the panel is cheap; it buys a gate that can actually refuse.

Reduce it by seating fewer roles (`--panel-roles repro skeptic` keeps the two that catch the
most), or by `--panel-rounds 1` to skip cross-examination.

## Limits worth knowing

- **Correlated seats.** Five prompts against one model are less independent than they look.
  `--panel-models` is the real fix; distinct mandates are a partial one, and the panel record
  flags a homogeneous roster rather than letting it pass as five opinions.
- **The null is real and this feature has not refuted it.** The measurement above is an
  instrument, not a result. If your runs report `changed_decision: 0` across every gate, the
  honest reading is that the single pass was enough for your work, and the panel should be
  turned off.
- **The panel reviews summaries, not the world.** Members are told to open artifacts, and the
  reproducibility seat exists to enforce that, but a determined stage summary can still
  describe a file more favourably than the file reads.
- **Deliberation can converge on a shared error.** Round two makes members more consistent with
  each other, which is a gain when someone is right and a loss when nobody is. The blocking
  flag is what keeps a single correct dissenter from being smoothed away.
