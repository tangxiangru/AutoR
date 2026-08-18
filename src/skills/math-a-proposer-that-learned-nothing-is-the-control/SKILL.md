---
name: math-a-proposer-that-learned-nothing-is-the-control
description: Use at study design and experimentation when the source's contribution is that a learned component chooses something a human or a search would otherwise supply, and the released model, checkpoint or its dependency stack will not install on your machine. Covers capping the time you spend inside somebody else's environment, training the smallest model that fits the same interface instead, the corpus-size scaling curve that bounds the endpoint you cannot reach, and why a random and a hand-written proposer are two copies of the null arm.
applies_when: neuro-?symbolic|neurosymbolic
stages: 03_study_design, 04_implementation, 05_experimentation
---

# Two untrained proposers are two copies of the control arm

The claim you are reproducing is that *learning* the choice beats not learning it.
Replacing the learned component with a uniform sampler, and then with a hand-written
prior, gives you that comparison's null arm twice. Reporting that neither buys much
is a measurement of the null. The sentence a reader is waiting for — what the learned
component adds over it — is still unwritten, and no amount of rigour applied to the
control writes it.

So the design question is not "can I run their model", it is "does this run contain a
trained component at all". If the answer is no when the study is planned, it will be
no when the report is written, because nothing downstream forces it.

## Cap the environment archaeology by the clock, and write the cap down first

A released model that will not install is a fact about somebody else's packaging in
a particular month against a particular index. It is worth measuring once: attempt
the release's own pinned configuration on the interpreter its requirements were
compiled for, record each attempt with the exact symbol that failed, and stop at a
budget you set in advance — an hour, or a fixed number of configurations, decided
before the first `pip install` rather than after the fifth.

Everything past that cap buys the same sentence at a rising price. Two rounds of
version archaeology and one round produce the same finding, *the release does not
install here*, and the second round is paid for out of the budget that was going to
train your own model. Record the attempts as a table so the failure is a measurement
rather than an anecdote, then leave.

## Then train the smallest thing that fits the same interface

What the reproduction needs from the learned component is its *interface*, not its
parameter count: whatever the released model consumed and emitted, yours consumes and
emits, in the same serialisation, so it can be spliced into the source's own search
loop without touching the loop. A few-million-parameter model trained for an hour on
the corpus you generated yourself is a learned component. It will lose to the
published one by a wide margin, and it answers a class of question — does learning
this choice help, where does the learned policy break, what does the data buy — that
no untrained proposer can answer at any budget.

Run it inside the source's search, not in isolation. A validation loss is not a
result about the system; a decode that the source's own translator accepts and the
source's own solver then consumes is.

## The scaling curve is how you speak about a scale you cannot reach

Retrain from scratch at a ladder of corpus sizes on nested subsets with one fixed
held-out split, and plot loss and the task metric against corpus size on a log axis.
State the slope, state the ratio between your largest corpus and the source's, and
say whether the curve has flattened. That turns "we could not reach their scale" into
a measured statement about how far the curve still has to run, and it is the only
honest way to relate a thousandth-scale run to a published endpoint. Do not
extrapolate the curve to their corpus size — plot it, quote the ratio, and let the
reader see that the trend has not saturated.

## Report where the learned model fails, in the vocabulary of your corpus

A trained component that closes nothing is still a result if you say why. Break the
failures down by a property of the instance — size, vocabulary, depth, how far
outside the generator's own sampling range it sits — and you will usually find the
failure is concentrated rather than uniform, and that the concentration points at the
corpus rather than at the architecture. "The policy has learned the grammar but not
the regime the full corpus supplies" is a finding. "It solved zero" is not.

## What the results section owes

Three rows on the same instances at a matched budget, in this order: the system with
no proposer, the system with an untrained proposer, the system with your trained one.
That is the comparison the source's claim is about. One or two of those rows on their
own do not make a smaller version of it; they make a different study.

## Why this is here

Measured on Math_003 of ResearchClawBench, gpt-5.1 judge, three draws. The checklist
item covering the source's training regime (weight 0.35) scored **11.0 for AutoR
against 29.3 for bare Claude Code**, and the judge's stated reason was that AutoR
"does not reproduce or modify the synthetic data generation" and makes no attempt to
"match, measure, or improve upon" the training setup. AutoR's workspace records **10
dependency-installation attempts across two probe rounds** — five on one interpreter,
five more on two others hours later — with **0 successes**, and contains **no trained
parameters at all**: no `.pt`, `.pth` or `.safetensors` file anywhere under the run
root. Its only non-symbolic arms were a uniform-random proposer and a hand-written
heuristic, which its own report correctly describes as adding 0 and 1 problems. The
bare agent capped nothing and archaeologised nothing: it trained a 4.8M-parameter
decoder on its own generated corpus (`outputs/lm/geolm.pt`), swept training-set size
over 250, 500, 1000, 2000, 4000, 8000 and 15,400 examples, ran the result inside the
release's own search loop, and reported the size regime where its decodes stop being
legal. The pack's general `train-the-named-architecture` says most of this, and its
`applies_when` matches "neural network" and "pre-train" — not a brief that says
"neuro-symbolic" — so it was never installed for this run.
