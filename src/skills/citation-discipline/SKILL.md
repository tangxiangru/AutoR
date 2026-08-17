---
name: citation-discipline
description: Use when adding, verifying or cleaning citations and BibTeX entries in Stage 07 (Writing), when a reference cannot be resolved cleanly from DBLP or CrossRef, when checking that a cited paper actually supports the claim attributed to it, or when filling citation_verification.json.
stages: 01_literature_survey, 07_writing
---

# Citation discipline

Stage 07 must write `workspace/artifacts/citation_verification.json`, and the
gate checks it has a non-empty `claim_coverage` list where every entry carries
a claim and at least one `citation_keys` or `source_ids` value. That file is a
record of verification, so it is only worth anything if verification happened.

`reference.md` in this directory is the long-form treatment: source APIs, the
full verification workflow, BibTeX field rules, entry templates by publication
type, and a troubleshooting table. Read it when a specific reference will not
resolve.

## The rule that matters most

**Never generate a citation from memory.**

The dangerous failure is not an obviously fake reference. It is one that looks
plausible: real authors with a fabricated title, a real title with the wrong
year, a real arXiv ID attached to the wrong venue, a preprint and its published
version silently merged into one entry. These survive a read-through and
surface during review.

If a citation cannot be verified programmatically or from the run's own
`workspace/literature/sources.json`, mark it unresolved and say so. Do not
produce a plausible-looking BibTeX entry to fill the hole.

## Verification loop

For each citation:

1. **Resolve** the work against a source of record — DBLP for CS venues,
   CrossRef for DOIs, the publisher page, or arXiv for preprints.
2. **Match the metadata exactly**: authors, title, year, venue. A mismatch in
   any one of them means you have the wrong record, not a typo to smooth over.
3. **Check the claim**. Open enough of the paper to confirm it says what you
   are attributing to it. A correctly-formatted citation for a claim the paper
   does not make is still a fabricated citation.
4. **Record it** in `citation_verification.json` with the claim it supports.

## The run already has evidence — use it

`workspace/literature/sources.json` and `claims.json` were built in Stage 01
with source IDs. A Stage 07 claim that traces back to a Stage 01 claim should
reuse its `source_id` rather than re-deriving a citation. If a Stage 07 claim
has no Stage 01 ancestor, that is worth noticing: it may be a claim the run
never gathered evidence for.

## BibTeX hygiene

- One entry per work. Prefer the published version; if citing the preprint,
  cite it *as* a preprint rather than dressing it as a conference paper.
- Keys are stable and mnemonic (`author2024shorttitle`), never renumbered.
- Do not leave both a DOI and a conflicting arXiv ID on the same entry.
- Keep entries compatible with the venue's existing template. Do not migrate a
  working bibliography to BibLaTeX mid-run.

## Before you finish the stage

- Every `\cite` key resolves to an entry in the `.bib`.
- Every entry in the `.bib` is cited at least once.
- `citation_verification.json` covers each substantive claim, not just the
  easy ones.
- No entry was written from memory. If any was, it is marked unresolved.
