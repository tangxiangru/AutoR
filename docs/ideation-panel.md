# The ideation panel

[`--review-panel`](review-panel.md) seats a room to **converge** on one gate decision.
`--ideation-panel` does the opposite job with the same machinery, because that is where the
evidence for multi-agent systems actually points.

```bash
python main.py --ideation-panel --goal "..."
python main.py --ideation-panel --ideation-lenses mechanism null regime --goal "..."
python main.py --ideation-panel --ideation-models mechanism=opus null=codex:default --goal "..."
```

---

## Why divergence rather than debate

AgentPanel ([arXiv:2608.03283](https://arxiv.org/abs/2608.03283)) beat centralized multi-agent
debate on two ideation benchmarks, and its own reading of why is not that the agents argued
better. A heterogeneous population **widened the candidate pool** and left the selecting to a
human: *"the value of multi-agent scientific systems lies not only in improving individual
responses, but also in expanding and organizing a diverse candidate pool for human comparison,
selection, and refinement."*

Its gains concentrate in **feasibility** — 5.08 vs 4.08 on LiveIdeaBench, 0.28 vs 0.11 and
0.31 vs 0.04 on IdeaBench — not originality. More agents did not produce wilder ideas. They
produced more usable ones.

So Stage 02 gets a pool, not a verdict. **Nothing in this module decides anything.**

## The lenses

Five proposers, blind to each other, each looking somewhere different:

| Lens | Looks for |
| --- | --- |
| `mechanism` | What process would have to be true for the pattern to arise. |
| `contrarian` | What the world looks like if the obvious reading is wrong. |
| `adjacent` | A mechanism standard in a neighbouring field and unusual in this one. |
| `null` | Confounds, selection effects, artifacts — the boring explanations that must be excluded first. |
| `regime` | Where the effect should strengthen, invert, or vanish with scale or population. |

Lenses are the generation-side answer to correlated seats. Five agents asked for "a good
hypothesis" return five versions of the obvious one; these five return five different objects.

Each proposer may return an **empty list**. A lens with nothing real to offer on this goal
costs the panel nothing by staying silent, and costs it the diversity it exists for by
restating the obvious hypothesis.

## What Stage 02 receives

Candidates are deduplicated, scored on novelty / feasibility / relevance, ranked, and injected
into the Stage 02 prompt as **material, not a decision**. The stage is asked to say which it
took and why it left the rest.

Artifacts land in `workspace/notes/idea_pool.json` and `idea_pool.md`.

## Measuring whether it widened anything

Same discipline as the review panel, for the same reason.

Havranek and Irsova ([arXiv:2607.14713](https://arxiv.org/abs/2607.14713)) found a plain single
pass beating two multi-agent tools, and the mechanism they report is that the reports *"tended
to raise much the same points."* A pool of five restatements is that null in another costume.

So **the first proposer is the single-pass baseline** — one lens, one call, no sight of anyone
else — and the pool records how much of itself the others actually added:

```json
{
  "proposed": 7,
  "distinct": 3,
  "collapsed_as_duplicates": 4,
  "added_by_other_proposers": 0,
  "verdict": "All 3 distinct hypotheses came from the baseline proposer; the other proposers restated it, at 5 proposer calls. On this run the panel widened nothing — consider --ideation-lenses with fewer seats, or dropping it."
}
```

Duplicate detection is plain Python, not a model call: asking a model whether five of its own
ideas are really the same idea is the wrong instrument for catching a collapsed pool. The
threshold (0.5 Jaccard over content words) is **calibrated rather than guessed** — rewordings
of one claim score 0.60–0.78, a related-but-distinct claim about the same variables scores
0.28, unrelated claims score 0.00. Titles are excluded from the comparison, because two
proposers naming one idea differently is exactly the collapse this has to catch.

## Cost

`lenses + 1` calls per Stage 02 attempt — six by default, once per attempt. Cheaper than the
review panel, which pays per gate.

## Limits worth knowing

- **The pool is material, not a dependency.** A panel that cannot be reached logs the failure
  and Stage 02 generates hypotheses the ordinary way.
- **Scoring is one call over the whole pool**, not independent critics per candidate. It orders
  material a later reader judges anyway; paying per candidate would spend more on ranking the
  pool than on generating it.
- **A widened pool is not a better hypothesis.** AgentPanel measured candidate quality, not
  downstream research outcomes, and neither does this. If `added_by_other_proposers` stays 0
  across your runs, the honest reading is that one proposer was enough.
