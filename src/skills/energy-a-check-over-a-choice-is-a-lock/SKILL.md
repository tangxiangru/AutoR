---
name: energy-a-check-over-a-choice-is-a-lock
description: Use at implementation and experimentation when you are about to add a cross-artifact consistency check, a self-test, a guard or a tripwire to your own pipeline. Covers the one question that separates a guard from a ratchet, how to pin a chosen quantity without freezing it, and why scope and coverage decisions must never be asserted in code.
applies_when: geospatial levelized-cost
stages: 04_implementation, 05_experimentation
---

# A check over a choice is a lock, not a guard

Cross-artifact checking is among the most valuable things a long run does. Files
written hours apart drift, a number gets transcribed into three places, a pointer
outlives the file it names, and a suite that catches this is worth its length.
But the machinery is indifferent to what you point it at, and pointing it at the
wrong class of statement produces something that looks identical, passes review,
and quietly removes your ability to improve the study.

A guard belongs on statements that are true whatever you decided: a total equals
the sum of its parts, a unit conversion round-trips, every identifier a document
cites resolves, a pointer names a file that exists, two artifacts holding the
same number agree, a residual sits under a tolerance fixed in advance. Point the
same machinery at a **choice** — the scope you settled, the population you kept,
how many countries or cells you covered, which cases you excluded, the wording of
a decision — and you have not built a guard. You have built a ratchet, and it
points away from the fix.

## The question to ask before adding a check

**If this run gets better, does this check go red?**

If the answer is yes, you are about to make improvement more expensive than
standing still, at the exact moment — mid-run, tired, with a suite you trust —
when the cheapest way to keep everything green is to leave the study as it is. A
check that fires on progress will not be argued with. It will be obeyed.

## How to pin a chosen quantity without freezing it

- **Assert agreement between artifacts, never equality to a literal you typed.**
  "the coverage table and the design pins name the same uncovered set" survives
  an improvement. "the coverage table has the row count it had this morning"
  does not.
- **Make the check print the number rather than assert it.** A line of output
  reading `coverage: <covered> of <total>` gives you the same protection against
  silent drift, appears in the log where a later stage will read it, and costs
  nothing the day you widen.
- **Never encode a decision's wording.** A ban list of phrasings that no later
  artifact may contain is a decision defended by string matching. The next
  stage's honest sentence about changing course is indistinguishable, to a
  matcher, from the failure mode you were guarding against.
- **Tolerances are fine; populations are not.** Freezing "the closure residual
  must stay under 0.01" before any result exists is exactly right. Freezing
  "the site set is the one the sample shipped with" is the same syntax doing the
  opposite job.

## The decisions most likely to need reversing are the ones taken first

Rank your locked decisions by how likely the next stage's evidence is to
overturn them. Scope, population, coverage, admissibility and extent sit at the
top of that ranking every time, because they are decided earliest, on the least
information, before a single result exists. Those get a *review point* — a line
in the ledger saying which measurement would reopen them — and never a gate.
Decisions about units, provenance, naming and arithmetic identity sit at the
bottom, and those are what the suite is for.

Budget the machinery, too. Count the lines that check against the lines that
model. `the-results-panel-is-not-where-the-run-argues-with-itself` makes the same
count over figures and sections; this is the same imbalance one layer down, where
it is not merely displacement but obstruction.

## Why this is here

Energy_002. `code/s01_artifact_consistency_check.py` is 1,263 lines against the
762 of `code/s04_lcoh_model.py`, the cost model the whole study exists to run,
inside 13,930 lines of Python. Its check 14a asserts that the country arm covers
twenty-seven of thirty-one countries and that a named set of four is uncovered,
so a run that widened its own coverage would first have had to edit the test that
says it did not. A second block bans twelve separate phrasings of one decision
being reversed — "drop reading b", "reading b need not be carried", and ten more
— matched whitespace-normalised across every prose note and every stage summary,
with an explicit tagged exemption so that a correction record may quote the
wording it removed. The heaviest thing the task was graded on, at weight 0.40,
was whether delivered cost varied across the continent the brief names; this run
scored 19.3 against a plain agent's 55.0, on a study that never left the box its
supplied sample came in.
