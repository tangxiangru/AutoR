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

## The blocking rule

Any member may mark an objection `blocking`. **If a blocking objection survives the final
round, approval is refused in code** — the chair's approval is converted into a refinement and
the conversion is recorded.

This is deliberately mechanical. The chair is a model, and a model asked to weigh dissent can
be argued into discounting it. A prompt-level rule the chair can talk itself out of is not a
rule, and a gate that cannot say no is not a gate.

Two guards sit alongside it:

- A member that could not be reached is **not** counted as agreeing. It breaks unanimity and
  forces deliberation.
- An unparseable answer degrades to `abort`, and cannot also count as a blocking veto — one
  malformed response should not be able to stop a run.

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

The run log gets a one-line summary per gate:

```
03_study_design attempt 1 panel_decision
rounds: 2
positions: Principal Investigator=approve; Domain Expert=approve; Methodologist=custom_feedback; ...
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
  Mixed backends are the real fix; distinct mandates are a partial one.
- **The panel reviews summaries, not the world.** Members are told to open artifacts, and the
  reproducibility seat exists to enforce that, but a determined stage summary can still
  describe a file more favourably than the file reads.
- **Deliberation can converge on a shared error.** Round two makes members more consistent with
  each other, which is a gain when someone is right and a loss when nobody is. The blocking
  flag is what keeps a single correct dissenter from being smoothed away.
