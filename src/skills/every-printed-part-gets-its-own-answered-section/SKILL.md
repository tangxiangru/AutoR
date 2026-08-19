---
name: every-printed-part-gets-its-own-answered-section
description: Use at hypothesis generation when the sheet in front of you prints numbered or lettered parts and sub-questions, and you are about to decide what the run will investigate. Covers transcribing the printed parts into a fixed list before any framing, giving each one its own answered section, naming the concrete instance a part asks for instead of promoting it to a variable, and the parts that get dropped because they were the least interesting thing on the sheet.
applies_when: intermediate derivations
stages: 02_hypothesis_generation
---

# The list of things you owe is printed on the sheet, and it is not the list you find interesting

A sheet with nine printed parts is nine separate obligations. What gets written
instead is a treatment of the two or three that opened onto a real question,
with the rest absorbed into the framing. The absorbed ones are not answered
badly — they are absent, and absent is the cheapest thing to fix in this whole
craft.

**Do the transcription before you do any thinking.** Open the sheet, walk it top
to bottom, and write out the list: every numbered part, every lettered
sub-part, every sentence ending in a question mark, and every imperative
("calculate", "identify", "state", "compare", "propose"). Number them. Do not
merge two into one because they are about the same object. Do not drop one
because its answer seems obvious — an obvious part is a part you can discharge
in two lines, which is the best trade on the sheet. Two lines is the floor for a
part that asks *what*, not a ceiling for a part that asks *why*: where a part
wants the reasoning, the reasoning is scored on its own and two lines will not
carry it.

Then check the list against what you are about to investigate. A part with no
line pointing at it will not be answered.

## One section per part, and the section answers it

Give each printed part a heading that names it the way the sheet names it, and
put the answer in that section. Not in the framing, not in a synthesis at the
end, not implied by a table three sections later. If a fact belongs to part C,
write it under part C — writing it under part D and expecting the two to be read
together is how a fact that is present in the document is scored as absent.

Cross-references are additive, never a substitute: state it where it is owed,
and refer to it from wherever else it matters.

## A part that asks what you would do wants the thing, not the axis

The commonest way a printed part vanishes is promotion. The sheet asks which
stressor, how long, in what order, at what concentration — and what gets written
is a design that treats it as a factor to be measured: a two-by-two over the
order, a dose surface over the concentration, a decision rule over the choice.
That is a better research programme and a worse answer. The part asked you to
commit.

Commit first, then extend:

1. **Name the instance.** The specific reagent, the specific ordering, the
   specific duration, with its value and its unit.
2. **Give the reason.** One sentence where the part only asked you to choose;
   at full length where the part asked why, because there the reason is its own
   scored obligation and not a justification of the choice.
3. **Then** say what would change it, or how you would test the choice.

The concrete narrative example — the one sentence that says what happens first,
then what happens next, with quantities — is what a part like this is paid for.
Sweeping it into a factor deletes it.

## The comparison the sheet names is not optional

When a part says "compare with", "contrast against", or "relative to", the named
comparator is part of the obligation. A comparison against something else, however
better motivated, does not discharge it. Write the named comparison first, in its
own subsection, mechanism by mechanism; put your own comparator after it.

This is where a self-chosen quantitative model does the most damage: it is the
most impressive thing in the answer, it consumes the budget, and the printed
comparison arm ends up appearing zero times in the document.

## Before you close the stage

- The transcribed list of printed parts exists, numbered, with nothing merged.
- Every entry on it has a heading of its own in the answer.
- Every part that asks for a choice states a named instance with a value and a
  unit, before any sweep or decision rule.
- Every comparator the sheet names appears as its own subsection.
- No part is answered only inside another part's section.

## Why this is here

Measured on the sixty-task FrontierScience-Research trial, one draw per task,
judged by gpt-5.1 at high effort. Task totals below are the recorded ones. The
three tasks below are all biology, and in each of them it is the pipeline arm
that lost. On fs:053 and fs:042 the run's own per-item reasoning for that arm
was overwritten on disk, so the per-item numbers for that arm come from
re-judging its answer under the same prompt template; those re-judgements return
8.0 against a recorded 7.8 and 7.7 against a recorded 8.0, which is the size of
disagreement to read the item splits against. Bracketed material inside a quoted
judgement is a redaction and not the grader's words.

**fs:044, 10.000 to 6.000.** Four items of one point each, and the ideation
pool's ten candidate titles touched none of the four: the number of candidates
pointing at any of them was **zero**. The pipeline arm scored where its pool had
looked and lost where it had not — four points on one task. The criteria and the
printed parts are not quite in one-to-one correspondence, and the loss set and
the uncovered set coincide to within one item either way, so read the identity
as close rather than exact. Three of these four points are claimed again under a
different mechanism by `grant-the-expected-reading-before-you-depart-from-it`;
the two accounts are of the same items at two points in the pipeline, and the
figures must not be added.

**fs:053, task −1.700 (9.500 to 7.800), of which 1.750 sits on the three items
below.** The item sum is larger than the task delta because other items moved
the other way; every other per-task figure in this pack is a task total, and
this one and the next are item sums stated as such. Three items moved: one
point, half a point and a quarter of a point, and all three are one failure at
three prices. In each the criterion names something the writer is to produce by
hand and commit to, and on one of the three that thing appears **0 times** in
the pipeline answer where it appears twice in the control. The judgements on
either side read `... is defined as "[the thing it committed to]," which is
precisely ... Score: 1.0/1.0` for the control and, for the pipeline arm, that it
treated the same thing as an experimental variable `but never commits to or
justifies a specific default (+0.0)`.

**fs:042, task −1.000 (9.000 to 8.000), 1.150 of it on the two items below.**
Both items turn on something the sheet itself names and the answer is expected
to take up. The control took it up only loosely — `-> ~0.2/0.2 pts
(conceptually correct)` — and still scored 0.7 of 1.0 on one of the two and 0.95
of 1.0 on the other. In the pipeline answer the thing the sheet names appears
**0 times**, and the grader wrote `it does not explicitly [take it up] ...
Score: 0.0/1.0`. The budget had gone into a self-chosen quantitative model
instead, and that model scored well on its own terms.

Length is not the cause and must not be treated as one: after removing the
control arm's duplicated text, the pipeline's biology answers total 887k
characters against 803k. The pipeline writes **more** and covers **less**.

**Checked against what chemistry pays for.** The main effect is additive: it
increases the number of separately headed, separately answered units, which is
exactly the granularity chemistry criteria reward — on fs:022 the control scored
0 of 3.5 points on items of that granularity. It merges no rows and removes no
working. It does contain two sentences that shorten — discharge an obvious part
in two lines, give the reason in one sentence — and chemistry criteria do pay
separately for the verdict and for the explanation behind it, so those two are a
ceiling on the *cheap* part of a sheet and never a licence to compress a part
that asks why. The other risk is budget dilution across many small sections;
that is why it says to discharge an obvious part in two lines rather than to
expand it.
