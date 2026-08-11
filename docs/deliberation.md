# Raising a crux

AutoR spends the same effort on every step. Most steps deserve that — copying a dataset,
writing a plotting script, filling in a section. A few do not. The choice of identification
strategy, the reading of an anomalous result, the decision about what the central claim is:
those are the places a human researcher stops, argues with colleagues, reads for a day, and
sits with it.

Doing those at the same tempo as the mechanical steps is how a run produces work that is
complete and shallow.

```bash
python main.py --deliberation --goal "..."
python main.py --deliberation --max-deliberations 5 --goal "..."
python main.py --deliberation --deliberation-models critic=opus --goal "..."
```

---

## Why selective, when uniform deliberation lost

The pre-registered comparison in [arXiv:2607.14713](https://arxiv.org/abs/2607.14713) found
multi-agent deliberation **losing** to a single pass when applied uniformly to every paper.
Its authors close by naming the open question exactly:

> this design does not identify the occasions on which the more elaborate tools would pay

That is what this answers. Deliberation is expensive, so it is spent only where the agent
doing the work says it is stuck — and then measured, to see whether stopping was worth it.

## The agent decides

Every stage prompt carries the offer:

> Most of this stage is execution: do it. But if you hit a question where the right answer is
> genuinely unclear and getting it wrong would invalidate work downstream, you may stop and
> pull in help rather than guessing and moving on.

The agent writes `workspace/notes/deliberation_request.json`:

```json
{"question": "Should identification rely on the 2019 policy discontinuity or on household fixed effects?",
 "why_it_matters": "Every downstream estimate inherits this choice.",
 "already_considered": ["Matching on pre-period covariates, rejected for lack of overlap."],
 "working_answer": "Use household fixed effects, because the discontinuity sample is too small.",
 "help_wanted": "perspectives | expertise | both"}
```

…then **finishes the stage with its working answer**. It is never blocked. The panel convenes
on that question, and the resolution reaches the next attempt.

`working_answer` is required in spirit rather than in schema: it is what lets the run measure
whether the panel changed anything, and a crux raised without one can only be recorded as
unmeasured.

## Why a third panel

| Panel | Takes | Produces |
| --- | --- | --- |
| [Review](review-panel.md) | a finished draft | a gate decision (converges) |
| [Ideation](ideation-panel.md) | a research goal | a candidate pool (stays diverged) |
| **Crux** | **a question** | **an answer that names its own falsifier** |

Neither existing panel answers a question. Four voices — **theorist**, **empiricist**,
**critic**, **pragmatist** — each commit to an answer and are then required to *argue against
themselves*, because the strongest objection to a position is the most useful thing its holder
can contribute, and a position with no stated weakness has not been thought about.

When `help_wanted` includes expertise, an **expert brief** is assembled first from the run's
literature and installed skills. Opinions arrive faster than evidence, so the evidence goes
first — a panel that argues before reading is a panel arguing from priors.

## The resolution must name its own falsifier

The synthesis returns four fields, and `falsifier` may not be empty:

- **answer** — what to do, concretely enough to act on today
- **reason** — why, in terms of evidence rather than vote count
- **falsifier** — what observation would change this answer
- **dissent** — the strongest surviving objection, kept rather than smoothed away

An answer nothing could overturn is an opinion, and the point of stopping to think was to get
past opinions.

The stage receives it as a conclusion with reasons attached, **not an order**: it may depart
from the answer by saying so in `Decision Ledger`. A resolution the stage cannot argue with is
a manager, not a colleague.

## The budget

`--max-deliberations` defaults to **3**. Scarcity is what makes "think hard here" mean
anything; an agent that can escalate everything has prioritised nothing. When the budget is
spent the offer is withdrawn from the prompt rather than silently ignored, and a further
request is refused with a log line.

Questions shorter than 25 characters are dropped — "what about the data?" has no answer, and a
panel asked it writes essays.

## Was stopping worth it?

`workspace/reviews/deliberations.json`, same discipline as the other panels:

```json
{
  "summary": {
    "cruxes_raised": 2,
    "changed_the_agents_answer": 0,
    "confirmed_the_agents_answer": 2,
    "voice_calls": 10,
    "verdict": "2 crux(es) escalated at 10 calls, and the panel confirmed the agent's own answer every time. On this run stopping to think changed nothing — the agent was escalating questions it had already settled."
  }
}
```

Every position from every voice is kept, including the ones the resolution rejected.

## A crux asked twice is one crux

The same live run put the **identical** question to the panel on two consecutive attempts of
one stage — byte-for-byte the same string, four voice calls each, and `cruxes_raised: 2`.

The cause is structural, not a model quirk. A stage that fails its gate is sent back with the
state it already had, regenerates its escalation from that state, and asks the same thing
again. With the default `--max-deliberations 3` the budget is gone after three attempts of a
single stage, and a genuinely new crux in Stage 04 is then refused.

So before deliberating, the ledger is checked for the same question:

- **Already answered** → the stored answer is handed straight back. No panel, no budget, no
  second entry in the ledger. Re-asking a settled question is the stage failing to notice it
  has the answer, not the run needing more thinking.
- **Asked before but never answered** → the panel is called again. A panel that could not be
  reached last time may be reachable now, and one outage should not permanently silence a crux.

`REPEAT_THRESHOLD` is 0.6, calibrated against real questions rather than guessed:

| Pair | Similarity |
|:---|---:|
| verbatim re-escalation across attempts *(the observed failure)* | 1.00 |
| paraphrase of the same question | 0.34 |
| narrowed follow-up that builds on the answer — a **new** crux | 0.21 |
| a different crux from the same stage | 0.06 |

0.6 sits well above the paraphrase, deliberately. Suppressing a deliberation the agent actually
needed costs correctness; re-arguing a paraphrase costs four calls. **The threshold is set to
fail in the cheap direction**, which means a heavy paraphrase will still be re-argued.

## When no voice answers

A panel that could not be convened and a panel that convened and added nothing are different
outcomes, and for one live run they were reported with the same sentence.

Vertex had exhausted the quota for the reviewer's base model while the run's own operator sat
on a different, healthy one. All four voices failed. The ledger said:

> 1 crux(es) escalated at 4 calls; no working answer was offered to compare against.

**That is false.** The agent's `working_answer` was a thousand characters long. What was
missing was the panel. Reading only the summary would send someone to tighten the escalation
prompt — fixing a problem that does not exist, while the outage goes unnoticed.

So the ledger now separates the two:

| Situation | What the verdict says |
|:---|:---|
| Every voice failed, every crux | *not one panel could be convened … it was never tried* |
| Every voice failed on some cruxes | *N never reached a panel … the remaining M are the only ones this run can speak to* |
| Some voices failed, the panel still sat | the ordinary verdict, plus the unreachable count |
| No voice failed, no answer emerged | unchanged — this is a real outcome |

The distinction the code turns on is `all` versus `any`. *Every* voice failing means no panel;
*a* voice failing means a smaller panel that still deliberated, and writing that off would
subtract a real result from the evidence.

The run is **not** stopped. Deliberation is an optional aid and a stage keeping its own answer
is legitimate degradation — unlike a stage operator that cannot be reached, where the run has
no findings at all and [stops](backend-health.md). The requirement here is visibility, not
refusal.

## Limits worth knowing

- **A dead panel is silent unless you read the ledger.** The run completes and the report is
  real research; only `deliberations.json` records that no crux was ever argued.
- **The agent chooses what is hard, and it may choose badly.** It can escalate a question it
  had already settled, or fail to escalate the one that mattered. The `confirmed` count catches
  the first; nothing catches the second.
- **A resolved crux is not a correct crux.** Four voices agreeing says they share a prior, not
  that they are right — which is why the falsifier is mandatory and the dissent is kept.
- **Cost is real**: `voices + 2` calls per crux with a brief, six by default, times the budget.
- If `confirmed_the_agents_answer` dominates across your runs, the honest reading is that this
  agent does not need the help it is asking for, and the flag should be off.
