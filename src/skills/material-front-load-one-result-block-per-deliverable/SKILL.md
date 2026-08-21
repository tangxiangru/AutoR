---
name: material-front-load-one-result-block-per-deliverable
description: Use at study design when the results outline is locked, and again at writing, when the report opens with an abstract, a data audit or a mechanism section and a figure-bearing deliverable is first referenced behind them. Covers the block-per-deliverable layout, the character-offset audit of report.md that proves it held, and the repair order when the audit fails.
benchmarks: researchclawbench
stages: 03_study_design, 07_writing
---

# One self-contained result block per deliverable, and the offset audit that proves it

The failure: the results section is ordered by the run's narrative - the most
interesting finding first, then the mechanism that explains it, then a validation
of the pipeline, then whatever deliverables are left. A named deliverable ends up
past the halfway mark, behind a long abstract, a data forensics section and an
external anchor. Its figure exists and is correct. A reader working front-to-back
with a bounded budget forms a view of what the run produced from the opening, and
the workflows named there are the ones the report is taken to be about.

This bites hardest on the deliverables whose result *is* a figure. A panel is read
together with the prose around it, so a correct figure introduced after four pages
of audit vocabulary is read as one more audit exhibit. Text-scored results are
read further down the file and are not fixed by moving them; do not expect
reordering to buy anything for a deliverable whose problem is that the number is
missing or dimensionless.

Three neighbouring arguments are already in the library and are not repeated here:
run the requested analysis at all (`run-the-requested-analysis`), the audit must
not take the title or the abstract's first sentence
(`material-as-specified-run-and-stage-diagnostics`), and what has to be inside a
panel (the object-over-reference figure gate). This skill is only about *where*
the blocks sit, and the check that proves it.

## The layout

1. **Abstract**: one sentence per named deliverable, in the task's order, each
   carrying that deliverable's landmark scalar in its physical unit and its
   comparison. The framing device, the protocol and what is wrong with the inputs
   do not get the opening sentences.
2. **Results: one section per named deliverable, in the task's order, contiguous.**
   Nothing interleaved - no mechanism section, no data forensics, no pipeline
   validation, no external benchmark anchor between two deliverables. Those are
   real contributions and they are numbered after the last deliverable section.
3. Each deliverable section reads on one screen: one sentence naming the workflow
   and the configuration it ran at, with the shipped constants quoted by value;
   the object figure, referenced immediately; the landmark scalars in physical
   units with their comparison; one sentence of interpretation, including a null
   one if that is the result.
4. Data, methods, mechanism, audits, limitations: after.

## The offset audit

An ordering intention does not survive drafting. Measure the file you actually
wrote:

```python
import re, pathlib
t = pathlib.Path("report/report.md").read_text()
for m in re.finditer(r"(?m)^#{1,4} .*$|!\[[^\]]*\]\([^)]+\)|Figure\s+\d+", t):
    print(f"{m.start():7d}  {m.group(0)[:90]}")
print("total characters:", len(t))
```

Read the printout against the deliverable list you extracted from the task
statement, and require three things:

- **every named deliverable's first figure reference before character 10,000** -
  an absolute budget, two to three printed pages, about as far as a bounded reader
  gets before their view of the run sets. "In the first half" is not the check: in
  a long report the halfway mark sits far past that point, so a reference that has
  already lost the reader passes the test;
- **every deliverable's figure reference before the first heading that is not a
  deliverable**;
- **nothing between the first and the last deliverable heading** that is about the
  inputs, the pipeline, or the run's own process. This is the clause that catches a
  mechanism section or an external anchor sitting between two deliverables and
  pushing the later one out of the budget.

## The repair, when the audit fails

In this order, and none of them is deleting a deliverable:

1. cut the abstract to one sentence per deliverable - a long abstract spends the
   whole budget before the first result;
2. move mechanism, forensics, pipeline validation and external anchors to after
   the last deliverable heading, unchanged;
3. move per-deliverable methods prose into a methods section at the back, leaving
   the one configuration sentence in place;
4. re-run the audit and print the new offsets. If a deliverable still misses the
   budget, the report has more front matter than it can afford.

## Adjacency

The sentence immediately before each figure states, in words, the physical content
of the picture: what is plotted against what, in what unit, and what the reader
should see. A figure whose only nearby text is a caption of protocol prose is read
as belonging to whatever section surrounds it. Do not stack figures - four in a row
with no result sentence between them collapse into one exhibit.

## Checklist before the report is final

- [ ] The offset printout is in the run log, not only in your head.
- [ ] Every named deliverable has a heading, in the task's order, and those headings are contiguous.
- [ ] Every deliverable's first figure reference is before character 10,000 and before the first non-deliverable heading.
- [ ] The abstract names every deliverable, each with a number in a physical unit.
- [ ] No figure sits more than two sentences from the sentence stating its physical result.
- [ ] Reading only as far as the first non-deliverable heading, a reader can list every workflow the run ran and one number for each.
