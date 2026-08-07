# Effort tiers

[Raising a crux](deliberation.md) gave a stage a way to stop and think hard. This is the other
half, and without it the first half is only a sentence in a prompt: **nothing in AutoR ever ran
cheaper on routine work.** Every stage carried the full prompt assembly, the full gate, and
every panel that happened to be switched on — whether it was choosing an identification
strategy or writing a CSV loader.

```bash
python main.py --effort-tiers --goal "..."
python main.py --effort-tiers --review-panel --deliberation --goal "..."
```

---

## Why uneven spending

That uniformity is the mistake the multi-agent feedback literature made and measured: applying
the expensive configuration everywhere is how the expensive configuration loses on average.
The cost lands on every step; the benefit lands on a few.

| | `routine` | `deliberative` |
| --- | --- | --- |
| Prompt | lean, plus a "do not re-open settled questions" notice | full |
| Gate | single reviewer, even when a panel is seated | whatever is configured |
| Crux escalation offered | no | yes |
| Ideation panel (Stage 02) | no | yes |

## Who chooses

**The stage that just finished declares what the next one needs**, because it is the thing
that just learned whether the hard part is over. It ends its `Decision Ledger` with one line:

```
Next stage effort: routine — the design is settled; this is engineering.
Next stage effort: deliberative — the identification strategy is still open.
```

A per-stage default applies when nothing says otherwise:

| Deliberative by default | Routine by default |
| --- | --- |
| 01 literature, 02 hypotheses, 03 design, 06 analysis, 07 writing | 04 implementation, 05 experimentation, 08 dissemination |

Those are guesses about the *shape* of the work, not claims about any particular research
question — which is exactly why a stage can override the next one's.

## What stops a wrong guess costing anything

**A routine stage that fails its gate twice is promoted to deliberative** and re-run with the
full apparatus. Cheap is a bet; this is what happens when the bet loses, and the run recovers
by itself rather than thrashing at low power.

Two, not one: a single failed gate is ordinary and often a formatting problem. Twice means the
work is harder than the previous stage thought.

A promotion also **outranks a later declaration** — evidence beats a guess. A stage cannot talk
a promoted successor back down to routine.

And a routine stage is told explicitly that if it discovers something is *not* settled, it
should say so under Open Questions rather than quietly deciding it alone. Running cheap is a
claim about the work, and the stage doing the work is allowed to contradict it.

## Concentrating the expensive knob

Tiering by itself only *labels* the steps that matter. This is the part that acts on the label.

The polish loop is the run's most expensive setting — [`src/evolution.py`](../src/evolution.py)
says so itself: *"each one is a full stage execution, so this is where the money goes"* — and
it was being spread across all eight stages regardless of whether a stage had anything left to
decide. Cost on every step, benefit on a few.

Under `--effort-tiers`:

| Resource | routine | deliberative |
| --- | --- | --- |
| Polish rounds | **none** | all the configured rounds |
| Model | `--routine-model` if given | the run's model |

This is a **reallocation, not an increase**. The same rounds, aimed only at the stages that
still have something to decide; the cheaper model handed to the ones that do not.

```bash
python main.py --effort-tiers --model opus --routine-model sonnet --goal "..."
```

A promotion moves the resources with it: a routine stage promoted after failing twice regains
its polish rounds, because promotion is a statement that the work is harder than expected and
a label that does not change what the stage gets is not worth making.

### Did the concentration actually happen?

`workspace/reviews/effort.json` gains a `concentration` block:

```json
{
  "polish_withheld_from_routine": true,
  "polish_rounds_spent": {"routine": 0, "deliberative": 5},
  "share_on_deliberative": 1.0,
  "stages_on_the_cheaper_model": ["04_implementation", "05_experimentation"],
  "verdict": "All 5 polish round(s) went to deliberative stages; routine stages spent none."
}
```

Spending nothing is not success either — a run with no polish rounds at all reports that
nothing was concentrated, rather than claiming a perfect share of zero.

## Both directions of waste are recorded

`workspace/reviews/effort.json`:

```json
{
  "summary": {
    "stages_planned": 8,
    "run_as_routine": 3,
    "declared_by_a_prior_stage": 5,
    "promoted_after_failing": 1,
    "deliberative_but_uncontested": 2,
    "verdict": "3 of 8 stage(s) ran routine; 1 had to be promoted after failing, so that call was wrong; 2 ran deliberative but passed first time uncontested, so that effort bought nothing."
  }
}
```

- **`promoted_after_failing`** — ran cheap and should not have.
- **`deliberative_but_uncontested`** — passed first time with nobody asking for a change, so
  the ceremony was paid for and unused.

A tiering scheme that can only report one direction is measuring whether it was brave, not
whether it was right. A run where `run_as_routine` is 0 is called out too: nothing was treated
as routine, which is the thing tiering exists to avoid.

## Limits worth knowing

- **The promotion rule catches running too cheap; nothing catches running too rich.**
  `deliberative_but_uncontested` is a hint, not proof — a stage can be genuinely hard and still
  pass first time because it was done well.
- **The declaring stage is guessing about work it has not done.** It knows whether *its own*
  decisions are settled, which is a good proxy and not the same thing.
- **Tiering is off by default, and off means exactly the previous behaviour** — every stage
  deliberative, nothing gated more cheaply by accident.
