---
name: material-a-contingency-chooses-the-method-not-the-deliverable
description: Use at study design when you are writing a pre-registered branch, a cut order, a fallback or any go/no-go check that could fire later, and again at experimentation the moment one fires. Covers writing the branch table in artifacts rather than in hypotheses, the degraded producers available to a generative or search arm whose model underperforms, and the inventory check that catches a deleted deliverable before the report is written.
benchmarks: researchclawbench
applies_when: \b(?:vitrimer\w*|inverse-design framework)\b
stages: 03_study_design, 05_experimentation, 06_analysis
---

# A contingency chooses how the result is produced, never whether

Deciding in advance what you will do if a component underperforms is good practice, and it has one failure mode that eats an entire criterion. The branch gets written in the vocabulary of *hypotheses* — this comparison becomes `not tested`, that clause is unadjudicated — while the report is read as a set of *deliverables*. So a rule that looks like careful epistemics quietly removes a figure and a section, and the removal is invisible in the branch table, because the branch table is not written in those units.

Write the branch table in the units it will be graded in. For every contingency, list the figure slots and the section headings each arm produces, then check that the lists are identical across arms. If one arm's list is shorter, that arm is a deletion wearing a decision rule, and it needs rewriting before the run starts. The verdict on a hypothesis is free to change between branches. The artifact inventory is not.

## The fallback is a degraded producer, not an omission

The shape that works is: same panel, same axes, same target list, produced by whatever still works, with the degradation stated in the caption and in the methods. Before you accept that an arm cannot run, take the components apart and ask what each one can still do.

A generative-design arm whose decoder is too weak to emit valid structures still has a working encoder, and that is enough for the whole search. Encode the catalogue, optimise the objective over latent coordinates, and return the nearest catalogue member to the optimum: a latent-space optimiser that never needs a valid decode, producing the trajectory, the acquisition history and the achieved-versus-target numbers. Failing that, decode and snap each fragment to the nearest valid component by fingerprint similarity, reporting the snap distance as a column. The interpolation between two known endpoints and the property gradient across the embedding both need only the encoder as well.

Then write the caption that keeps it honest: "the decoder reaches N % validity at this budget, so the optimiser is restricted to the catalogue; the trajectory is real and the novelty claim is not." That sentence costs nothing and keeps the criterion alive. An empty column with a footnote pointing at your own internal test scores zero, and a reader cannot tell it apart from a step nobody attempted.

The same question is worth asking of every other component: a simulator you cannot run at production settings still runs at reduced settings on one system; a metric you cannot compute over the full set is computable over a stated subsample; a comparison you cannot make at equal budget is makeable at stated unequal budget with the ratio printed.

## The inventory check, before writing starts

Take the source's own list of results — one line per named target, per named comparison, per named validation — and write beside each the file in your image directory that carries it. Any line whose answer is the name of one of your own internal tests is the line to spend the remaining budget on, and the cheapest fix is nearly always a degraded producer rather than a rerun. `material-design-targets-span-the-property-range` gives the same rule for the specific case of a target deleted because it fell outside a validator's fitted range; this is the general form, and it applies to whole arms.

## Why this is here

Measured on Material_003. Study design fixed a branch test in advance — at least 30 of 1,000 latent samples must decode to a parseable bifunctional vitrimer — with branch B1, "trained, decoder fails", dropping the latent design arm, the latent-space design figure, H7's comparison and H9's clause B. The measured value was 5 valid of 1,000, B1 fired, and the delivered report's inverse-design caption reads "The latent-optimiser column is empty because the generative arm did not clear its pre-registered branch test." The branch table in the design note is written entirely in hypothesis verdicts and figure *slots*, and nothing in the run ever compared its two branches by what a reader would receive. The criterion about discovering candidates by optimisation in the latent space scored **3.3** across three gpt-5.1 draws against **43.3** for a bare agent that ran an evolutionary search in its own latent space plus a spherical interpolation between its lowest- and highest-Tg vitrimers; the judge's stated reason was that no plot depicted a latent-space optimisation trajectory or target acquisition. The encoder that arm needed was working the whole time: the same run published a PCA of 1,024 latent vectors as an exploratory figure.
