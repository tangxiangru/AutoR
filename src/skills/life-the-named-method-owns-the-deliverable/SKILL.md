---
name: life-the-named-method-owns-the-deliverable
description: Use at study design, experimentation and writing when the task's named output is an object some specific method produces — an alignment and its transform, a chain or read mapping, a docked pose, a called variant set — and you are also running the established tool for the same job. Covers which engine's object is the one printed, keeping the extracted-field set identical across engines, and what to do when the named method will not emit a field through the command you happened to use.
benchmarks: researchclawbench
stages: 03_study_design, 05_experimentation, 07_writing
applies_when: correspondence between chains|superimposition vectors
---

# The object in the report comes out of the method the task is about

Running the established tool beside the new one is right, and a life-science
result is a head-to-head. But the head-to-head is a *comparison* of two
producers of the same object, and the object itself — the transform, the
mapping, the call set, the pose — belongs to the method the task names. The
incumbent is a column beside it, never the source of the printed thing.

## Nobody decides this; the parser decides it

The failure never happens at design time. It happens at the parse.

The incumbent is thirty years old and has a documented flag that writes its
rotation matrix to a file. The method under study emits one tabular report, and
you wrote a reader for the two columns you needed that afternoon — the score and
the identifiers. So the record on disk holds eight named fields for the
incumbent and three for the method. Every later stage can only report what is in
the record. By the writing stage the results section, the appendix table and the
figure panel all print the incumbent's object, because it is the only complete
one, and the deliverable the task named has quietly changed hands.

The tell is a per-engine record whose key sets are not equal. It is silent: no
error, no empty cell, no counter.

## One schema, filled for every engine

Before any engine runs, write the field list the named deliverable requires —
from the task statement's own output list, not from what a tool happens to
print. Then produce that same list from every engine you run, and end the
implementation stage by loading the record and printing the key set per engine
side by side. Unequal sets are the defect, and that print is the whole test.

A field one engine does not give you is a parsing job, not a smaller table.
Convenience wrappers print a subset by design: the same binary usually has a
format string that names the columns, a per-pair or per-record file left in the
scratch directory, a verbose mode, or a second subcommand that carries the rest.
Open its output specification and go and get the field. Only after that search
has failed do you write that the named method does not report it — and then you
write it in the results section, in one sentence, with the invocation you tried,
before you print the incumbent's version labelled as the incumbent's.

## The byline goes in the sentence, not the methods section

Every number that discharges the task's output list names its producer where it
appears: in the column header, in the panel caption, in the abstract sentence,
in the conclusion. *"Method X reports the correspondence A→B with rotation U and
translation T"*, not *"the alignment is A→B"*. A reader who has to go to the
methods section to learn which program produced the deliverable will assume it
was whichever one the sentence around it is about.

Write down, at design time, which engine owns the deliverable, and treat that as
fixed. Engine choice is being made for you the moment one of them is easier to
parse, and convenience is not a reason to move the byline onto the tool the task
was not about.

## Checklist

- [ ] The deliverable's field list is written from the task's output list before any engine runs.
- [ ] Every engine's record carries the same keys; the key sets were printed and compared.
- [ ] A field missing from one engine was chased through its other output modes before being called unavailable.
- [ ] The printed object — transform, mapping, call set — is the named method's.
- [ ] Every deliverable sentence, column header and caption names its producing engine.
- [ ] The incumbent's version appears as a labelled comparison column, never unattributed.

## Why this is here

Measured on a protein-complex alignment task. The run's own
`outputs/alignment_7xg4_6n40.json` holds, for the named method, nine
chain-to-chain rows each with its rotation matrix and translation vector
(translation components 136.3–295.2 Å, largest rotation element per row
0.782–0.998) — the object the criterion on superposition vectors describes. Its
record for the incumbent carries `superimposition`, `rmsd`, `seq_id`,
`aligned_length` and `chain_correspondence`; its record for the named method
carries an assignment list, a row count and a byte count. The report printed the
incumbent's single transform in the results section, in the appendix table and
inside a figure panel; the named method's translation vector appears zero times
in it. The bare comparison agent printed that same vector as the method's own
and scored 17.0 on the superposition criterion against this run's 6.67, and 26.7
against 18.3 on the TM-score criterion, whose text attributes every quantity to
the named method. `life-the-correspondence-is-a-table-not-a-score` specifies the
per-row table; this is the rule about whose table it is.
