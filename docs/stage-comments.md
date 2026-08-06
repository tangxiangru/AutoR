# Anchored review comments

Every refusal path in AutoR re-runs the whole stage. The continuation prompt asks the operator
to *"preserve correct completed parts unless the feedback requires changing them"* — and
nothing checks that it did.

So a reviewer who objects to one paragraph rerolls the ninety percent nobody objected to, and
the run has no way to notice. That is the defect this fixes.

---

## A comment quotes the text it objects to

Not a line number, which rots the moment anything above it moves. Not a section name, which is
too coarse to act on. A verbatim quote:

```json
{
  "decision": "custom_feedback",
  "comments": [
    {
      "quote": "Statistical power is adequate for the expected effect size.",
      "severity": "blocking",
      "comment": "No power calculation is shown; 'adequate' is asserted.",
      "required_change": "Report the MDE at 80% power for n=2,000, or drop the claim."
    }
  ]
}
```

The multi-agent audit tools in the feedback literature do exactly this — every criticism tied
to a quotation, *"so a disagreement has to point at text rather than at a hunch."*

This is an addition to the reviewer contract, not a replacement. A reviewer that returns plain
`feedback` behaves exactly as before, and the human `4. Refine with your own feedback` path is
untouched. Comments attached to an **approval** are dropped: an approval sends nothing back, so
a comment on one is an instruction nobody will act on.

## Quotes that are not there

A quote the draft does not contain is recorded as `unanchored` and **never reaches the
operator**. A reviewer objecting to text the document does not contain is objecting to
something it imagined, and passing that on as an instruction it cannot satisfy would burn a
round.

The count appears in the ledger as `comments_quoting_absent_text`. A reviewer that keeps
producing them is worth looking at.

Quotes shorter than 12 characters are dropped too — `"the results"` matches half the document,
and a comment that matches everywhere points at nothing.

## The revision is checked, not trusted

This is the part that matters. The instruction says:

> **Revise only these passages.** Every other part of the stage summary must come back
> byte-identical — do not re-word, re-order, re-title, or 'improve' anything a comment did not
> ask about.

…and then the next draft is diffed against it. Two questions, both mechanical:

| Question | Measure |
| --- | --- |
| Did each quoted passage actually change? | `addressed` / `untouched` per comment |
| How much changed that nothing asked about? | `collateral_lines_changed`, `collateral_ratio` |

"Only change what I asked about" is a prompt wish until something measures it. A targeted
revision scores `collateral_ratio: 0.0`; a whole-stage rewrite scores `0.5` and up, and the
ledger says so:

> 1 comment(s) acted on across 2 round(s), but 34 of 41 changed lines were outside anything a
> comment asked about. Targeted revision is not being honoured here — the stage is being
> rewritten, not patched.

## Unaddressed comments do not expire

A comment whose passage never moved is **carried into the next round**, with the same quote. A
review whose objections quietly disappear when ignored is advisory, not a gate.

Disagreement is allowed — the operator is told it may argue in `Revision Delta` and leave a
passage unchanged. What it may not do is silently ignore.

## The ledger

`workspace/reviews/comment_ledger.json`, one entry per round:

```json
{
  "summary": {
    "rounds": 2,
    "comments_raised": 3,
    "comments_addressed": 2,
    "comments_left_untouched": 1,
    "comments_quoting_absent_text": 0,
    "lines_changed_on_target": 4,
    "lines_changed_as_collateral": 1,
    "collateral_ratio": 0.2,
    "verdict": "..."
  },
  "rounds": [ ... ]
}
```

Stage 08 already reads `workspace/reviews/`, so the record travels with the run.

## Where this fits

- The [review panel](review-panel.md) decides *whether* a stage passes. Anchored comments
  decide *what comes back* when it does not.
- Each panel seat can quote independently, so an objection carries the seat that raised it.
- [`review_policy.json`](run-artifacts.md) carries corrections **forward across stages**;
  this ledger tracks them **within one stage**. They answer different questions.

## Limits worth knowing

- **Change is not correction.** `addressed` means the quoted text is gone, not that what
  replaced it is right. The next review round is what judges that.
- **Collateral is not always wrong.** A comment can legitimately require changes elsewhere —
  fixing a claim may mean fixing the abstract that repeats it. The ratio is a signal that
  something is worth reading, not a verdict.
- **Whole-stage failures still need whole-stage re-runs.** When the design itself is wrong,
  quoting three sentences is the wrong instrument, and a plain `feedback` refusal is correct.
