---
name: claims-before-harness-forensics
description: Use at hypothesis generation and study design on reproduction and method-evaluation tasks, once close reading of the release has turned up defects, ambiguities or under-specification, and again when ordering the report. Covers labelling every planned experiment as a test of a claim or a test of self-consistency, the count gate that follows, and where reproduction-fidelity statistics belong.
stages: 02_hypothesis_generation, 03_study_design, 07_writing
---

# Claims before harness forensics

## The failure this prevents

Reading a release closely turns up real problems. A parameter documented two
ways. A configuration that returns fewer items than the protocol needs. A
headline comparison that changes two factors at once and therefore identifies
neither. An evaluator whose denominator moves with input size. These findings
are genuine, they are satisfying, and they are cheap — each one is a short
script against code you have already vendored.

So the run drifts. The frozen hypothesis set fills with tests of whether the
released code is self-consistent. Figure slots fill with protocol panels. The
headline numbers become agreement statistics: how many printed cells fell
inside a replicate band, how a published gap decomposes across a lattice, how
far two documented settings diverge. The first result in the abstract is a
reproduction-fidelity score.

Meanwhile the source's own claims — the ones anyone opening the report will
look for — never get a producer. What ships is a competent audit of somebody's
repository, submitted in place of an answer to the question. It is also
self-defeating in tone: a run that spent its budget locating where the method
is weaker than advertised has manufactured evidence against the claim it was
asked to establish, and says nothing about the conditions under which the claim
holds.

## Build the row list elsewhere

`run-the-conditions-the-source-ran` already gives the procedure: one row per
named system, scenario, stress axis, ablation and worked case study, with the
baselines it is compared against; run every row before any variant of your own;
a row you cannot run still gets its subsection. Do that first — this skill is
about what happens to that list when forensic work competes with it. Two
additions:

* The dataset shipped with the task is **one row, not the list.** Arms that
  live behind a generator or an accession are rows too, and they are usually
  the cheapest rows, because a generator gives exact ground truth at a size you
  choose.
* Do not plan around fetching. When an arm is out of reach, the cut is a
  locally written, scaled-down instance of **the same result class** — fewer
  units, fewer conditions, fewer replicates. The class is what the claim is
  about; the size is not.

## The C/F label

Label every planned hypothesis and every planned figure:

* **C** — it tests a claim the source makes about the world: this method beats
  those under this condition, this structure is recovered, this effect
  survives.
* **F** — it tests whether the released code or paper is internally consistent:
  a parameter specified twice, a config that truncates, an unidentified
  contrast, our numbers landing inside our own replicate bands.

F items rationalise into C if you let them, so use the operational test: **if
neither answer to this experiment can change whether the source's claim about
the world is true or false, it is F.** "Does the published contrast identify
the mechanism?" is F — the claim stands either way. "Does the method still lead
when the input is degraded?" is C.

Write the labelled table out as an artifact, with the two counts in it. A count
asserted in a stage summary is not auditable and will not survive contact with
the next stage's rewrite.

**The gate:** F must not outnumber C, and no F job enters the run queue while a
C row still has no producer. Apply it before the plan is frozen, when the fix
costs nothing.

## Forensics that belongs inside a row

A forensic finding that changes **how a claim row must be run** — a parameter,
a root, a denominator, a preprocessing choice — is not a separate result. It is
part of that row: reported inside it, and sized by its effect on the claim's
number rather than on its own scale.

A forensic finding with no consequence for any row is a real contribution and
gets a named subsection plus a limitations line — after the claim rows, not
before them.

## Report ordering

* The first two results a reader meets are claim rows: what the method
  achieves, on what, against what baseline, in the metric's own units.
* Reproduction-fidelity statistics — coverage counts, containment fractions,
  median absolute deviation from published values — are statements about **your
  harness**, not about the method. They belong in the reproduction section.
  They must not be the first number in the abstract and must not be the title
  of the main comparison figure; a headline that leads with a partial-coverage
  verdict is read as a declined reproduction whatever the tables underneath say.
* When a claim does not reproduce, report the shortfall **and** report what the
  claim does hold at: the level, the ordering, the margin. A run that reports
  only where the method fails has deleted the claim rather than measured it.
* An uncovered row is named in limitations, by name, with the source's number
  beside the blank.

## Relation to task-coverage discipline

`cover-what-the-task-named` keys coverage on the sentences you were handed;
this keys on the source's result classes. Both tables, kept separately. A run
can bind every clause of the brief to a measured artifact, declare full
coverage and be right about it, and still have left most of the source's
evidence base untouched — the brief is one paragraph and the study is six
experiments. (`material-as-specified-run-and-stage-diagnostics` carries the
same ordering rule for the narrower case of auditing a supplied protocol.)

## Checklist

- [ ] **hypothesis generation** — every candidate hypothesis carries a C or F
      label and the two counts are written down before the set is frozen.
- [ ] **hypothesis generation** — anything you quoted from the source about its
      own evidence base is a row with a producer, not a sentence in a novelty
      argument.
- [ ] **study design** — F does not outnumber C; every C row has a producer or
      a named scaled-down surrogate; F jobs are queued last.
- [ ] **writing** — the abstract opens on claim rows; fidelity statistics sit
      in the reproduction section and title no comparison figure.
- [ ] **writing** — every non-reproducing claim carries both the shortfall and
      the conditions under which it holds.
