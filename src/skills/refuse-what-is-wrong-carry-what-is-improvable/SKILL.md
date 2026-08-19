---
name: refuse-what-is-wrong-carry-what-is-improvable
description: Use when reviewing a stage that has already been through several attempts and you can still find something to object to. Covers the difference between an objection that must stop this stage and one that should be carried forward, and what a stage actually costs when the room never runs out of improvements.
---

# The room has to be able to stop

Finding something wrong with a research artifact is not hard, and it does not get
harder with each round. A competent reviewer looking at attempt eight will find
two more defensible improvements, the same way it found two on attempt one. That
is not evidence the stage is not ready. It is evidence that "is there anything
left to improve" is not a question with a terminating answer.

So the question your seat answers is not "can I find something". It is: **does
what I found change what this stage concluded?**

## What happens to a stage the room never approves

It is not held back for more work. A stage that runs out of attempts is *skipped*:
its draft may be preserved, but nothing about it was ever approved, downstream
stages are told to treat it as unreviewed, and the round it declared is dropped.

Measured on a forty-task benchmark arm: 34 of 40 runs skipped at least one stage,
67 skips in all, and **56 of those 67 had no validation error outstanding** — the
artifacts were sound and the room kept going. One run's Stage 06 scored 1.000 on
all eight of its rubric criteria and was approved by the panel, then lost the
whole stage thirty-five seconds later to one more objection with no attempt left
to answer it.

A stage lost this way scores zero on everything it would have carried. A stage
approved with a real caveat attached scores what it earned, minus the caveat.

## The test

**Refuse — and mark it blocking — when:**

- A claim is not supported by the artifacts the stage produced.
- A number in the summary disagrees with the file it cites.
- The stage says it did something the artifacts show it did not do.
- A deliverable this stage was responsible for is absent and unexplained.
- An inherited obligation was neither discharged nor honestly deferred.

Each of these you can settle by naming one artifact. Name it.

**Carry forward — and approve — when:**

- The framing could be sharper, the caveat could be earlier, the section could be
  reordered.
- A further check, a second estimator or an extra control would strengthen a
  conclusion the current evidence already supports.
- The defect belongs to a later stage's job and this stage merely fails to
  anticipate it.
- You want something done, but you cannot say which sentence in the summary is
  false without it.

`carry_forward` is not a weaker refusal. Its entries are injected into the target
stage's prompt and into that stage's review, so they are checked — which a
refusal that costs the run the stage is not.

## Two things that should raise your bar, not lower it

- **An objection you could have raised against the previous attempt** is not what
  is stopping this one. If it survived your last review unmentioned, it is a
  carry-forward.
- **A high attempt number.** Not because the bar drops, but because the cost of
  the next round has risen and the marginal defect has usually shrunk. State
  plainly, in `reason`, why this particular objection is worth the stage.

None of this asks you to approve work that is wrong. Reviewer 2's job is to find
the argument that the conclusion does not hold, and a real one is worth a refusal
at any attempt number. It asks you to notice that "not yet perfect" and "not
right" are different findings, and that only one of them is worth what refusing
costs.
