---
name: paper-writing
description: Use when drafting, structuring or revising the manuscript or report in Stage 07 (Writing) — shaping the contribution into one story, writing the abstract and introduction, fixing prose that reads generic or templated, ordering sentences for clarity, or deciding what Figure 1 should show.
stages: 07_writing
---

# Paper writing

Stage 07 turns approved stage summaries into a manuscript. The failure mode is
not bad grammar — it is a draft that reports what was done instead of arguing
one claim. This skill is the correction for that.

`reference.md` in this directory is the long-form treatment: reviewer reading
order, the seven sentence-level principles from Gopen and Swan, mathematical
notation habits, figure design, and a pre-submission checklist. Read it when a
specific problem below is the one you have.

## Start here: the one-sentence contribution

Before drafting anything, write the paper's claim as one sentence:

- "We prove that X converges under assumption Y."
- "We show that method A improves B by 15% on benchmark C."
- "We identify failure mode D and propose mechanism E that removes it."

If you cannot write it, the framing has not converged, and no amount of prose
will fix that. Go back to the Stage 02 hypothesis manifest and the Stage 06
analysis and find out which claim the evidence actually supports. Writing
around a claim the results do not support is the most expensive mistake
available at this stage.

Every section then serves that one claim. Related work, experiments and
discussion support it; they are not independent mini-papers.

## The abstract, in five sentences

1. What is the general problem area, in one line a non-specialist follows.
2. What is the specific gap or failure this paper addresses.
3. What did you do — the method, named and characterised.
4. What did you find — the headline number or result, stated concretely.
5. Why it matters — what changes for someone in the field.

Delete openings that carry no information: "With the rapid development of…",
"In recent years, X has attracted increasing attention…". Start at sentence 1.

## Introduction

By the end of the introduction the reader must have:

- **The what** — the 1-3 specific claims,
- **The why** — the evidence backing them,
- **The so what** — why the community should care.

Contribution bullets state results, not activities. "We conduct extensive
experiments on three datasets" is an activity. "We show retrieval recovers 12
points of accuracy that long-context prompting loses when evidence is diffuse"
is a result.

## Prose that reads as generic

Symptoms and fixes, in order of how often they apply:

| Symptom | Fix |
| --- | --- |
| Hedging stacked on hedging ("may potentially suggest") | State the claim, or state the limitation. Not both in one clause. |
| Vague quantifiers ("significantly better", "a variety of") | Replace with the number. If there is no number, say what you actually observed. |
| Ambiguous pronouns ("this shows…") | Name the referent: "this gap shows…". |
| Verb buried at the end of a long sentence | Move the verb early; readers hold the subject in memory until they get it. |
| Terminology drifting across sections | Pick one term per concept and use it everywhere. Synonyms read as different concepts. |
| Every paragraph the same length and shape | Vary it. Uniform paragraph shape is the strongest tell of generated prose. |

## Where to spend the effort

Roughly equal time on: the title and abstract; the introduction; the figures;
and everything else combined. Reviewers usually read title → abstract →
figures → introduction → results, and form a verdict before the method
section. Front-load accordingly.

## Before you finish the stage

- Does the abstract's claim match what Stage 06 actually measured?
- Does every claim in the introduction have a pointer to evidence in the run?
- Are limitations stated, in the paper's own voice, rather than implied?
- Would the paper survive a reader who reads only the figures and captions?

For citation handling use the `citation-discipline` skill. For venue-specific
required sections use `venue-checklist`.
