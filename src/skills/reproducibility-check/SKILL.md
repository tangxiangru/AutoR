---
name: reproducibility-check
description: Use in Stage 08 (Dissemination) when assembling the release or submission bundle — auditing whether the run's code, data, results and figures are actually reproducible by someone else, writing the readiness checklist and threats-to-validity notes, or deciding what has to be disclosed as not verified.
---

# Reproducibility check

Stage 08 must write review and readiness artifacts under `workspace/reviews/`.
The purpose is to state honestly what a third party could reproduce from this
run's directory alone — not to assert that everything is fine.

The output of this check is a record of what was **verified**, what was
**not verified**, and what is **known not to reproduce**. All three categories
are legitimate. Only a fourth is not: recording an unchecked item as verified.

## Audit the run directory as a stranger would

Work from `runs/<run_id>/` and assume no access to the conversation, the
operator's memory, or the environment the run happened in.

| Question | Where the answer must live |
| --- | --- |
| What was the research goal? | `user_input.txt` |
| What was actually run? | `workspace/code/` — scripts, not descriptions |
| What data went in? | `workspace/data/`, with provenance for anything downloaded |
| What came out? | `workspace/results/`, indexed by `experiment_manifest.json` |
| How do the figures relate to the results? | a script under `workspace/code/` that regenerates them |
| What decisions were made and why? | the decision ledger in the stage summaries |
| Which stages actually completed? | `run_manifest.json` — see below |

## Read the manifest before claiming the run is complete

`run_manifest.json` distinguishes stages that were **approved** from stages
that were **skipped**. A skipped stage has `skipped: true` and a `skip_kind`
of `human` or `auto`; an `auto` skip means the stage exhausted its retry budget
in an unattended run with nobody in the loop, and its work was never done.

A readiness review that reports a run as complete when a stage was auto-skipped
is wrong in the most damaging direction. List every skipped stage in the
readiness artifact, with its `skip_reason`, and say what downstream claim is
weakened by the gap.

## The checklist

For each item, record `verified`, `not_verified`, or `fails`, with a one-line
reason. Never leave an item without evidence for its status.

- **Environment** — is there a record of the Python version and any
  dependencies? A script that imports a package the run never declares is not
  reproducible.
- **Determinism** — are seeds set and recorded? If results vary run to run,
  say by how much.
- **Data provenance** — for each file in `workspace/data/`, where did it come
  from, and can someone else obtain it? "Generated synthetically" is a complete
  answer only if the generator is in `workspace/code/`.
- **Results regeneration** — does a script take the data to the results, or is
  there a gap where a manual step happened?
- **Figures** — same question, from results to figures.
- **Claims to evidence** — does every claim in the manuscript point at a file
  in the run? `citation_verification.json` covers external claims; this covers
  the run's own.
- **Compute** — what hardware and how long. Venues ask; see the
  `venue-checklist` skill.

## Threats to validity

Write these in the paper's own voice, not as a disclaimer appendix nobody
reads. The ones that matter most in an AutoR run:

- **Single-seed results** presented as if replicated.
- **A skipped or thin stage** upstream of the claim — especially Stage 05.
- **Baselines that were not tuned** to the same effort as the proposed method.
- **Evaluation on the data the method was developed against**, with no held-out
  split.
- **Claims that outran the experiment**: check the Stage 02 hypothesis
  manifest against what Stage 06 actually measured, and flag anything the
  manuscript asserts more strongly than the analysis supports.

## Before you finish

- Every checklist item has a status and a reason.
- Every skipped stage is named, with its kind and reason.
- Nothing is marked verified that you did not actually run or read.
- The bundle under `workspace/artifacts/` contains what the checklist says it
  contains.
