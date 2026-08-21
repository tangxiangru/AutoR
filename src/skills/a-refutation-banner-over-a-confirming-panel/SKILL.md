---
name: a-refutation-banner-over-a-confirming-panel
description: Use at hypothesis freeze, and again after the last revision pass, when a run has found that the supplied data or your own reproduction disagrees with the source it names. Covers the branch-name test that stops an agreement being printed as a refutation, and the enumerate-and-search sweep that keeps fidelity verdicts and internal labels out of the title, the headings and the figure banners.
benchmarks: researchclawbench
stages: 02_hypothesis_generation, 07_writing
---

# A refutation banner over a confirming panel

## What goes wrong

You investigate the supplied bundle, find something real about it, and the finding is
sharper and easier to measure than the analysis you were asked for. Two library skills
already cover the consequence: run the requested analysis anyway and add the audit as its
own section (`run-the-requested-analysis`), and kill the cheap explanations for a gap
before calling it a disagreement (`close-the-gap-to-the-published-number`, whose first two
discriminators are units/normalisation and population/split). Read both.

This skill is the residue those two do not touch, and it is purely lexical: the word a
hypothesis branch is given before any data exists, and the words that end up in the few
slots a reader actually reads. Both are invisible from the inside. Both survive an
intention to avoid them - a run can carry an explicit written objective to lead with the
requested analysis, ship the fidelity verdict in its title anyway, and then spend its one
revision pass making that verdict more precise. Intent does not fire here. Enumerate and
search does.

## Check 1 - the branch-name test, at hypothesis freeze

Before any hypothesis is frozen, write one line for it:

> If the source's published claim is exactly true of my data, branch ____ fires, and that
> branch is called ____.

Read the branch name. If it contains *refuted*, *rejected*, *diverges*, *inconsistent*,
*not reproduced*, *fails*, *synthetic*, *surrogate* or *inauthentic*, the hypothesis's
subject is the file rather than the phenomenon, and every artifact downstream of it will
stamp a failure word across a panel whose data agrees with the source. Prose cannot undo
this: the heading and the figure banner are what get read.

The fix is to change the subject, not the wording. The hypothesis asks about the thing the
task named - does this variable dominate the response, does this ordering hold across
conditions, does this arm detect more - phrased so that the source's claim being true
fires a branch you would be happy to title a panel with.

Provenance hypotheses are legitimate and stay. They are *separate*: their own hypothesis
id, their own statistic, their own figure slot, their own section. The specific sentence
to refuse is any variant of "computed once, this statistic is both the deliverable and a
provenance test". A statistic with two jobs resolves as the audit every time, because the
audit is the branch with the interesting name.

## Check 2 - the verdict-word sweep, after the last revision

Do not do this by reading. Build the list, then search it.

1. Enumerate, as literal strings: the report title; the first two sentences of the
   abstract; every section and subsection heading; every figure suptitle and panel title;
   the first sentence of every caption.
2. Case-insensitively search each string for verdict words - refuted, supported, confirms,
   diverges, divergence, overshoots, undershoots, inflated, discrepancy, deviation, not
   reproduced, fails to reproduce, provenance, authentic, synthetic, surrogate,
   mislabelled - and for anything of the form "X vs published".
3. Search the same strings for internal labels: hypothesis ids, slot numbers, proposition
   or obligation ids, branch names, stage names.

Every hit is a defect unless it sits inside the single section that *is* the fidelity
accounting, or the word states the requested analysis's own outcome in plain language: an
exemption on that ground has to name the phenomenon and a number, so "H1 refuted" and "the
supplied numbers diverge from the published ones" do not qualify. Two fixes, and only
these two:

- **Internal label in a title.** Delete it. A reader has no copy of your numbering. The
  label belongs in the caption body or a plan appendix.
- **Verdict word in a title.** Replace it with what the panel or section shows, in the
  source's vocabulary and units. A suptitle states the quantity, the comparison and the
  conditions. It is not a place to adjudicate anything.

Then check the positive space, which is where the graded result usually went missing: for
every claim of the source's that your data speaks to, one plain sentence exists saying
whether your data reproduces it, with your number and the source's - **including every
claim that does reproduce**. A confirmation that appears only as the premise of a
refutation ("the effect sits where the source said it does, so the divergence hypothesis
fails") is not in the report as a result. Give it its own sentence, in the lead of the
section that owns it.

## Checklist

- [ ] Every frozen hypothesis has its branch-name line written, and no confirming branch
      carries a failure word.
- [ ] No statistic and no figure slot serves both a requested analysis and a provenance
      test.
- [ ] Title, abstract's first two sentences, all headings, all suptitles and panel titles,
      all caption openings: enumerated as a list and searched, not skimmed.
- [ ] Zero verdict words and zero internal labels among them, outside the one fidelity
      section.
- [ ] One sentence per source claim stating whether your data reproduces it, with both
      numbers, including the ones that agree.
- [ ] The fidelity finding is complete, in one place, and is not the first thing a reader
      meets.
