---
name: a-value-you-did-not-measure-still-has-a-source
description: Use at Stage 06 and Stage 07 when a deliverable the task named cannot be produced by this run at all — a wet-lab measurement, a synthesised material, a proprietary benchmark, hardware you do not have. Covers the difference between fabricating a number and citing one, where the cited value belongs, and why omitting the section is the worst of the three options.
applies_when: \b(synthesi[sz]\w*|wet[-\s]?lab|in\s+vivo|in\s+vitro|experimentally|experimental (?:validation|verification|measurement|characteri[sz]ation))\b
stages: 03_study_design, 06_analysis, 07_writing
---

# Not measuring something is not the same as having nothing to say about it

Some tasks name a deliverable this run cannot produce. The study asks for a
synthesised polymer and a DSC trace; you have no bench. It asks for a run on
hardware you do not have, or a benchmark behind a licence, or an experiment that
takes six weeks.

There are three things you can do, and they are not close in value:

1. **Omit it.** The section does not exist. To a reader this is indistinguishable
   from a run that forgot, and it is scored as absence.
2. **Name the gap.** One paragraph: this was asked for, it could not be done,
   here is why. Honest, and better than silence.
3. **Report the field's own answer, attributed, and position your work against
   it.** The value exists — in the source study, in a reference database, in a
   handbook. Give it, say whose it is, and show what your work does and does not
   establish about it.

The third is what a real paper does. A methods section that needs a melting point
it did not measure cites one. A benchmark table with a row you could not run gives
the published figure with a citation and a footnote. This is ordinary scholarly
practice, and it is the difference between a section that says nothing and a
section that positions the run's contribution in the literature.

## Fabrication and citation are different acts

The rule you are working under is that no number in the report may be invented,
estimated, or narrated into existence: every quantity traces to something. That
rule is correct and this does not weaken it. **A published value has a source; it
is traceable; it is not an invention.** What makes the difference is entirely in
how it is carried:

- **Attributed.** "Zheng et al. measured DSC 317 K and TMA 311 K on their
  synthesised candidate (ref. 4, Fig. 5)."
- **Labelled where it appears.** In a figure, the external value is a separately
  styled band or marker with the source in the legend — never a series that reads
  as one of yours. In a table, a `source` column.
- **Never counted as validation of your own pipeline.** The published number is
  the target your work is compared against, not evidence that your work is right.

A number carried that way is a citation. The same number carried as your own
measurement is a fabrication. The line is bright and it is about labelling.

## Plotting the value is not enough; you have to stand next to it

The near-miss is worth naming because it looks like the right answer. A run puts
the published band on a figure, and then captions it "carried as an external
reference, and never as a validation of this run" — and the section still reads as
a refusal, because nothing of the run's own is placed against the band. A reader
sees a number that belongs to someone else and no claim.

The version that works puts the run's own quantity in the same frame and states
the distance: "our pipeline predicts 355 K against the 311-317 K they measured —
0.8σ of our uncertainty budget." Same published number, same honesty about who
measured what, and now there is a result in the sentence.

The disclaimer is still correct and still belongs there. It goes *after* the
comparison, as a qualification of it, not instead of it.

## Then say what your work does establish about it

This is the part that turns a citation into a result. You could not synthesise the
candidate — but you designed it, and you have a predicted property with an
uncertainty. Put the prediction and the published measurement in the same figure
and state the deviation. You could not run the licensed benchmark — but you have
your metric on the open subset, and the source reports both, so the offset between
them is estimable.

The section then reads: this is what was asked, this is what the field has
measured, this is what this run predicts, this is the gap between them, and this
is what would close it. That is a contribution. "Not attempted" is not.

## Where it goes

In the section a reader looks in for the answer — under the heading the task's own
words would send them to — not in Limitations. Limitations gets a cross-reference.
A deliverable answered only in Limitations has been answered in the one place a
reader goes to find out what the run failed at.

## The check

For each named deliverable the run could not produce: is there a section under a
heading a reader would look for, containing the field's value with its source, this
run's nearest evidence, and the distance between them? If the answer is "it is
mentioned in Limitations", it is not done.

See also `cover-what-the-task-named` for enumerating deliverables in the first
place, and `citation-discipline` for how the source is recorded once you cite it.
