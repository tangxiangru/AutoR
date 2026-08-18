---
name: bind-every-deliverable-to-the-file-that-is-graded
description: Use at hypothesis generation when the run's whole output will be read out of one file and a reviewer has to approve the stage before anything is written, and you are about to describe in a stage summary what you produced. Covers writing the graded file first, naming only paths that already resolve, binding every coverage locator to the graded file rather than to a report that nobody opens, and the two sentences that get a stage sent back twice and the question forfeited.
applies_when: intermediate derivations
stages: 02_hypothesis_generation
---

# Nothing you promise counts until it is at the path that gets opened

Only one file is read. Everything else in the run directory — the plan, the
manifest, the coverage record, the report — exists to say something true about
that one file. A stage summary that describes deliverables sitting somewhere
else is not a summary of your work; it is a claim that will be checked, and it
fails on the first path that does not resolve.

The failure is not that the work was bad. It is that the stage was sent back
twice over its bookkeeping, and a run with no approved stage produces no answer
at all. A forfeited question scores zero no matter how good the physics was.

## Write the graded file first

Before you write one line of the stage summary, the file that gets read has to
exist on disk with its real content in it. Not an outline, not a placeholder,
not a section list. The order is: solve, write the answer file, then describe
what you wrote.

Writing the summary first produces a specific and fatal sentence — a promise in
the past tense about a file that does not exist yet. It reads as complete and it
is unverifiable, and it is the single most common reason the stage does not clear.

## Every path you name must already resolve

Read your own summary back and pull out every path in it. For each one, check
that the file is there, from the run root, spelled exactly as written. Then:

- **It exists** — keep the sentence.
- **It does not exist** — either create it now, or delete the sentence. Not
  soften it, not move it to future tense. Delete it.

Directories you invented while planning are the usual offender: a derivations
folder, a code folder, a notes folder that the plan assumed and nothing created.
Naming three of them costs three separate objections in one review.

## Bind the coverage record to the graded file

Every coverage locator has to point at a heading that exists **in the graded
file**. A locator that points into a report is a statement that the report is
the deliverable, and the reviewer will say so, correctly. If a section is worth
listing in the coverage record, it is worth having a heading of that name in the
file that is read.

Check each locator by opening the graded file and finding the heading. Not by
remembering that you meant to write it.

## Claim only the fields the record actually has

Do not advertise properties a record does not carry. If your summary says the
manifest carries provenance, dependencies, a prior expectation, or a
what-would-surprise-me field, then either those keys are populated in it or the
sentence comes out. A description of a schema that the file does not have is
the second most common objection, and it is entirely self-inflicted: it costs
nothing to describe the file you wrote instead of the file you designed.

## Make the summary's results about the question

Objective, what you did, key results: each of the three has to be about the
scientific question, and the results section has to contain statements a reader
could disagree with — a value, a sign, a mechanism, a choice between two
readings. A results section that reports which artifacts were produced is a
manifest with a different heading, and it is what makes a summary read as
structurally incomplete no matter how many times it is repaired.

## Before you close the stage

- The graded file exists and contains the finished answer, right now.
- Every path in the summary resolves from the run root, spelled as written.
- Every coverage locator names a heading that is in the graded file.
- No sentence describes a field the record does not carry.
- Key results are claims about the question, not a list of files.
- The summary has each of its required sections, non-empty, in order.

## Why this is here

Measured on the sixty-task FrontierScience-Research trial, one Claude Opus draw
per task, judged by gpt-5.1 at high effort. The pipeline arm produced no answer
on **14 of 60 tasks**; 13 of those ended as `driver:no_approved_stage`, and the
synthesiser refused because zero stages had been approved. Four of the thirteen
were provider-side refusals of the stage prompt itself and are outside what any
craft advice can reach. **Nine were review send-backs and summary-shape
failures**, which is what this is for.

Both send-backs on fs:007 and fs:017 are bookkeeping, verbatim. fs:007, second
review: `Fix the paths. "Derivations: notes/typed_claims_T_and_C.json" and
"code/pilot_fisher.py, code/pilot_bias_operator.py" do not resolve from the run
root; there is no code/ or notes/ there. ... either populate
derived_from/depends_on in the manifest or stop advertising "prior expectation,
what-would-surprise-me, dependencies" for a file whose schema has no such
fields.` fs:017, second review, carry-forward: `answer.md is the graded
deliverable and deliverables_coverage.json binds its seven where locators to
report.md only. Bind them to answer.md as well.` Neither objection is about
science. Both runs spent `sendback_count = 2` and forfeited the question.

The control arm passed four of the forfeited tasks outright — fs:007 at 7.0,
fs:017 at 7.6, fs:049 at 9.25, fs:057 at 8.94 against a 7.0 threshold. fs:057
never reached review at all: two attempts, 2,827 s and 212,219 output tokens,
and the log ends `Repair output for Stage 02 ... is still incomplete.
Normalizing locally... / Local normalization ... is still incomplete. Re-running
the stage... / Stage 02 ... was stopped by the run supervisor: the auto-skip
budget (0) is spent.`

Refusals are not spread evenly: physics 7 of 20, biology 4 of 20, chemistry 3 of
20. They are the largest single subject-level asymmetry in the trial, and they
account for the whole of the pipeline's physics and biology accuracy deficit.
On the tasks where it did produce an answer the pipeline passed 30 of 46 — so
recovering nine forfeits is worth about six tasks, roughly ten points of overall
accuracy. The entire score-level effect measured over the 43 complete pairs is
+0.085 points per task.

**Checked against what chemistry pays for.** Nothing here touches the content of
an answer: it adds no compression, merges no rows, moves no conclusion. It makes
the enumerated per-part working exist on disk earlier, which is the thing
chemistry is paid for. Three chemistry passes sit at exactly 7.0 against a 7.0
threshold, and this skill cannot move a score down by a tenth — it can only turn
a zero into a score.

This is the run-bookkeeping half of what `a-deliverable-is-not-an-instruction`
and `cover-what-the-task-named` do at study design and writing; those two route
to stages that a single-stage configuration never reaches, and neither of them
says which file the locators must bind to.
