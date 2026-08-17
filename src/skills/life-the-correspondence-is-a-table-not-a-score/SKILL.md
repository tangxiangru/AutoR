---
name: life-the-correspondence-is-a-table-not-a-score
description: Use at implementation, analysis and writing when the task's named output is a correspondence between the parts of two objects — chain-to-chain pairings, matched cells, mapped reads, docked poses, aligned residues — and it is about to be reported as one best-match score. Covers the per-row record schema including unmatched parts and every column the tool emits, and the numbers computed across rows: coverage, spread of the auxiliary fields, and whether the per-part transforms agree.
stages: 04_implementation, 06_analysis, 07_writing
---

# The correspondence is a table, not a score

A matcher — a structural aligner, a chain mapper, a cell-type matcher, a read
mapper, a pose ranker — emits one record per candidate correspondence between
the parts of two objects. When the task's named output *is* that correspondence,
the set of records is the deliverable. A best-match scalar cannot stand in for
it, and neither can a heatmap.

## What goes wrong

The same deliverable is lost three times, at three stages, and each loss is
cheap to prevent.

**Implementation — a parser that keeps the fields it wanted and bins the rest.**
The tool's tabular report is read into a schema with named columns for the score
and the two identifiers, and placeholder names — `col9`, `col10`, `extra` — for
everything after them. The transform, the per-pair error, the per-pair identity,
the per-pair cost are discarded at the point of parsing, and nothing downstream
can recover them. A second variant: the field is genuinely absent because the
convenience one-shot command does not emit it, nobody checks the tool's other
output modes, and the quantity is later described in the report as unavailable.

**Analysis — nothing is computed across the rows.** The records survive to disk;
a figure script may even plot the per-part matrix. The quantities that turn a
dump into a result — how many matched, how consistent the per-part solutions
are, how the auxiliary fields are distributed — exist nowhere in the run, so the
writing stage cannot print them. `publish-what-the-run-already-computed` is the
general sweep that finds unpublished outputs; this skill is the specific row
schema and the specific across-row numbers.

**Writing — the argmax substitutes for the table.** The report gives one scalar
and one identifier pair: *score 0.0X, best pair Q1->T1*. From that a reader
cannot tell how many parts matched, which were left out, or whether the per-part
solutions agree with each other.

## What to produce

### 1. One row per candidate correspondence

One artifact per aligned instance (`outputs/<instance>_record.json`, plus a flat
TSV), with a row for every candidate the tool considered *and* a row for every
part left unmatched, partner field empty. Columns:

- identifier on the query side, identifier on the target side, `paired` boolean;
- the score under **every** normalisation the tool offers, not only the one you
  prefer, with the denominator named in the column header;
- the transform in full — every element of the rotation/affine matrix and every
  element of the translation — with the convention written beside it (row- or
  column-major, `X = t + Ux` or `X = Ux + t`);
- the size fields the score divides by: parts or residues on each side, aligned
  length, coverage;
- every auxiliary per-pair measurement the tool reports: error, identity,
  e-value, rank, assignment index;
- the cost of producing the row, if the tool reports per-pair cost.

No placeholder column names survive into the artifact. Open the tool's output
specification, name every field it documents, and if a field the task's output
list mentions is missing from what you captured, re-invoke in the mode that
emits it before concluding it is unavailable — a one-shot wrapper routinely
deletes the per-pair file that carries exactly these columns.

### 2. The across-row numbers

Computed from the table and stated in prose, not left for the reader to infer.

1. **Count and coverage.** How many correspondences were returned, and what
   fraction of the query's parts and of the target's parts that covers. Name the
   parts left out.
2. **Spread of each auxiliary field.** Mean and min–max range across matched
   rows, one sentence each. Where your field has a conventional interpretive
   cut-off for that quantity — an identity below which the cheaper method is not
   expected to detect the relationship, an error above which a fit is
   meaningless — say where your rows sit relative to it and cite where the
   cut-off comes from.
3. **Do the transforms agree?** Most matchers of this kind work because true
   correspondences share one superposition; the clustering or consensus step is
   the method's operating principle. Nobody tests it. Compute the element-wise
   spread of the rotation entries, the range of each translation component, or
   the maximum pairwise rotation angle between rows, and state in one sentence
   whether the matched rows are one solution or several. That sentence is the
   run's only empirical evidence for or against the principle the method rests
   on, and it is a few lines of numpy over a table you already have.
4. **The incumbent's per-row score is another column in the same table.** Put it
   there; `life-benchmark-against-the-incumbent` specifies the paired statistics
   that then go in the text. Two threshold-crossing counts are not a paired
   comparison.

### 3. When the named instance's table is degenerate

If the instance the task named returns one paired row, or none, print its table
anyway — unmatched rows explicit, reason measured rather than inferred — because
that instance is the graded one (`the-supplied-item-is-the-graded-unit`). Then
compute the across-row numbers on the instances where the matcher does fire, at
the same depth (`the-firing-instance-gets-the-full-record`). A one-row table on
a negative satisfies the letter of this skill and measures nothing.

## Checklist

- [ ] One row per candidate correspondence, unmatched parts included, for every instance aligned.
- [ ] Every field in the tool's documented output is a named column; no `colN` placeholders, nothing dropped as uninteresting.
- [ ] A missing field was chased into another invocation mode before being called unavailable.
- [ ] All score normalisations present, each with its denominator named.
- [ ] Full transform per row, convention stated.
- [ ] Count, coverage on both sides, and the named unmatched parts, in prose.
- [ ] Mean and range for every auxiliary field, placed against a cited conventional cut-off.
- [ ] An explicit statement of whether the transforms agree across rows, with the dispersion number behind it.
- [ ] Incumbent's per-row score in the same table.
- [ ] The table appears in the results section for the named instance, not only in an appendix.
