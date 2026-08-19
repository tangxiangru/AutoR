---
name: grant-the-expected-reading-before-you-depart-from-it
description: Use at hypothesis generation when a panel or a review has converged the run onto one committed reading and the obvious textbook reading is about to be named and then ruled out. Covers why an eliminated candidate scores as absent while an unranked alternative scores as present, the granted-reading paragraph that keeps both, and the three phrasings that turn a correct refinement into a lost point.
applies_when: intermediate derivations
stages: 02_hypothesis_generation
---

# Naming a candidate in order to kill it is how you get no credit for naming it

Converging on one commitment is the right instinct for research and the wrong
reflex for an answer that is read clause by clause. A reader looking for whether
you engaged with a particular mechanism finds the words, reads the sentence
they sit in, sees that you ruled it out, and records that you did not offer it.
An answer that mentions the same mechanism as a live alternative — without
ranking it, without defending it — is read as having offered it.

So the elimination costs you the point and the hedge keeps it. This is not a
reason to hedge everything. It is a reason to **keep both readings on the page**
whenever the one you are ruling out is the conventional one.

## The granted-reading paragraph

Whenever you are about to write "not X", "X is excluded", "X is eliminated by",
"X is a minority channel", or "this is not the classical X mechanism", stop and
write this instead, in this order:

1. **The conventional reading, stated straight.** One short paragraph, in its
   own words, as its own proponent would put it — the standard identity, the
   standard mechanism, the standard technique for this situation. No hedge, no
   framing device, no "one might say".
2. **Your commitment, with the sign of the evidence that moved you.**
3. **The switch condition.** What observation would put the conventional reading
   back in front.

You lose nothing scientifically: your commitment is still first-ranked and still
argued. You keep the sentence a reader needs to find.

## Correcting the expected answer is the expensive move

The most costly single sentence in this trial was factually right. A run
explained that a proposed rationale was not the mechanism it is usually named
for — true, and precisely the rationale being looked for. The refinement is
worth writing. Write it **after** the conventional rationale has been stated as
the primary one, as a refinement of it, not as its replacement.

Same rule for a parameter. When your own reasoning fixes a value or a bound that
sits inside the conventional range, report both: the conventional range, named
as such, and your narrower committed value with the argument for the narrowing.
A committed single value that excludes the conventional one deletes it from the
document; a range that contains it keeps it. This costs one line.

## Assignments across a set are all-or-nothing in both directions

When a sheet asks you to assign one method, one technique or one instrument to
each of several scenarios and forbids reuse, a single reassignment moves two
answers at once. Before you swap on the strength of a scoring rule you invented,
write the conventional assignment out as a full row-by-row table, then your own
beside it, then the one-sentence reason for each cell you moved. If your own
scoring rule separates two options by a few hundredths, that is not a reason to
move a cell — say so and leave it.

## The three phrasings to remove

- "**X is eliminated by** ..." → "X is the standard reading here, and it holds
  unless ...; I rank Y first because ..."
- "**Not X, but Y**" → "Y, on the evidence below; X is the conventional reading
  and remains available if ..."
- "**I record this reading but do not take it as primary**" → state the reading
  as an answer in its own labelled section, then rank.

None of these three rewrites applies when the sheet asked for the exclusion. A
part that says why a competing pathway is not observed, not favoured or not
necessary owes exactly the sentence this section removes; there, the rewrite is
to add the conventional statement in front of it, and to leave the exclusion
standing behind it word for word.

## Before you close the stage

- Every eliminated candidate that is a conventional reading has a granted-reading
  paragraph stating it straight.
- No conventional parameter range has been replaced by a committed value that
  falls outside it; where it has been narrowed, both appear.
- Every reassignment across a set is shown against the conventional assignment,
  cell by cell.
- Searching your own text for "not", "eliminated", "excluded", "rather than" and
  "minority" returns no sentence whose only job is to remove a named mechanism —
  **except where the sheet asked for that sentence.** When a part or a criterion
  asks *why* a competing path does not operate, does not dominate, or is not
  detected, the exclusion is the answer and deleting it deletes a scored item.
  Put the granted-reading paragraph **before** it, never in place of it: state
  the competing path straight, then give the argument that rules it out. The
  sentence this checklist is hunting is the one that removes a mechanism nobody
  asked you to remove.

## Why this is here

Measured on the sixty-task FrontierScience-Research trial, judged by gpt-5.1 at
high effort. The pipeline arm's per-item reasoning was re-obtained by re-judging
under the same prompt template; four of eight biology re-judgements reproduced
the recorded totals digit for digit, and the rest were within 1.0 with a mean
absolute difference of 0.29. **On its four biology tasks this is the only
mechanism in the trial with quoted per-item reasoning on both arms.** Its two
chemistry tasks are not in that position — only the control arm's judgement
survives on disk for either — and the chemistry section below says where that
makes the attribution an inference.

Four biology tasks, **7.0 points**, all the same shape:

- **fs:044**, items 1B, 2A and 2C, one point each. Control: `Part 2B heading ...
  explicitly stated. Points: 1.0`. Pipeline: `Identifies Protein 1 as [a
  different node] ... Points: 0.0`, and the criterion for the motif scan was
  marked `the motif scan is generic and tied to the student's proposed target
  ... Points: 0.0`. The commitment is traceable: a contrarian lens statement
  ends with a clause that explicitly rules one reading out, it was scored
  relevance 6 into the stage, and the reviewer endorsed it.
- **fs:054**, items 3 and 9, −2.0. The two criteria pin one technique to one
  scenario. Control: `Scenario 2 is explicitly assigned to ... Score: 1.0`.
  Pipeline: `Scenario 2 ... is answered with [another technique] ... Score: 0.0`
  — moved on the strength of the run's own rule, quoted in its answer as `the
  combined score is 0.833 against 0.750`. No-reuse across scenarios turned one
  swap into two lost points.
- **fs:058**, −1.0. Control hedged and scored: `"If [the stated condition]
  holds, the intended answer is ..." Score: 1`. The pipeline wrote instead that
  the reading was eliminated by another part's own design, and was scored
  `explicitly eliminating ... Score: 0.0`.
- **fs:056**, −1.0. Pipeline: `The explanation directly rejects [the rationale
  the criterion asks for] ... 0.0/1.0` — **and it was scientifically right**.
  Correcting the expected rationale cost exactly one point.

The mirror confirms the mechanism rather than the arm: on fs:047 it was the
**control** that wrote a "better described as ... than as ..." refinement and
scored 0.0 where the pipeline's plain statement took 1.0, and on fs:052 the
control's explicit rejection of a stated alternative scored 0/1.25 against the
pipeline's 1.25/1.25. Across the twenty biology answers, explicit-elimination
phrasing runs at 0.28 per ten thousand characters in the pipeline arm against
0.10 in the control — 2.8 times.

**Checked against what chemistry pays for — and this is the one skill of the
five with a known risk surface in chemistry.** Take the benefit first. The two
chemistry losses in the trial are the same shape as the four biology ones.
fs:024, −1.000, item 4: the control was given `Partial credit: 0.5/1.0` for
keeping the conventional reading alongside its own variants; the pipeline
replaced it with a single committed value, and the conventional reading appears
**0 times** in its answer against 1 in the control. fs:033, −1.170 as a task
total (8.17 to 7.00): here the attribution to items 4 and 5 is **inferred, and
the inference is flagged** — the pipeline arm's per-item reasoning for this task
was overwritten on disk and both arms' score records now point at the surviving
judgement of the other arm, so what is checkable is the two totals and the fact
that the pipeline's own answer names the mechanism the criteria ask for and then
demotes it in the following sentence. No grader sentence about that demotion
exists to quote. Granting the reading first would have kept both statements
without changing either commitment.

Now the risk. Three chemistry criteria across two tasks, one rubric point each,
pay for an exclusion: they ask the answer to say why a competing pathway is not
the operative one, and the sentence that does that is exactly the sentence the
closing checklist tells a writer to hunt for. One of those two tasks is fs:033
itself, which passed at exactly 7.0 against a 7.0 threshold, inside the ±0.33
single-draw noise band; the other is fs:036, a +1.500 chemistry win for the
pipeline. Applied mechanically — delete
every sentence whose job is to remove a named mechanism — this skill would take
points off both. That is why the checklist carries the carve-out above and why
the three rewrites are stated as *add in front of*, never *replace*. This is the
skill to withdraw first if the next trial's chemistry number moves down.

Beyond that surface, nothing here compresses a ledger, merges an opposing pair,
or moves a verdict sentence later; it adds one paragraph per elimination.
