---
name: evidence-not-assertion
description: Use whenever a number, a comparison or a claim is about to enter a stage summary or the report — at analysis and writing, and any time you are tempted to state a value you have not computed in this run. Covers where a number must come from, what to do when the experiment did not run, and why an honest gap outscores a plausible sentence.
---

# Every number comes from a file this run wrote

A reader who cannot trace a number to an artifact has to decide whether to trust
it, and a strict one decides no. That is not a style preference: a value you
recall from the literature, infer from a trend, or round from memory is
indistinguishable in the prose from one you measured, and the moment a single
number turns out to be invented the whole report is worth nothing.

So, for every quantity that reaches the report:

- It was produced by code in `code/` and written to a file under `outputs/` or
  `results/` during this run. Name that file next to the number.
- If it comes from the literature, say so in the same sentence, with the source.
  "The published value is X (Smith 2023); we measure Y" is a result. "The value
  is X" where X came from a paper is a fabrication with a citation missing.
- If you have not run the experiment, do not describe what it would have shown.
  Write what you did run and what remains unmeasured.

## When the experiment did not run

State it plainly, in one sentence, in the section where the result would have
gone: what was not run, why, and what would settle it. Do not bury it in a
limitations paragraph at the end, and do not substitute a proxy analysis without
saying that is what you are doing.

An honest "we did not measure this" costs you that one result. A plausible
sentence with no measurement behind it, once found, costs you the reader's
belief in the results you *did* measure — including the good ones.

## The self-check before writing

Take the three numbers your abstract leads with. For each, open the file it came
from. If you cannot, it does not go in the abstract.
