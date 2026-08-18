---
name: a-deliverable-is-not-an-instruction
description: Use at study design when listing the task's deliverables into report_plan.json, and again before writing when checking coverage. Covers how to tell a research deliverable from the harness's own operating instructions, why a padded list is worse than a short one, and what to write when a deliverable is genuinely out of reach.
stages: 03_study_design, 07_writing
---

# The sheet you were handed is two documents. Only one of them is the task.

A task statement that arrives through a harness is rarely only the task. Around
the research question sits a second document: how to operate, where to write
files, what not to do, what counts as finished. Both are addressed to you, both
are written in the imperative, and one of them is not a deliverable.

Enumerate the wrong one and the study is planned against phantoms.

## The failure this prevents

Measured on a forty-task benchmark arm: the deliverable list drawn off the whole
instruction sheet held **337 requirements; the research questions alone held 142**.
Fifty-eight per cent of what every run was planning against was the harness talking
about itself, and the same five phantoms appeared in all forty runs:

> Read & Understand — Study the related work and data to build domain context.
> Code & Execute — Implement the analysis, generate figures, and iterate…
> Analyze & Report — Interpret the results and produce a publication-quality report.
> Your primary goal is to … produce a high-quality `report/report.md`.
> Figures are mandatory — generate plots and save to `report/images/`.

Every one is a true instruction. Not one is a finding. A plan that answers
"Read & Understand" with `figure:2` has spent a figure slot on the fact that
reading happened.

The damage is not only wasted slots. A plan is checked for a *covering* answer to
each listed deliverable, so a list of seventeen forces seventeen answers out of a
study that has four results — and the entries that cannot be answered honestly get
answered emptily. An empty entry fails the gate, the stage is sent back, and a
stage sent back often enough is a stage that never happens.

## The test

For each imperative sentence, ask: **would the answer to this appear in the
published paper?**

| Sentence | In the paper? | Deliverable |
|:---|:---|:---|
| "derive upper limits on the coupling strength" | yes, a number with an interval | **yes** |
| "compare against the incumbent method" | yes, a table | **yes** |
| "report the distribution across all seven datasets" | yes, a figure | **yes** |
| "study the related work to build context" | no — everyone does this | no |
| "save all figures as PNG" | no — that is file format | no |
| "install python packages as needed" | no | no |
| "produce a high-quality report" | no — that is the container | no |

The distinction is not importance. Saving figures as PNG matters enormously; it is
just not a finding. Obey those instructions — they are how the work gets delivered
— and keep them out of the list of things the work *found*.

A second cue: a deliverable is task-specific. If the sentence would read identically
in a task about superconductors and a task about cloud seeding, it came from the
template, not from the study.

## Sizing the list

Three to six deliverables is the normal shape of a research task. If your list has
grown past ten, you are almost certainly enumerating the template. Re-read it and
cut, rather than inventing an answer for each.

Two entries that look like two deliverables are often one: "derive limits on masses
**and** coupling strengths" is two, because either can be present without the other;
"produce reproducible tables **and** figure-level evidence" is one result delivered
two ways. Split on *what could be missing independently*, not on the conjunction.

## When one is genuinely out of reach

Say so in the entry rather than leaving it blank or inventing a cover. Name the
deliverable, say exactly what is missing — the data was not supplied, the reference
implementation is not public, the compute is not there — and say what you did
instead.

**A blank entry is the worst of the three options.** It fails the plan gate, which
costs the stage; and if it survives, it claims coverage that does not exist. An
honest "not reachable, because X" costs nothing and is a sentence the report can
reuse in its limitations.

## Before you leave study design

- Every entry names something that would appear in a published paper.
- No entry would read identically in a task from another field.
- No entry is blank.
- The count is in single digits, and each one is answered by a figure, a number,
  or a named section — not by "prose" used as a placeholder.
