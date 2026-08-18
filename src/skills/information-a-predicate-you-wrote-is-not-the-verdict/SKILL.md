---
name: information-a-predicate-you-wrote-is-not-the-verdict
description: Use at experimentation and analysis when a keyword list, regex or rubric you authored is scoring free-form model output, and its answer is about to become the report's headline about a qualitative capability. Covers the direction such a rule fails in, the calibration set that has to be frozen alongside it, which sensitivity check is worth the compute, and how a negative verdict has to be published.
stages: 05_experimentation, 06_analysis
applies_when: multimodal understanding
---

# A lexicon rule scores your lexicon, and it fails in one direction

Turning an anecdote into a rate is the right instinct: a paper that demonstrates
a capability with one printed answer has evidence of n = 1, and a dozen decodes
against predicates fixed in advance is a real improvement on it. But the
predicates are an instrument you built, and a keyword or regex rule over
free-form generated prose has an asymmetric error: it almost never fires on
output that lacks the idea, and it routinely misses output that carries the idea
in words the list does not contain. Its rate is a **lower bound on the
capability** and an exact measurement of your word list.

That asymmetry decides how the number may be used. A rule that returns zero has
told you one of two things and has not told you which: the system never did it,
or the system did it in other words.

## Calibrate the rule before it decides anything

1. **Freeze a hand-labelled calibration set with the rule.** Before any decode
   is scored, commit to labelling k of your own outputs by hand, blind to the
   rule's verdict, and to publishing the agreement. That is what keeps the audit
   from being an after-the-fact rescue of a number you did not like, which is
   the objection to doing it later, and it gives the frozen rate a measured
   error rate instead of an assumed one. A hand read produced after the zero is
   real evidence and cannot be the verdict, because by then you knew what you
   wanted it to say.
2. **Read your own modal output yourself.** One decode, two minutes. If a plain
   reading of it satisfies the criterion the rule just failed, the rule's
   false-negative rate is not zero and every rate it produced is a floor.
3. **Spend the sensitivity budget on the axis the rule is weak on.** Re-running
   the generation under a different mechanical setting — a longer budget,
   another seed, a second checkpoint — tests the model, and it is the easy check
   to automate. It cannot test the lexicon, because the lexicon is unchanged in
   every arm of it. The only check that can is you reading the outputs and
   judging them in words, and it costs minutes rather than GPU hours.

Running the rule over the source's own printed answer is a fourth thing and you
should do it too — `the-headline-entry-is-the-canonical-outcome` asks for it. It
is necessary and much weaker than it looks: it proves the rule can fire on texts
the authors wrote, and paraphrase, which is the whole failure mode, is exactly
what those texts do not contain.

## Publishing a disagreement

When the hand read and the rule disagree, both go in the same sentence, at the
same prominence, with **the transcript under them**: *"Under the frozen lexicon
k of n; under a blind hand read of the same n, k′ of n; here is the modal
decode."* That is a sharper result than either number alone — it is a measured
case of an automatic rubric rejecting a correct output, with the output attached
— and it is honest in both directions, because the frozen rule is still the one
the pre-registered decision runs on.

Same sentence, and the same *places*: a disagreement that lives only in a figure
caption while the abstract, the summary row and the conclusion each carry the
rule's number alone has not been published, it has been footnoted.

What must not happen is the shape where the rule's verdict is the only sentence
a reader gets. A headline of *refuted*, *inverts* or *the capability does not
reproduce*, resting on a lexicon, with no output printed anywhere in the
document, asks a reader to take an instrument's word about a system. A negative
verdict on a capability the source demonstrated is the strongest claim in the
report and it carries the heaviest evidential burden, not the lightest.

Freezing a rule protects you from tuning it on the outcome. It does not make it
correct, and a frozen wrong rule is still wrong.

## Boundary

`information-check-the-steps-yourself-not-only-their-scores` builds a mechanical
oracle for algebra, where one exists. This is for free-form natural-language
output, where none does, and the substitute is a small hand read committed to in
advance.

`the-headline-entry-is-the-canonical-outcome` governs where a rate is allowed to
appear — the summary row, the abstract, the heading, the figure title — and asks
for the rule to be run over the reference answer. This is about the rule itself:
which direction it fails in, what has to be frozen beside it so a disagreement
can adjudicate anything, and which sensitivity check is worth buying.

## Why this is here

Measured on a unified understanding-and-generation reproduction. Its meme arm
froze three predicates and reported the third — the strong/weak polarity that is
the joke — as 0 of 12. The abstract carries that zero and an asymmetry of −0.75,
the headline results table carries the −0.75, and the conclusion repeats the
verdict. The run's own `outputs/rows/h5_janus-1.3b.jsonl` records the predicate
`False` on all fifteen rows, while its greedy decode reads the muscular dog as
"more control and flexibility" against a "more centralized and less flexible"
single encoder — the polarity, in words the list did not hold. None of those
words, and no other decode, appears anywhere in the report; it contains no fenced
block at all.

The rule had been calibrated the recommended way and it passed:
`outputs/h5_scorer_validation.json` runs all three predicates over the three
systems' answers printed in the source's own figure and matches the expected
pattern in 9 of 9 cells, before any decode was scored, with the predicates not
adjusted to fit. Calibrating against texts the authors wrote is what cannot
catch a paraphrase, and paraphrase is what the run's own model produced.

Both audits it then ran point the same way. `outputs/h5_uncapped_sensitivity.json`
re-decoded at a token cap of 512 instead of 160, found nothing still truncated,
and returned the same rates — so the zero was never the budget, and that is where
the compute went. `outputs/h5_hand_adjudication.json` re-scored the same twelve
by hand, in a read the report describes as blind to the keyword lists, and got 3
of 12, with an independently written relaxed rule agreeing; but both were
produced after the decodes had been read, so the run correctly labelled them
exploratory and could not let either touch the verdict. It reaches the meme
section and its figure caption, and none of the three headline places above. The
check that could have moved the finding was the cheap one, and it was reached too
late to count.

That criterion scored **26.7** against **38.3** for a plain agent on the same
task — which ran its own twelve decodes of the same checkpoint, published 3 of 12
for the same polarity as its finding, quoted the deciding fragments of its
decodes inline, and reported that its own greedy decode misread one of the two
embedded strings outright.
