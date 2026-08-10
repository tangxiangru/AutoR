# One dial: `--rigor`

AutoR's optional machinery arrived one feature at a time, and each arrival made the same
locally correct argument: *this is unproven, so do not impose it — default it off behind its
own flag.*

Four features later that aggregate was indefensible. You had to know four switches to get any
of it, and AutoR then wrote you a scorecard whose entire purpose is to say **which of those
four you should have picked**. An instrument that says "you cannot know this up front" sitting
behind an interface that demands you know it up front is a contradiction, not a design.

So there is one dial.

```bash
python main.py --goal "..."                    # standard, the default
python main.py --rigor fast --goal "..."
python main.py --rigor thorough --goal "..."
python main.py --rigor max --goal "..."
```

| Level | Turns on | Why here |
| --- | --- | --- |
| `fast` | nothing optional | What AutoR did before any of this existed. |
| **`standard`** | effort tiers | The only switch that *lowers* a run's cost, so it costs nothing to default on. |
| `thorough` | + crux deliberation, ideation panel | Budgeted and one-off respectively. |
| `max` | + review panel | Bills per *gate* rather than per run, and is the one with direct evidence against it. |

The levels nest: a higher level never turns off something a lower one turned on.

## The ordering is not a taste

It follows the two things that decide whether a feature belongs in a default — what it costs
per run, and what evidence there is that it helps.

- **Effort tiers** withholds polish rounds from stages whose decisions are already made. It is
  the only one of the four that makes a run cheaper.
- **Crux deliberation** is budgeted at three escalations and only fires when a stage says it
  is stuck.
- **The ideation panel** is one extra round of proposers, once, at Stage 02.
- **The review panel** costs 5–11 calls *per gate*, and the pre-registered comparison in
  [arXiv:2607.14713](https://arxiv.org/abs/2607.14713) found uniform multi-agent deliberation
  losing to a single pass.

Worth saying plainly: **the feature built first here, and most elaborately, is the one that
belongs furthest from the default.**

## Individual switches still work

They are escape hatches now, not the interface. Each takes a negative form:

```bash
python main.py --rigor thorough --no-ideation-panel --goal "..."
python main.py --rigor fast --review-panel --goal "..."
```

An explicit flag wins in **both** directions. That is why the switches are declared with
`BooleanOptionalAction` and no default: a plain `store_true` cannot tell *"off because they
asked"* from *"off because nobody mentioned it"*, and that difference is the whole reason an
override can beat a level.

The per-feature knobs — `--panel-roles`, `--ideation-lenses`, `--deliberation-voices`,
`--panel-models` and friends — are untouched. They were never the problem; needing four
booleans to get any behaviour at all was.

## Reading the dial back

The chosen level is printed at startup and recorded on the run's
[scorecard](scorecard.md), so the card can be read against what was asked for:

```
Run at `--rigor thorough`.
4 optional feature(s) ran, costing about 58 extra model call(s); 2 changed an
outcome; 1 changed nothing and can be turned off; 1 could not be measured.
```

The intended loop is: run at a level, read the card, move the dial. Not: read four docs and
guess.
