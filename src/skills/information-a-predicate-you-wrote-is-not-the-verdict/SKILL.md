---
name: information-a-predicate-you-wrote-is-not-the-verdict
description: Use at experimentation and analysis when a keyword list, regex or rubric you authored is scoring free-form model output, and its answer is about to become the report's headline about a qualitative capability. Covers estimating the rule's false-negative rate before it decides anything, the calibration set to freeze alongside it, and how a negative verdict has to be published.
stages: 05_experimentation, 06_analysis
applies_when: multimodal understanding
---

# A lexicon rule scores your lexicon, and it fails in one direction

Turning an anecdote into a rate is the right instinct: a paper that demonstrates
a capability with one printed answer has evidence of n = 1, and twelve decodes
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

1. **Validate on the source's printed answer.** Necessary, and much weaker than
   it looks: it proves the rule can fire on one text the authors wrote. It says
   nothing about paraphrases, and paraphrase is the whole failure mode.
2. **Freeze a hand-labelled calibration set with the rule.** Before any decode is
   scored, commit to labelling k of your own outputs by hand, blind to the rule's
   verdict, and to publishing the agreement. That keeps the audit from being an
   after-the-fact rescue of a number you did not like, which is the objection to
   doing it later, and it gives the frozen rate a measured error rate instead of
   an assumed one.
3. **Read your own modal output yourself.** One decode, two minutes. If a plain
   reading of it satisfies the criterion the rule just failed, the rule's
   false-negative rate is not zero and every rate it produced is a floor.

## Publishing a disagreement

When the hand read and the rule disagree, both go in the same sentence, at the
same prominence, with **the transcript under them**: *"Under the frozen lexicon
0 of 12; under a blind hand read of the same twelve, 3 of 12; here is the modal
decode."* That is a sharper result than either number alone — it is a measured
case of an automatic rubric rejecting a correct output, with the output attached
— and it is honest in both directions, because the frozen rule is still the one
the pre-registered decision runs on.

What must not happen is the shape where the rule's verdict is the only sentence a
reader gets. A headline of *refuted*, *inverts* or *the capability does not
reproduce*, resting on a lexicon, with no output printed anywhere in the
document, asks a reader to take an instrument's word about a system. A negative
verdict on a capability the source demonstrated is the strongest claim in the
report and it carries the heaviest evidential burden, not the lightest.

Freezing a rule protects you from tuning it on the outcome. It does not make it
correct, and a frozen wrong rule is still wrong.

## Boundary

`information-check-the-steps-yourself-not-only-their-scores` builds a mechanical
oracle for algebra, where one exists. This is for free-form natural-language
output, where none does, and the substitute is a small blind hand read committed
to in advance.

## Why this is here

Measured on a unified understanding-and-generation reproduction. Its meme arm
froze three predicates and reported the third — the strong/weak polarity that is
the joke — as 0 of 12, leading the abstract with "the meme profile **inverts**"
and an asymmetry of −0.75. The run's own `outputs/rows/h5_janus-1.3b.jsonl`
records that predicate `False` on all fifteen rows, and its greedy decode reads
"…the visual encoding process is more flexible and can be broken down into its
individual components, much like the dog's muscles, allowing for more control and
flexibility… In contrast, the 'Single Visual Encoder' meme implies that the
encoding process is more centralized and less flexible." A blind hand re-score in
the same run returned 3 of 12 and an independently written relaxed rule agreed,
both reported as exploratory after the frozen zero. No decode was quoted in the
report. That criterion scored **26.7** against **38.3** for a plain agent whose
greedy decode misread one of the two captions outright.
