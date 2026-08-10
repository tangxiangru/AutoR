# What the optional machinery bought

AutoR has five optional features that each measure themselves honestly and write their own
ledger: the [review panel](review-panel.md), the [ideation panel](ideation-panel.md),
[anchored comments](stage-comments.md), [crux deliberation](deliberation.md), and
[effort tiers](effort-tiers.md). Each can say it did not help.

**None of them were read together.** Deciding which flags to run next time meant opening five
JSON files and doing the arithmetic, so in practice nobody did — and five honest
self-assessments add up to no answer at all.

At the end of a run, `workspace/reviews/scorecard.md` answers the only question left:

```
4 optional feature(s) ran, costing about 58 extra model call(s); 2 changed an
outcome; 1 changed nothing and can be turned off; 1 could not be measured.

| Feature                  | Flag               | Verdict                          | Extra calls |
| Review panel             | --review-panel     | drop — changed nothing           | 40          |
| Ideation panel           | --ideation-panel   | unproven — could not be measured | 6           |
| Crux deliberation        | --deliberation     | keep — changed an outcome        | 12          |
| Effort tiers             | --effort-tiers     | keep — changed an outcome        | —           |
```

…followed by a **Turn these off** section naming the flags, with each feature's own verdict
sentence as the reason.

---

## Three verdicts, and the distinction that matters

| Verdict | Meaning |
| --- | --- |
| `keep` | Enabled, measured, and the measurement says it changed an outcome. |
| `drop` | Enabled, measured, and it changed nothing. |
| `unproven` | Enabled, but the measurement could not run. |

**`unproven` is not a pass.** A feature lands here when there was no baseline to compare
against — the ideation panel whose Stage 02 was never approved, the crux panel that was
offered a question with no working answer, the review panel that never reached a gate. The run
does not know whether these helped, and saying so is different from saying they helped.

The rendered report repeats that in the artifact itself, because the temptation to read a
missing measurement as a good result is exactly what the rest of this work exists to resist.

## Two things it refuses to conflate

- **Never enabled ≠ failed.** A feature that was not switched on is reported as unused and
  appears in no section.
- **Unreadable ≠ no effect.** A ledger that exists but cannot be parsed is reported as
  unreadable. Reporting it as a null would condemn a working feature with the same confidence
  the card uses for a real one — the worst thing a scorecard can do.

## Cost

The headline totals the extra model calls the optional machinery spent, taken from each
feature's own accounting: panel member calls, proposer calls, deliberation voice calls. A
feature whose cost is not in model calls (effort tiering, which *saves* them) reports none
rather than inventing a number.

## Limits worth knowing

- **It grades a single run.** One run is one sample; a feature that changed nothing here may
  matter on a harder problem. The card says what happened, not what will.
- **`keep` means "changed an outcome", not "changed it for the better."** A panel that
  overturned a decision is recorded as having done so; whether it was right is a judgement the
  card does not make.
- **The verdicts inherit their features' blind spots.** Each row is only as good as the ledger
  behind it, and every one of those documents its own limits.
