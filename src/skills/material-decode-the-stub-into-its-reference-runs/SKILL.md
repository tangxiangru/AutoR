---
name: material-decode-the-stub-into-its-reference-runs
description: Use at literature survey, study design and implementation when the supplied data is a short file of bare numeric literals under headers naming scripts or workflows - no column names, no units, no provenance - and the plan is forming around what the numbers are rather than which reference run they were the input to. Covers the decode table (array -> call signature -> role -> unit -> source of unit), choosing estimators whose conventional diagnostic is producible, and composing the blocks into each other for held-out evidence.
benchmarks: researchclawbench
stages: 01_literature_survey, 03_study_design, 04_implementation
---

# Decode the block into the run it was the input to

A few hundred bare numbers under headers that name scripts or workflows is not a
dataset. It is the *argument list* of a reference implementation somebody ran,
serialised. Every array in it was a variable with a name, a role and a unit, and
the run that produced the results you are being compared against had all three.

The failure this prevents: the run treats the file as a dataset, characterises it
well - closed forms, periodicity, degeneracy, collision structure - and then
reports every downstream quantity dimensionless: "in target units", "a normalised
objective", "index-aligned". The characterisation is correct and earns nothing,
because no number in it can be placed against any published number for the same
workflow. A dimensionless error reads as the physical error never having been
measured.

## Build the decode table before any model code

One row per array, written into the design document before the design is costed:

| array (length, first values) | block header it sits under | role in that workflow | physical quantity | unit | how the unit was assigned |

Fill **role** by writing out the call signature the block is the argument list
for, in order. A block headed with a property-prediction name holding an integer
array, a wide float array, a list of index pairs and a shorter float array is
`(atomic numbers, node features, edge index, targets)`. A block headed with an
optimisation name holding two 2-element arrays, two bare scalars, a small scalar
and a round integer is `(bound_1, bound_2, x0_1, x0_2, noise, budget)`. Write the
signature down. Where two readings survive, keep both rows and resolve it in the
next step, in writing: an unresolved ambiguity silently becomes "dimensionless"
three stages later.

## Assigning a unit when the file supplies none

The reporting rule - physical unit first, published band beside it - is already
`material-landmark-scalars-in-physical-units`, and mining the supplied papers for
the named quantity and the benchmark it is quoted on is already
`mine-the-papers-you-were-given`. Read those for the rule. What both assume, and
this file denies you, is that something in the workspace states the unit. Nothing
does. Assign one, from these sources, and record in the table which one you used:

1. **the numbers read against the process the header names** - a range that is
   ordinary in one unit and absurd in another decides itself; a start point that
   is round in one unit and ragged in the other is a second vote;
2. **the supplied papers** - they run this workflow on real material, in a unit,
   and quote an accuracy band in it. That is the unit a reader of this literature
   will convert your number into before judging it;
3. **the field's conventional unit for that quantity**, cited.

A unit assigned by assumption and stated once in a sentence is a unit. Silence is
not. "Target units", "normalised objective", "arbitrary units" and a bare index
axis are the same non-answer, and they are unrecoverable at writing time because
every table cell, axis label and abstract sentence inherits them.

## Shipped scalars enter the design at their shipped values

Every scalar the block ships - bounds, start point, noise level, budget, counts -
appears in the plan at its value and in the results quoted against it, in the
assigned units. The argument is
`material-as-specified-run-and-stage-diagnostics`; the only thing to add for a
stub file is the temptation specific to one. A synthetic block often looks
degenerate, or too easy, and redesigning it into a better benchmark deletes the
one piece of ground truth you were given. If you want the harder variant, run it
as a second arm beside the as-shipped one, never instead of it.

## Choose estimators whose conventional diagnostic is producible

Each block names a workflow, and each workflow has a diagnostic the field always
shows (`the-canonical-figure` lists them). Pick the estimator family at design
time so that the diagnostic can exist at all:

- a family with no iteration loop cannot emit an objective-versus-step trace.
  Choosing one deletes that result for the whole run, and no later stage can
  recover it - the numbers never existed;
- a rank statistic, a correlation or a p-value is not an error in a physical
  unit. If the field quotes an error, the estimator has to produce per-item
  predictions to take one from;
- a generative arm has to emit samples in the same coordinates as the population
  it was fit on, not only summary rates computed over them.

Cheaper families are good baselines beside the conventional one. They are not
substitutes for it, and a substitution made here is invisible by the time anyone
reads the report.

## The blocks compose - that is where the held-out evidence comes from

Blocks of one file are stages of one pipeline, and the cross-block runs are
usually the only unseen-input evidence available anywhere in the workspace:

- the generative block's samples are the predictive block's held-out input. Score
  them, and report that number separately from the in-sample one;
- the predictive block scores the optimisation block's proposals;
- a population the file did not contain, pushed through a model the file did
  train, is what "generalises beyond the supplied rows" means here.

Plan those runs in the design. They cost minutes, and nothing else in the file
supplies the evidence.

## Checklist before study design closes

- [ ] Every array has a row with a role, a quantity, a unit, and the source of that unit.
- [ ] Every ambiguous reading is resolved in writing, with the reason.
- [ ] No planned output is expressed in target units, a normalised objective, or an index.
- [ ] For each block: the field's conventional metric and diagnostic panel are named, and the chosen estimator can produce both.
- [ ] For each block: one published number in the same unit, taken from the supplied papers, is written down as the comparison target.
- [ ] Every shipped scalar appears at its shipped value; none was engineered away to make the study more interesting.
- [ ] At least one cross-block run is planned, with its own reported number.
